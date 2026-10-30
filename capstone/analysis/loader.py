"""Load a run directory into flat, typed per-item records.

Run directory layout (written by capstone/run/run_cut.sh):

    $RUN/config.json              run manifest (optional)
    $RUN/cap<C>/<domain>.json     benchmark_runner predictions
    $RUN/eval/cap<C>.json         evaluator output
    $RUN/traces/spans-*.jsonl     tracing span copies (optional, VAKRA_TRACE_DIR)

Only files that exist are used; missing pieces degrade gracefully.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CAPABILITY_DIRS = {
    1: "capability_1_bi_apis",
    2: "capability_2_dashboard_apis",
    3: "capability_3_multihop_reasoning",
    4: "capability_4_multiturn",
}
CAPABILITY_LABELS = {
    1: "API chaining",
    2: "Tool selection",
    3: "Multi-hop reasoning",
    4: "Multi-source + policy",
}
_EVAL_NAME_TO_ID = {
    "capability_bi_apis": 1,
    "capability_dashboard_apis": 2,
    "capability_multihop_reasoning": 3,
    "capability_multiturn": 4,
}
_CAP_FILE_RE = re.compile(r"cap(?:ability_)?(\d)")


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolSpan:
    """A traced tool invocation (from tracing JSONL), in start-time order."""

    name: str
    input: str
    output: str
    start_ns: int


@dataclass
class Item:
    """One benchmark item (dialogue) as seen across prediction, eval and GT."""

    run_id: str
    capability: int
    domain: str
    uuid: str
    # From predictions
    has_prediction: bool = False
    status: str | None = None
    error: str | None = None
    duration_s: float | None = None
    query: str = ""
    pred_answer: str = ""
    pred_calls: list[ToolCall] = field(default_factory=list)
    # From the evaluator
    scored: bool = False
    score: float | None = None
    turn_meta: dict[str, Any] = field(default_factory=dict)
    # From ground truth
    gt_answer: Any = None
    gt_calls: list[ToolCall] = field(default_factory=list)
    gt_responses: list[Any] = field(default_factory=list)
    # From tracing spans
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    n_llm_calls: int | None = None
    tool_spans: list[ToolSpan] = field(default_factory=list)

    @property
    def tool_outputs(self) -> list[str]:
        return [t.output for t in self.tool_spans]

    @property
    def key(self) -> tuple[int, str]:
        return (self.capability, self.uuid)


@dataclass
class Run:
    path: Path
    run_id: str
    manifest: dict[str, Any]
    items: list[Item]
    has_spans: bool

    @property
    def variant(self) -> str:
        return str(
            self.manifest.get("agent_variant") or self.manifest.get("variant") or "?"
        )

    def by_key(self) -> dict[tuple[int, str], Item]:
        return {it.key: it for it in self.items}


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def read_uuid_list(path: Path | None) -> set[str]:
    """One uuid per line; blank lines and '#' comments ignored. CSV first column ok."""
    if path is None:
        return set()
    uuids = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            first = line.split(",", 1)[0].strip()
            if first.lower() != "uuid":
                uuids.add(first)
    return uuids


def _calls(raw: Iterable[dict[str, Any]] | None) -> list[ToolCall]:
    out = []
    for c in raw or []:
        if isinstance(c, dict) and c.get("name"):
            args = c.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"_raw": args}
            out.append(
                ToolCall(
                    str(c["name"]), args if isinstance(args, dict) else {"_": args}
                )
            )
    return out


def _last_turn(record: dict[str, Any]) -> dict[str, Any]:
    turns = record.get("output") or [{}]
    return turns[-1] if isinstance(turns, list) and turns else {}


def _capability_of(path: Path, data: dict[str, Any] | None = None) -> int | None:
    if data and data.get("capability_name") in _EVAL_NAME_TO_ID:
        return _EVAL_NAME_TO_ID[data["capability_name"]]
    m = _CAP_FILE_RE.search(path.stem)
    return int(m.group(1)) if m else None


def load_run(path: Path, gt_root: Path | None = None) -> Run:
    path = Path(path)
    manifest_path = path / "config.json"
    manifest = read_json(manifest_path) if manifest_path.exists() else {}
    run_id = str(manifest.get("run_id") or path.name)
    items: dict[tuple[int, str], Item] = {}

    def item(cap: int, domain: str, uuid: str) -> Item:
        key = (cap, uuid)
        if key not in items:
            items[key] = Item(run_id=run_id, capability=cap, domain=domain, uuid=uuid)
        return items[key]

    # Evaluator output defines the ground-truth universe (n_groundtruth) per domain.
    for eval_path in sorted((path / "eval").glob("cap*.json")):
        data = read_json(eval_path)
        cap = _capability_of(eval_path, data)
        if cap is None:
            continue
        for domain, dom in (data.get("domains") or {}).items():
            for d in dom.get("dialogues") or []:
                it = item(cap, domain, str(d["uuid"]))
                it.scored = True
                it.score = float(d.get("score") or 0.0)
                turns = (d.get("details") or {}).get("per_turn") or [{}]
                it.turn_meta = turns[-1].get("metadata") or {}
                it.query = it.query or turns[-1].get("query", "")
            for uuid in dom.get("missing_prediction_uuids") or []:
                item(cap, domain, str(uuid))

    # Predictions.
    for cap_dir in sorted(path.glob("cap[0-9]")):
        cap = int(cap_dir.name[3:])
        for pred_path in sorted(cap_dir.glob("*.json")):
            if pred_path.stem.endswith("_tools"):
                continue
            records = read_json(pred_path)
            if not isinstance(records, list):
                continue
            for rec in records:
                if not isinstance(rec, dict) or "uuid" not in rec:
                    continue
                it = item(
                    cap, str(rec.get("domain") or pred_path.stem), str(rec["uuid"])
                )
                turn = _last_turn(rec)
                it.has_prediction = True
                it.status = rec.get("status")
                it.error = rec.get("error") or None
                it.duration_s = rec.get("duration_s")
                it.query = turn.get("query") or it.query
                answer = turn.get("answer", "")
                it.pred_answer = (
                    answer if isinstance(answer, str) else json.dumps(answer)
                )
                it.pred_calls = _calls((turn.get("sequence") or {}).get("tool_call"))

    if gt_root is not None:
        _attach_ground_truth(items.values(), Path(gt_root))
    has_spans = _attach_spans(items, path / "traces")
    ordered = sorted(items.values(), key=lambda it: (it.capability, it.domain, it.uuid))
    return Run(
        path=path, run_id=run_id, manifest=manifest, items=ordered, has_spans=has_spans
    )


def _attach_ground_truth(items: Iterable[Item], gt_root: Path) -> None:
    wanted: dict[tuple[int, str], list[Item]] = defaultdict(list)
    for it in items:
        wanted[(it.capability, it.domain)].append(it)
    for (cap, domain), group in wanted.items():
        gt_path = gt_root / CAPABILITY_DIRS.get(cap, "") / "output" / f"{domain}.json"
        if not gt_path.exists():
            continue
        by_uuid = {
            str(r.get("uuid")): r for r in read_json(gt_path) if isinstance(r, dict)
        }
        for it in group:
            rec = by_uuid.get(it.uuid)
            if rec is None:
                continue
            turn = _last_turn(rec)
            seq = turn.get("sequence") or {}
            it.gt_answer = turn.get("answer")
            it.gt_calls = _calls(seq.get("tool_call"))
            it.gt_responses = list(seq.get("tool_response") or [])
            it.query = it.query or turn.get("query", "")


def _attach_spans(items: dict[tuple[int, str], Item], trace_dir: Path) -> bool:
    files = sorted(trace_dir.glob("spans-*.jsonl")) if trace_dir.is_dir() else []
    if not files:
        return False
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            span = json.loads(line)
            cap, uuid = span.get("vakra.capability_id"), span.get("vakra.uuid")
            it = items.get((int(cap), str(uuid))) if cap is not None and uuid else None
            if it is None:
                continue
            kind = span.get("openinference.span.kind")
            if kind == "LLM":
                it.n_llm_calls = (it.n_llm_calls or 0) + 1
                for attr, name in (
                    ("llm.token_count.prompt", "prompt_tokens"),
                    ("llm.token_count.completion", "completion_tokens"),
                    ("llm.token_count.total", "total_tokens"),
                ):
                    if span.get(attr) is not None:
                        setattr(it, name, (getattr(it, name) or 0) + int(span[attr]))
            elif kind == "TOOL":
                it.tool_spans.append(
                    ToolSpan(
                        name=str(span.get("tool.name") or span.get("name")),
                        input=str(span.get("input.value") or ""),
                        output=str(span.get("output.value") or ""),
                        start_ns=int(span.get("start_ns") or 0),
                    )
                )
    for it in items.values():
        it.tool_spans.sort(key=lambda t: t.start_ns)
    return True
