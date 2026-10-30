"""Render one compact, slide-ready example trace as Markdown."""

from __future__ import annotations

import json
from typing import Any

from capstone.analysis.labels import Label
from capstone.analysis.loader import Item


def _short(value: Any, n: int) -> str:
    s = (
        value
        if isinstance(value, str)
        else json.dumps(value, ensure_ascii=False, default=str)
    )
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def render_trace(
    item: Item, label: Label | None = None, max_calls: int = 8, width: int = 110
) -> str:
    lines = [
        f"### Example trace: capability {item.capability} · {item.domain} · `{item.uuid}`",
        "",
        f"- **Run:** {item.run_id} · **score:** {item.score if item.score is not None else 'unscored'}"
        + (
            f" · **latency:** {item.duration_s:.1f}s"
            if item.duration_s is not None
            else ""
        )
        + (
            f" · **tokens:** {item.total_tokens}"
            if item.total_tokens is not None
            else ""
        ),
        f"- **Question:** {_short(item.query, width)}",
        "",
        "```text",
    ]
    if item.tool_spans:  # traced: show what the tools actually returned
        steps = [(t.name, t.input, t.output) for t in item.tool_spans]
    else:
        steps = [(c.name, c.arguments, None) for c in item.pred_calls]
    for i, (name, args, output) in enumerate(steps[:max_calls], 1):
        lines.append(f"{i}. {name}({_short(args, width - 20)})")
        if output is not None:
            lines.append(f"   -> {_short(output, width - 6)}")
    if len(steps) > max_calls:
        lines.append(f"... {len(steps) - max_calls} more tool calls")
    if not steps:
        lines.append("(no tool calls)")
    lines += [
        "```",
        "",
        f"- **Agent answer:** {_short(item.pred_answer or '(empty)', width)}",
    ]
    if item.gt_answer is not None:
        lines.append(f"- **Reference answer:** {_short(item.gt_answer, width)}")
    if item.gt_calls:
        gt = ", ".join(c.name for c in item.gt_calls[:max_calls])
        lines.append(f"- **Reference tool path:** {_short(gt, width)}")
    expl = (item.turn_meta or {}).get("score_explanation") or {}
    for key in ("answer", "groundedness", "policy"):
        if expl.get(key):
            lines.append(f"- **Judge ({key}):** {_short(expl[key], width)}")
    if label is not None and label.headline:
        lines.append(
            f"- **Error label:** {label.headline} / {label.subreason} ({label.source}, {label.confidence})"
        )
    return "\n".join(lines) + "\n"
