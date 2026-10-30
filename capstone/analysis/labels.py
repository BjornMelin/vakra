"""Error labels for wrong answers: deterministic rules first, plus human overrides.

Taxonomy (plan WS1.4; two headline labels, each with sub-reasons):

  not_supported (A)        the final answer is not backed by the right tool output
    - wrong_tool             a required tool was never called
    - wrong_arguments        right tool(s), wrong arguments
    - answer_not_in_output   tools returned data, the answer does not reflect it
    - no_answer              (auxiliary) agent errored / timed out / returned nothing
  supported_but_wrong (B)  the answer reflects the tool output, but is still wrong
    - wrong_reasoning        right calls and data, wrong conclusion
    - reference_wrong        the ground-truth answer itself is wrong
    - policy_violation       (auxiliary, capability 4) answer violated the policy

Rules, first match wins (``Label.rule`` names the one that fired):

  1 reference_wrong     uuid in the reference-wrong list
  2 no_answer           agent error or empty answer
  3 policy_violation    evaluator policy judge failed
  4 calls               predicted calls miss a GT tool / GT arguments -> A
  5 groundedness        evaluator groundedness judge < 0.5 -> A/answer_not_in_output
                        (the evaluator's own reason for the zero score)
  6 b1_deterministic    B1 traced every value (B/wrong_reasoning) or found an
                        untraced value (A/answer_not_in_output). Uses the run's
                        B1 verdict when present, else runs the same check here
                        (no judge) on the recorded tool outputs, or on the GT
                        responses when the calls match GT.
  7 b1_judge            the run's B1 judge verdict (supported / unsupported)
  8 support_ratio       token-overlap fallback (medium confidence)
  9 calls_match         calls match GT, nothing else known -> B/wrong_reasoning (low)

Each label carries a confidence and an evidence string, and the CSV has blank
human_* columns. A filled CSV can be fed back (``--labels``) and human labels
override the auto ones.
"""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from capstone.analysis.loader import Item, ToolCall

NOT_SUPPORTED = "not_supported"
SUPPORTED_BUT_WRONG = "supported_but_wrong"
SUBREASONS = {
    NOT_SUPPORTED: ("wrong_tool", "wrong_arguments", "answer_not_in_output", "no_answer"),
    SUPPORTED_BUT_WRONG: ("wrong_reasoning", "reference_wrong", "policy_violation"),
}
AUXILIARY_SUBREASONS = frozenset({"no_answer", "policy_violation"})
HEADLINE_OF = {sub: head for head, subs in SUBREASONS.items() for sub in subs}

SUPPORT_THRESHOLD = 0.6
_NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]{3,}")
_STOPWORDS = frozenset(
    [
        "the",
        "that",
        "this",
        "with",
        "from",
        "have",
        "were",
        "there",
        "their",
        "which",
        "what",
        "when",
        "where",
        "answer",
        "based",
        "data",
        "tool",
        "tools",
        "result",
        "results",
        "output",
        "following",
        "provided",
        "total",
        "number",
        "value",
        "values",
        "approximately",
        "about",
        "into",
        "than",
        "then",
        "also",
        "only",
        "been",
        "being",
        "more",
        "most",
        "none",
        "same",
        "such",
    ]
)


@dataclass
class Label:
    headline: str  # NOT_SUPPORTED / SUPPORTED_BUT_WRONG / "" (unknown)
    subreason: str
    confidence: str  # high / medium / low
    evidence: str
    source: str = "auto"
    rule: str = ""


def _norm_value(v: Any) -> Any:
    if isinstance(v, str):
        s = v.strip().lower()
        try:
            return float(s)
        except ValueError:
            return s
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, list):
        return [_norm_value(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _norm_value(x) for k, x in sorted(v.items())}
    return v


def _call_key(call: ToolCall) -> str:
    return json.dumps(
        [call.name, _norm_value(call.arguments)], sort_keys=True, default=str
    )


def compare_calls(pred: list[ToolCall], gt: list[ToolCall]) -> str:
    """'match', 'wrong_tool', 'wrong_arguments' or 'no_gt'."""
    if not gt:
        return "no_gt"
    pred_names = {c.name for c in pred}
    if any(c.name not in pred_names for c in gt):
        return "wrong_tool"
    pred_keys = {_call_key(c) for c in pred}
    if any(_call_key(c) not in pred_keys for c in gt):
        return "wrong_arguments"
    return "match"


def _numbers(text: str) -> set[str]:
    out = set()
    for m in _NUM_RE.findall(text):
        s = m.replace(",", "").rstrip(".")
        try:
            f = float(s)
        except ValueError:
            continue
        out.add(f"{round(f, 2):g}")
    return out


def _salient_tokens(text: str) -> tuple[set[str], set[str]]:
    words = {w.lower() for w in _WORD_RE.findall(text)} - _STOPWORDS
    return _numbers(text), words


def support_ratio(answer: str, outputs: Iterable[Any]) -> float | None:
    """Fraction of the answer's salient tokens found in the tool outputs.

    Returns None when the answer has no salient tokens or there is no output.
    """
    blob = " ".join(
        o if isinstance(o, str) else json.dumps(o, default=str) for o in outputs
    )
    if not blob.strip():
        return None
    a_nums, a_words = _salient_tokens(answer)
    if not a_nums and not a_words:
        return None
    o_nums, _ = _salient_tokens(blob)
    blob_l = blob.lower()
    hits = sum(1 for n in a_nums if n in o_nums) + sum(
        1 for w in a_words if w in blob_l
    )
    return hits / (len(a_nums) + len(a_words))


def _b1_verdict(item: Item, call_cmp: str) -> tuple[dict[str, Any] | None, str]:
    """The item's B1 verdict: recorded by a B1 run, else computed here.

    Computed verdicts use the deterministic path only (no judge) so labeling
    stays offline and free.
    """
    if item.verification:
        return item.verification, f"B1 run verdict ({item.tool_outputs_source or 'n/a'})"
    from capstone.b1.config import VerifierConfig
    from capstone.b1.step import B1Step

    record = item.trajectory_record()
    src = item.tool_outputs_source
    if record.get("tool_calls") is None and call_cmp == "match" and item.gt_responses:
        record["tool_calls"] = [
            {"name": c.name, "result": r} for c, r in zip(item.gt_calls, item.gt_responses)
        ]
        src = "GT responses (calls match GT)"
    if record.get("tool_calls") is None:
        return None, ""
    verdict = B1Step(VerifierConfig(), judge=None)(record)
    return verdict.model_dump(mode="json"), f"B1 check on {src}"


def auto_label(
    item: Item, *, reference_wrong: set[str] | None = None, use_b1: bool = True
) -> Label:
    """Label for a wrong (or unscored) item; see the module docstring for rules.

    ``use_b1=False`` skips rules 6-7, for scoring B1 against these labels
    without circularity (capstone.b1.verifier_eval).
    """
    meta = item.turn_meta or {}
    if reference_wrong and item.uuid in reference_wrong:
        return Label(
            SUPPORTED_BUT_WRONG, "reference_wrong", "high",
            "uuid in reference-wrong list", rule="reference_wrong",
        )
    if item.status == "error" or not (item.pred_answer or "").strip():
        why = (item.error or "empty answer")[:160]
        return Label(
            NOT_SUPPORTED, "no_answer", "high", f"agent status={item.status}: {why}",
            rule="no_answer",
        )
    if meta.get("policy_adherance_score") == 0:
        return Label(
            SUPPORTED_BUT_WRONG, "policy_violation", "high",
            "evaluator policy judge failed", rule="policy_violation",
        )

    call_cmp = compare_calls(item.pred_calls, item.gt_calls)
    if call_cmp in ("wrong_tool", "wrong_arguments"):
        return Label(
            NOT_SUPPORTED, call_cmp, "high", "pred vs GT tool calls", rule="calls"
        )

    grounded = meta.get("groundedness_score")
    if isinstance(grounded, (int, float)) and grounded < 0.5:
        return Label(
            NOT_SUPPORTED, "answer_not_in_output", "high",
            f"groundedness judge={grounded}", rule="groundedness",
        )

    verdict, v_src = _b1_verdict(item, call_cmp) if use_b1 else (None, "")
    if verdict is not None:
        why = f"{v_src}: {verdict['outcome']} ({verdict['reason']})"
        if verdict.get("failed_field"):
            why += f" untraced={verdict['failed_field']!r}"
        if verdict["b1_path"] == "deterministic" and verdict["outcome"] == "reject":
            return Label(NOT_SUPPORTED, "answer_not_in_output", "high", why, rule="b1_deterministic")
        if verdict["b1_path"] == "deterministic" and verdict["reason"] in ("all_traced", "names_traced"):
            return Label(SUPPORTED_BUT_WRONG, "wrong_reasoning", "high", why, rule="b1_deterministic")
        if verdict["reason"] == "judge_unsupported":
            return Label(NOT_SUPPORTED, "answer_not_in_output", "medium", why, rule="b1_judge")
        if verdict["reason"] == "judge_supported":
            return Label(SUPPORTED_BUT_WRONG, "wrong_reasoning", "medium", why, rule="b1_judge")

    # Which tool output did the agent actually see? Prefer recorded outputs; if
    # its calls exactly match GT, the GT responses are what it saw.
    if item.tool_outputs:
        seen, seen_src = item.tool_outputs, f"{item.tool_outputs_source} tool outputs"
    elif call_cmp == "match":
        seen, seen_src = item.gt_responses, "GT responses (calls match GT)"
    else:
        seen, seen_src = [], ""
    ratio = support_ratio(item.pred_answer, seen) if seen else None
    ratio_txt = (
        f"support={ratio:.2f} vs {seen_src}" if ratio is not None else "support=n/a"
    )
    if ratio is not None:
        if ratio < SUPPORT_THRESHOLD:
            return Label(
                NOT_SUPPORTED, "answer_not_in_output", "medium",
                f"calls={call_cmp}; {ratio_txt}", rule="support_ratio",
            )
        return Label(
            SUPPORTED_BUT_WRONG, "wrong_reasoning", "medium",
            f"calls={call_cmp}; {ratio_txt}", rule="support_ratio",
        )
    if call_cmp == "match":
        return Label(
            SUPPORTED_BUT_WRONG, "wrong_reasoning", "low",
            f"calls match GT; {ratio_txt}", rule="calls_match",
        )
    return Label("", "", "low", f"calls={call_cmp}; {ratio_txt}; needs human label")


LABEL_FIELDS = [
    "run_id",
    "capability",
    "domain",
    "uuid",
    "score",
    "query",
    "pred_answer",
    "gt_answer",
    "pred_tools",
    "gt_tools",
    "auto_headline",
    "auto_subreason",
    "auto_confidence",
    "auto_evidence",
    "auto_rule",
    "b1_outcome",
    "b1_path",
    "human_headline",
    "human_subreason",
    "human_notes",
]


def _fmt_calls(calls: list[ToolCall], limit: int = 8) -> str:
    parts = [
        f"{c.name}({json.dumps(c.arguments, default=str)[:80]})" for c in calls[:limit]
    ]
    if len(calls) > limit:
        parts.append(f"... +{len(calls) - limit}")
    return " | ".join(parts)


def label_rows(
    items: Iterable[Item], labels: dict[tuple[int, str], Label]
) -> list[dict[str, Any]]:
    rows = []
    for it in items:
        lab = labels[it.key]
        rows.append(
            {
                "run_id": it.run_id,
                "capability": it.capability,
                "domain": it.domain,
                "uuid": it.uuid,
                "score": it.score,
                "query": it.query,
                "pred_answer": (it.pred_answer or "")[:500],
                "gt_answer": json.dumps(it.gt_answer, default=str)[:500]
                if it.gt_answer is not None
                else "",
                "pred_tools": _fmt_calls(it.pred_calls),
                "gt_tools": _fmt_calls(it.gt_calls),
                "auto_headline": lab.headline,
                "auto_subreason": lab.subreason,
                "auto_confidence": lab.confidence,
                "auto_evidence": lab.evidence,
                "auto_rule": lab.rule,
                "b1_outcome": (it.verification or {}).get("outcome", ""),
                "b1_path": (it.verification or {}).get("b1_path", ""),
                "human_headline": "",
                "human_subreason": "",
                "human_notes": "",
            }
        )
    return rows


def read_human_labels(path: Path) -> dict[tuple[int, str], Label]:
    """Read a labeling CSV; returns human labels for rows where they were filled."""
    out: dict[tuple[int, str], Label] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            sub = (row.get("human_subreason") or "").strip()
            head = (row.get("human_headline") or "").strip() or HEADLINE_OF.get(sub, "")
            if not head and not sub:
                continue
            if sub and sub not in HEADLINE_OF:
                raise ValueError(f"{row['uuid']}: unknown sub-reason {sub!r}")
            if sub and HEADLINE_OF[sub] != head:
                raise ValueError(
                    f"{row['uuid']}: sub-reason {sub!r} does not belong to {head!r}"
                )
            if head and head not in SUBREASONS:
                raise ValueError(f"{row['uuid']}: unknown headline {head!r}")
            out[(int(row["capability"]), row["uuid"])] = Label(
                head,
                sub,
                "human",
                (row.get("human_notes") or "").strip(),
                source="human",
            )
    return out
