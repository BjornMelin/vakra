"""B1: check that a final answer's values trace back to the tool outputs.

Decision order (each answer takes exactly one path, logged as ``b1_path``):

1. No answer, or the agent errored          -> insufficient_evidence (deterministic)
2. Tool outputs were not recorded            -> insufficient_evidence (deterministic)
3. Numbers / dates / ids present             -> deterministic: all traced -> accept,
                                                any untraced -> reject
4. Only names present                        -> all found -> accept (deterministic);
                                                else judge (or reject, per config)
5. A refusal with nothing claimed            -> accept (deterministic), if configured
6. Free text with no checkable values        -> judge: supported / unsupported /
                                                insufficient; no judge -> insufficient
"""

from __future__ import annotations

import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from capstone.b1.config import VerifierConfig
from capstone.b1.evidence import EvidenceIndex
from capstone.b1.judge import Judge, JudgeResult
from capstone.b1.values import AnswerValue, extract_answer_values

VERIFIER_VERSION = "b1-0.1"

Outcome = Literal["accept", "reject", "insufficient_evidence"]
B1Path = Literal["deterministic", "judge"]
Reason = Literal[
    "all_traced",
    "untraced_value",
    "names_traced",
    "names_missing",
    "abstention",
    "no_answer",
    "agent_error",
    "tool_outputs_unknown",
    "judge_supported",
    "judge_unsupported",
    "judge_insufficient",
    "judge_unavailable",
    "verifier_error",
]

_ABSTAIN = re.compile(
    r"\b(?:i\s+(?:could\s*not|couldn'?t|can\s*not|can'?t|was\s+unable\s+to|am\s+unable\s+to|"
    r"was\s+not\s+able\s+to|do\s+not\s+have|don'?t\s+have)|"
    r"(?:no|not\s+enough)\s+(?:data|results?|records?|information|matching\s+\w+)\s+"
    r"(?:was\s+|were\s+|is\s+|are\s+)?(?:found|available|returned)|"
    r"unable\s+to\s+(?:find|determine|retrieve|locate|answer)|"
    r"(?:is|are)\s+not\s+available)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ToolOutput:
    name: str
    output: Any


@dataclass(frozen=True)
class VerifierInput:
    """One finished task, as B1 sees it."""

    query: str
    answer: str | None
    # None means "not recorded" (e.g. a B0 prediction file with no sidecar);
    # an empty list means the agent called no tools.
    tool_outputs: Sequence[ToolOutput] | None
    context: str = ""
    status: str = "success"
    error: str | None = None


class ValueCheck(BaseModel):
    kind: str
    raw: str
    normalized: str
    unit: str | None = None
    traced: bool
    via: str | None = None
    evidence_id: str | None = None


class Verdict(BaseModel):
    outcome: Outcome
    # Status label used by the plan's per-check log: passed / failed / insufficient_evidence.
    status: Literal["passed", "failed", "insufficient_evidence"]
    b1_path: B1Path
    reason: Reason
    values: list[ValueCheck] = Field(default_factory=list)
    failed_field: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    n_tool_outputs: int | None = None
    judge: JudgeResult | None = None
    duration_s: float = 0.0
    action: Literal["kept", "abstained"] = "kept"
    original_answer: str | None = None
    answer_returned: str | None = None
    error: str | None = None
    verifier_version: str = VERIFIER_VERSION
    config_sha256: str | None = None


_STATUS = {"accept": "passed", "reject": "failed", "insufficient_evidence": "insufficient_evidence"}


def is_abstention(answer: str) -> bool:
    return bool(_ABSTAIN.search(answer))


def evidence_text(inp: VerifierInput, max_chars: int) -> str:
    """Tool outputs rendered for the judge, one block per call."""
    parts = []
    for i, t in enumerate(inp.tool_outputs or []):
        body = t.output if isinstance(t.output, str) else repr(t.output)
        parts.append(f"[t{i}:{t.name}]\n{body}")
    text = "\n\n".join(parts) or "(no tool outputs)"
    return text[:max_chars]


def verify(inp: VerifierInput, cfg: VerifierConfig, judge: Judge | None = None) -> Verdict:
    """Run the B1 check on one finished task. Never raises on bad input."""
    t0 = time.perf_counter()

    def done(outcome: Outcome, path: B1Path, reason: Reason, **kw: Any) -> Verdict:
        v = Verdict(
            outcome=outcome,
            status=_STATUS[outcome],  # type: ignore[arg-type]
            b1_path=path,
            reason=reason,
            config_sha256=cfg.sha256(),
            **kw,
        )
        v.duration_s = round(time.perf_counter() - t0, 6)
        return apply_policy(v, inp.answer, cfg)

    answer = (inp.answer or "").strip()
    if inp.status != "success" or inp.error:
        return done("insufficient_evidence", "deterministic", "agent_error")
    if not answer:
        return done("insufficient_evidence", "deterministic", "no_answer")
    if inp.tool_outputs is None:
        return done("insufficient_evidence", "deterministic", "tool_outputs_unknown")

    index = EvidenceIndex.build(
        [(t.name, t.output) for t in inp.tool_outputs],
        query=inp.query if cfg.allow_query_values else "",
        context=inp.context if cfg.allow_query_values else "",
        derivations=cfg.derivations,
    )
    n_out = index.n_tool_outputs
    ex = extract_answer_values(answer)
    checks = [_check(index, v) for v in ex.values]
    hard = [c for c, v in zip(checks, ex.values) if v.kind != "name"]
    names = [c for c, v in zip(checks, ex.values) if v.kind == "name"]
    eids = sorted({c.evidence_id for c in checks if c.evidence_id})
    common: dict[str, Any] = {"values": checks, "evidence_ids": eids, "n_tool_outputs": n_out}

    if hard:
        missing = [c for c in hard if not c.traced]
        if missing:
            return done("reject", "deterministic", "untraced_value", failed_field=missing[0].raw, **common)
        return done("accept", "deterministic", "all_traced", **common)

    if names:
        missing = [c for c in names if not c.traced]
        if not missing:
            return done("accept", "deterministic", "names_traced", **common)
        if cfg.names_missing == "reject" and not is_abstention(answer):
            return done("reject", "deterministic", "names_missing", failed_field=missing[0].raw, **common)
        common["failed_field"] = missing[0].raw

    if cfg.accept_abstentions and is_abstention(answer):
        return done("accept", "deterministic", "abstention", **common)

    if judge is None or not cfg.judge.enabled:
        return done("insufficient_evidence", "judge", "judge_unavailable", **common)
    jr = judge(query=inp.query, evidence=evidence_text(inp, cfg.judge.max_evidence_chars), answer=answer)
    if jr.verdict == "supported":
        return done("accept", "judge", "judge_supported", judge=jr, **common)
    if jr.verdict == "unsupported":
        common["failed_field"] = jr.unsupported_claim or common.get("failed_field")
        return done("reject", "judge", "judge_unsupported", judge=jr, **common)
    reason: Reason = "judge_unavailable" if jr.error else "judge_insufficient"
    return done("insufficient_evidence", "judge", reason, judge=jr, **common)


_CONJ = re.compile(r"\s+(?:and|&)\s+")


def _check(index: EvidenceIndex, v: AnswerValue) -> ValueCheck:
    tr = index.trace(v)
    if tr is None and v.kind == "name" and _CONJ.search(v.norm):
        # "Smith and Jones": traced if every part is (one evidence id is reported).
        parts = [index.trace(AnswerValue("name", p, p)) for p in _CONJ.split(v.norm)]
        if all(parts):
            tr = parts[0]
    return ValueCheck(
        kind=v.kind,
        raw=v.raw,
        normalized=v.norm,
        unit=v.unit,
        traced=tr is not None,
        via=tr.via if tr else None,
        evidence_id=tr.evidence_id if tr else None,
    )


def apply_policy(v: Verdict, answer: str | None, cfg: VerifierConfig) -> Verdict:
    """WS2.4 reject policy: keep the B0 answer (flag) or abstain."""
    abstain = (v.outcome == "reject" and cfg.on_reject == "abstain") or (
        v.outcome == "insufficient_evidence" and cfg.on_insufficient == "abstain"
    )
    v.action = "abstained" if abstain else "kept"
    v.original_answer = answer
    v.answer_returned = cfg.abstain_text if abstain else answer
    return v
