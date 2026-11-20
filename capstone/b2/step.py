"""Decide, for one task, whether B2 runs one recovery and what answer remains.

The attempt count is ``recovery_step_cap`` from the config. There is no
built-in cap of 1. Session B's design is one attempt; that number has to be
set in the config. A cap hit, an error, or a rejected re-check uses the
configured policy. An accepted re-check keeps the recovery answer. An
insufficient re-check uses ``on_insufficient``.
"""

from __future__ import annotations

import asyncio
import copy
from typing import Any, Mapping

from capstone.b1.step import B1Step
from capstone.b1.verifier import Verdict
from capstone.b2.config import B2Config, B2ConfigError, count_prompt_tokens
from capstone.b2.control import control_trigger_ids
from capstone.b2.executor import RecoveryExecutor

_RESUME = (
    "The answer check rejected the previous answer.\n"
    "Reason: {reason}\n"
    "Failed field: {failed_field}\n"
    "Previous answer: {answer}\n"
    "Question: {query}\n"
    "Tool outputs so far:\n"
    "{evidence}\n"
    "Make one more attempt. The answer must be supported by tool output.\n"
)


class B2Step:
    variant = "B2"

    def __init__(
        self,
        cfg: B2Config,
        b1: B1Step,
        *,
        task_ids: list[str] | None = None,
        executor: RecoveryExecutor | None = None,
    ) -> None:
        cfg.validate_launch()
        self.cfg = cfg
        self.b1 = b1
        self.executor = executor
        if cfg.arm == "random_control":
            if not task_ids:
                raise B2ConfigError(
                    "B2 REFUSING TO LAUNCH: random_control needs the explicit "
                    "task-id universe to draw the matched sample."
                )
            self.triggers = control_trigger_ids(
                task_ids, cfg.matched_trigger_count, cfg.control_seed  # type: ignore[arg-type]
            )
        else:
            self.triggers = None

    def bind_executor(self, executor: RecoveryExecutor) -> None:
        self.executor = executor

    def __call__(self, record: Mapping[str, Any]) -> Verdict:
        raise B2ConfigError(
            "B2 REFUSING TO LAUNCH: recovery is async. Call decide(), not the "
            "synchronous B1 hook. A sync call would skip the recovery."
        )

    def describe(self) -> dict[str, Any]:
        out = self.cfg.live_dict()
        out["b1"] = self.b1.describe()
        if self.triggers is not None:
            out["control_trigger_count"] = len(self.triggers)
        return out

    def triggered(self, record: Mapping[str, Any], verdict: Verdict) -> bool:
        if self.cfg.arm == "random_control":
            return str(record.get("uuid")) in (self.triggers or ())
        return verdict.outcome == "reject"

    async def decide(self, record: Mapping[str, Any]) -> tuple[Verdict, dict[str, Any]]:
        verdict = await asyncio.to_thread(self.b1, record)
        original = record.get("answer")
        decision: dict[str, Any] = {
            "arm": self.cfg.arm,
            "triggered": False,
            "recovery_attempted": False,
            "recovery_attempts": 0,
            "recovery_tool_calls": [],
            "n_recovery_tool_calls": 0,
            "n_recovery_llm_calls": 0,
            "final_answer_changed": False,
            "abstained": False,
            "skip_reason": None,
            "stop_reason": "not_triggered",
            "policy_applied": None,
            "recheck_outcome": None,
            "b1_outcome": verdict.outcome,
            "resume_prompt_tokens": None,
            "prompt_token_count_method": self.cfg.prompt_token_count_method,
        }
        if not self.triggered(record, verdict):
            return verdict, decision

        decision["triggered"] = True
        prompt = resume_prompt(record, verdict)
        n_tokens = count_prompt_tokens(prompt, self.cfg.prompt_token_count_method or "")
        decision["resume_prompt_tokens"] = n_tokens
        if n_tokens > int(self.cfg.max_resume_prompt_tokens or 0):
            decision["skip_reason"] = "resume_prompt_tokens"
            decision["stop_reason"] = "skipped_resume_prompt"
            return verdict, decision

        if self.executor is None:
            raise B2ConfigError(
                "B2 REFUSING TO LAUNCH: a recovery was triggered but no executor "
                "is bound. Refusing instead of leaving the B0 answer silently."
            )

        working = verdict
        calls: list[dict[str, Any]] = []
        llm_calls = 0
        for _ in range(int(self.cfg.recovery_step_cap or 0)):
            decision["recovery_attempted"] = True
            decision["recovery_attempts"] += 1
            try:
                attempt = await asyncio.wait_for(
                    self.executor.attempt(
                        prompt=prompt,
                        max_tool_calls=int(self.cfg.max_recovery_tool_calls or 0),
                        max_llm_calls=int(self.cfg.max_recovery_llm_calls or 0),
                        timeout_s=float(self.cfg.recovery_timeout_s or 0),
                    ),
                    timeout=float(self.cfg.recovery_timeout_s or 0),
                )
            except asyncio.TimeoutError:
                return self._finish(
                    original, verdict, decision, calls, llm_calls,
                    stop_reason="cap_hit", policy=self.cfg.on_cap_hit,
                )
            except Exception as exc:
                decision["error"] = f"{type(exc).__name__}: {exc}"
                return self._finish(
                    original, verdict, decision, calls, llm_calls,
                    stop_reason="error", policy=self.cfg.on_error,
                )
            if attempt.error:
                decision["error"] = attempt.error
                return self._finish(
                    original, verdict, decision, calls, llm_calls,
                    stop_reason="error", policy=self.cfg.on_error,
                )
            got = list(attempt.tool_calls)
            llm_calls += int(attempt.llm_calls)
            calls.extend(got)
            if (
                len(got) > int(self.cfg.max_recovery_tool_calls or 0)
                or llm_calls > int(self.cfg.max_recovery_llm_calls or 0)
            ):
                return self._finish(
                    original, verdict, decision, calls, llm_calls,
                    stop_reason="cap_hit", policy=self.cfg.on_cap_hit,
                )
            recheck_record = record_with_recovery(record, attempt.answer, calls)
            working = await asyncio.to_thread(self.b1, recheck_record)
            decision["recheck_outcome"] = working.outcome
            if working.outcome == "accept":
                changed = working.answer_returned != original
                decision.update(
                    recovery_tool_calls=_public_calls(calls),
                    n_recovery_tool_calls=len(calls),
                    n_recovery_llm_calls=llm_calls,
                    final_answer_changed=changed,
                    abstained=False,
                    stop_reason="accepted",
                    policy_applied=None,
                )
                return working, decision
            if working.outcome == "insufficient_evidence":
                return self._finish(
                    original, working, decision, calls, llm_calls,
                    stop_reason="insufficient", policy=self.cfg.on_insufficient,
                )
            # still reject: another attempt only if the cap has room
        return self._finish(
            original, working, decision, calls, llm_calls,
            stop_reason="rejected", policy=self.cfg.on_reject,
        )

    def _finish(
        self,
        original: Any,
        verdict: Verdict,
        decision: dict[str, Any],
        calls: list[dict[str, Any]],
        llm_calls: int,
        *,
        stop_reason: str,
        policy: str | None,
    ) -> tuple[Verdict, dict[str, Any]]:
        returned, abstained = apply_policy(
            policy or "",
            original=original,
            abstain_text=self.b1.cfg.abstain_text,
            verdict=verdict,
        )
        decision.update(
            recovery_tool_calls=_public_calls(calls),
            n_recovery_tool_calls=len(calls),
            n_recovery_llm_calls=llm_calls,
            final_answer_changed=returned.answer_returned != original,
            abstained=abstained,
            stop_reason=stop_reason,
            policy_applied=policy,
        )
        return returned, decision


def resume_prompt(record: Mapping[str, Any], verdict: Verdict) -> str:
    blocks = []
    for call in record.get("tool_calls") or []:
        name = call.get("name") or call.get("tool_name") or ""
        blocks.append(f"{name}: {call.get('result')}")
    return _RESUME.format(
        reason=verdict.reason,
        failed_field=verdict.failed_field,
        answer=record.get("answer"),
        query=record.get("query"),
        evidence="\n".join(blocks),
    )


def record_with_recovery(
    record: Mapping[str, Any], answer: str | None, calls: list[dict[str, Any]]
) -> dict[str, Any]:
    rec = copy.deepcopy(dict(record))
    rec["answer"] = answer
    base = list(rec.get("tool_calls") or [])
    extra = []
    for call in calls:
        extra.append(
            {
                "name": call.get("name") or "",
                "arguments": call.get("arguments") or {},
                "result": call.get("result"),
            }
        )
    if rec.get("tool_calls") is not None or extra:
        rec["tool_calls"] = base + extra
    return rec


def apply_policy(
    policy: str, *, original: Any, abstain_text: str, verdict: Verdict
) -> tuple[Verdict, bool]:
    out = verdict.model_copy(deep=True)
    out.original_answer = original if isinstance(original, str) or original is None else str(original)
    if policy == "flag_keep_original":
        out.action = "kept"
        out.answer_returned = original if isinstance(original, str) or original is None else str(original)
        return out, False
    if policy == "abstain":
        out.action = "abstained"
        out.answer_returned = abstain_text
        return out, True
    raise B2ConfigError(
        f"B2 REFUSING TO LAUNCH: unknown policy {policy!r}."
    )


def _public_calls(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"name": c.get("name") or "", "arguments": c.get("arguments") or {}}
        for c in calls
    ]
