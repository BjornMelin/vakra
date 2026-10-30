"""B1 as a post-answer step on the shared runner, and the record adapter that
replay uses too, so inline and offline B1 run the same code."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from capstone.b1.config import VerifierConfig
from capstone.b1.judge import PROMPT_SHA256, Judge, build_judge
from capstone.b1.verifier import ToolOutput, Verdict, VerifierInput, verify
from capstone.trajectories import context_text


def input_from_record(record: Mapping[str, Any]) -> VerifierInput:
    """VerifierInput from a trajectory sidecar record.

    A record without a ``tool_calls`` key (tool outputs not recorded) gives
    ``tool_outputs=None`` so the verdict is insufficient_evidence, not reject.
    """
    calls = record.get("tool_calls")
    outputs: list[ToolOutput] | None
    if calls is None:
        outputs = None
    else:
        outputs = []
        if record.get("initial_data") is not None:
            outputs.append(ToolOutput("get_data", record["initial_data"]))
        outputs += [ToolOutput(str(c.get("name", "")), c.get("result")) for c in calls]
    return VerifierInput(
        query=str(record.get("query") or ""),
        answer=record.get("answer"),
        tool_outputs=outputs,
        context=context_text(record.get("context")),
        status=str(record.get("status") or "success"),
        error=record.get("error") or None,
    )


class B1Step:
    variant = "B1"

    def __init__(self, cfg: VerifierConfig, judge: Judge | None) -> None:
        self.cfg = cfg
        self.judge = judge

    @classmethod
    def from_config_file(cls, path: str | Path | None) -> B1Step:
        cfg = VerifierConfig.load(path)
        return cls(cfg, build_judge(cfg.judge))

    def __call__(self, record: Mapping[str, Any]) -> Verdict:
        try:
            return verify(input_from_record(record), self.cfg, self.judge)
        except Exception as exc:  # the check must never lose the agent's answer
            return verifier_error(record, self.cfg, exc)

    def describe(self) -> dict[str, Any]:
        return describe_config(self.cfg, judge_model=getattr(self.judge, "model", None))


def verifier_error(record: Mapping[str, Any], cfg: VerifierConfig, exc: BaseException) -> Verdict:
    return Verdict(
        outcome="insufficient_evidence",
        status="insufficient_evidence",
        b1_path="deterministic",
        reason="verifier_error",
        error=f"{type(exc).__name__}: {exc}",
        answer_returned=record.get("answer"),
        original_answer=record.get("answer"),
        config_sha256=cfg.sha256(),
    )


def describe_config(cfg: VerifierConfig, judge_model: str | None = None) -> dict[str, Any]:
    """What the manifest records about B1 (WS2.2: judge model + prompt hash)."""
    return {
        "verifier": cfg.model_dump(mode="json"),
        "config_sha256": cfg.sha256(),
        "judge_prompt_sha256": PROMPT_SHA256,
        "judge_model_resolved": judge_model,
    }
