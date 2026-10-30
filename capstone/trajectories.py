"""Per-task trajectory sidecars: ``cap<C>/<domain>_trajectory.json``.

The prediction files the evaluator reads (``cap<C>/<domain>.json``) keep the
upstream format and drop tool outputs. B1 needs those outputs, and so do the
error labels, so the runner writes them next to the predictions for every
variant (B0, B1, B2). The evaluator only opens ``<domain>.json`` and ignores
sidecars.

Record format (one per task)::

    {"uuid", "domain", "turn_id", "query", "context", "status", "error",
     "answer",                       # the agent's own answer (a B1 replacement is
                                     #   in verification.answer_returned)
     "tool_calls": [{"name", "arguments", "result", "result_truncated"}],
     "initial_data": {...} | null,   # capability 1 get_data peek
     "verification": {...} | null}   # B1 verdict (capstone.b1.verifier.Verdict)
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

TRAJECTORY_SUFFIX = "_trajectory"
TOOLS_SUFFIX = "_tools"
SIDECAR_SUFFIXES = (TOOLS_SUFFIX, TRAJECTORY_SUFFIX)
MAX_RESULT_CHARS = 1_000_000


def is_sidecar(path: Path) -> bool:
    return path.stem.endswith(SIDECAR_SUFFIXES)


def trajectory_path(pred_dir: Path, domain: str) -> Path:
    return pred_dir / f"{domain}{TRAJECTORY_SUFFIX}.json"


def tool_result_text(result: Any) -> str:
    """MCP / LangChain tool content as text (content blocks are joined)."""
    if isinstance(result, str):
        return result
    if isinstance(result, list) and all(isinstance(b, Mapping) and "text" in b for b in result):
        return "\n".join(str(b["text"]) for b in result)
    try:
        return json.dumps(result, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(result)


def tool_call_record(tc: Mapping[str, Any]) -> dict[str, Any]:
    """One runner tool call ({tool_name, arguments, result}) as a sidecar entry."""
    text = tool_result_text(tc.get("result"))
    return {
        "name": tc.get("tool_name") or tc.get("name") or "",
        "arguments": tc.get("arguments") or {},
        "result": text[:MAX_RESULT_CHARS],
        "result_truncated": len(text) > MAX_RESULT_CHARS,
    }


def context_records(context: Any) -> list[dict[str, str]] | None:
    """Capability-4 dialogue context as JSON-able [{role, content}]."""
    if not context:
        return None
    out = []
    for turn in context if isinstance(context, list) else [context]:
        if isinstance(turn, Mapping):
            out.append({"role": str(turn.get("role", "")), "content": str(turn.get("content", ""))})
        else:
            out.append({"role": str(getattr(turn, "role", "")), "content": str(getattr(turn, "content", turn))})
    return out


def context_text(context: Any) -> str:
    """Capability-4 dialogue context (earlier turns) as plain text."""
    if isinstance(context, str):
        return context
    return "\n".join(f"{t['role']}: {t['content']}" for t in context_records(context) or [])


def build_record(
    *,
    uuid: str,
    domain: str,
    query: str,
    answer: str,
    tool_calls: Iterable[Mapping[str, Any]],
    turn_id: int = 0,
    context: Any = None,
    status: str = "success",
    error: str = "",
    initial_data: Any = None,
    verification: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One trajectory sidecar record (see module docstring)."""
    return {
        "uuid": uuid,
        "domain": domain,
        "turn_id": turn_id,
        "query": query,
        "context": context_records(context),
        "status": status,
        "error": error,
        "answer": answer,
        "tool_calls": [tool_call_record(tc) for tc in tool_calls],
        "initial_data": initial_data,
        "verification": dict(verification) if verification is not None else None,
    }


def write_trajectories(records: Iterable[Mapping[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(list(records), indent=1, ensure_ascii=False, default=str), encoding="utf-8")


def read_trajectories(path: Path) -> dict[str, dict[str, Any]]:
    """uuid -> trajectory record; {} when the sidecar is absent or unreadable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, list):
        return {}
    return {str(r["uuid"]): r for r in data if isinstance(r, dict) and "uuid" in r}
