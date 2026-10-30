"""Recover tool outputs for runs that did not record them (pre-B1 B0 runs).

Re-executes each prediction's tool calls against the capability's MCP server,
in the same way and order as the evaluator (``evaluator/mcp_tools.py``:
schema-coerced arguments, first content block's text, capability 1 gets
``get_data(tool_universe_id=uuid)`` first). Writes trajectory sidecars to a
separate directory, never into the source run::

    OUT/cap<C>/<domain>_trajectory.json   tool_outputs_source = "reexecuted"

Then ``python -m capstone.b1 replay --tool-outputs OUT ...``.

Re-execution reproduces what the agent saw only if the tools are
deterministic read-only queries over the (unchanged) SQLite DBs. That holds
for the VAKRA MCP servers; the records are still marked "reexecuted" so
results can be reported separately from recorded outputs. Needs the MCP
containers (droplet), so it is not exercised by the offline tests except
through a fake session.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from capstone.analysis.loader import read_json
from capstone.trajectories import build_record, is_sidecar, trajectory_path, write_trajectories

_EVALUATOR_DIR = Path(__file__).resolve().parents[2] / "evaluator"


class ToolSession(Protocol):
    """The part of ``mcp.ClientSession`` used here."""

    async def list_tools(self) -> Any: ...
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any: ...


def _evaluator_coerce():
    # The evaluator modules import each other by bare name (run from evaluator/).
    if str(_EVALUATOR_DIR) not in sys.path:
        sys.path.append(str(_EVALUATOR_DIR))
    from mcp_tools import _coerce_args_to_schema  # type: ignore[import-not-found]

    return _coerce_args_to_schema


def _content_text(result: Any) -> str:
    content = getattr(result, "content", None) or []
    if not content:
        return ""
    first = content[0]
    return first.text if hasattr(first, "text") else str(first)


def last_turn_calls(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    turns = record.get("output") or [{}]
    seq = (turns[-1] if turns else {}).get("sequence") or {}
    out = []
    for c in seq.get("tool_call") or []:
        if isinstance(c, Mapping) and c.get("name"):
            args = c.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            out.append({"name": str(c["name"]), "arguments": args})
    return out


async def reexecute_record(
    session: ToolSession,
    record: Mapping[str, Any],
    schema_map: Mapping[str, Any],
    *,
    capability: int,
) -> dict[str, Any]:
    """Trajectory record for one prediction with re-executed tool outputs."""
    coerce = _evaluator_coerce()
    uuid = str(record.get("uuid"))
    initial_data = None
    if capability == 1:
        peek = _content_text(await session.call_tool("get_data", {"tool_universe_id": uuid}))
        try:
            initial_data = json.loads(peek)
        except json.JSONDecodeError:
            initial_data = peek
    calls = []
    for c in last_turn_calls(record):
        try:
            args = coerce(dict(c["arguments"]), schema_map.get(c["name"]))
            text = _content_text(await session.call_tool(c["name"], args))
        except Exception as exc:  # mirror the evaluator: errors become outputs
            text = f"Error: {exc}"
        calls.append({"tool_name": c["name"], "arguments": c["arguments"], "result": text})
    turns = record.get("output") or [{}]
    last = turns[-1] if turns else {}
    context = [
        {"role": role, "content": str(t.get(key) or "")}
        for t in turns[:-1]
        for role, key in (("user", "query"), ("assistant", "answer"))
    ]
    rec = build_record(
        uuid=uuid,
        domain=str(record.get("domain") or ""),
        turn_id=last.get("turn_id", 0),
        query=str(last.get("query") or ""),
        answer=last.get("answer", ""),
        tool_calls=calls,
        context=context or None,
        status=str(record.get("status") or "success"),
        error=record.get("error") or "",
        initial_data=initial_data,
    )
    rec["tool_outputs_source"] = "reexecuted"
    return rec


async def collect_domain(
    session: ToolSession, records: Sequence[Mapping[str, Any]], *, capability: int
) -> list[dict[str, Any]]:
    from environment.mcp_compat import tool_input_schema

    tools = await session.list_tools()
    schema_map = {t.name: tool_input_schema(t) for t in tools.tools}
    return [
        await reexecute_record(session, r, schema_map, capability=capability)
        for r in records
        if isinstance(r, Mapping) and r.get("uuid")
    ]


async def collect_run(
    src: Path, out: Path, *, mcp_config: Path, caps: set[int] | None = None
) -> dict[str, int]:
    """Re-execute every prediction in ``src``; returns tasks collected per cap dir."""
    from benchmark.mcp_client import create_client_and_connect, load_mcp_config

    configs = load_mcp_config(str(mcp_config))
    counts: dict[str, int] = {}
    for cap_dir in sorted(Path(src).glob("cap[0-9]")):
        cap = int(cap_dir.name[3:])
        if (caps and cap not in caps) or cap not in configs:
            continue
        for pred_path in sorted(cap_dir.glob("*.json")):
            if is_sidecar(pred_path):
                continue
            records = read_json(pred_path)
            domain = pred_path.stem
            async with create_client_and_connect(configs[cap], domain) as session:
                recs = await collect_domain(session, records, capability=cap)
            write_trajectories(recs, trajectory_path(Path(out) / cap_dir.name, domain))
            counts[cap_dir.name] = counts.get(cap_dir.name, 0) + len(recs)
    return counts
