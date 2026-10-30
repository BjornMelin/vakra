"""Offline B1: run the B1 step over an existing B0 run directory (plan WS2.3).

Writes a new run directory in the normal layout, so the analysis CLI and the
evaluator treat it like an inline B1 run:

    OUT/config.json                    source manifest + agent_variant=B1, replay_of, b1
    OUT/cap<C>/<domain>.json           predictions; answers replaced only when the
                                       policy abstains (on_reject/on_insufficient)
    OUT/cap<C>/<domain>_trajectory.json   tool outputs + B1 verdict per task
    OUT/cap<C>/<domain>_tools.json     copied from the source run
    OUT/eval/cap<C>.json               copied when no answer in that capability
                                       changed (scores are identical); otherwise
                                       re-score with SKIP_AGENTS=1 RUN_ID=<OUT name>

The source run is never modified. Tool outputs come from the source run's
trajectory sidecars, then ``tool_outputs_dir`` (``collect`` output), then
traced spans; tasks with none get insufficient_evidence (tool_outputs_unknown).
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import shutil
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from capstone.analysis.loader import load_run, read_json
from capstone.b1.step import B1Step
from capstone.trajectories import is_sidecar, trajectory_path, write_trajectories


@dataclass
class ReplaySummary:
    out_dir: Path
    n_tasks: int = 0
    outcomes: Counter = field(default_factory=Counter)  # (path, outcome) -> n
    tool_outputs_source: Counter = field(default_factory=Counter)
    n_answers_changed: int = 0
    eval_copied: list[int] = field(default_factory=list)
    needs_rescore: list[int] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "out_dir": str(self.out_dir),
            "n_tasks": self.n_tasks,
            "outcomes": {f"{p}/{o}": n for (p, o), n in sorted(self.outcomes.items())},
            "tool_outputs_source": dict(self.tool_outputs_source),
            "n_answers_changed": self.n_answers_changed,
            "eval_copied_caps": self.eval_copied,
            "needs_rescore_caps": self.needs_rescore,
        }


def _set_last_answer(record: dict[str, Any], answer: Any) -> None:
    turns = record.get("output") or []
    if turns:
        turns[-1]["answer"] = answer


def replay_run(
    src: Path,
    out: Path,
    step: B1Step,
    *,
    tool_outputs_dir: Path | None = None,
    caps: set[int] | None = None,
) -> ReplaySummary:
    src, out = Path(src).resolve(), Path(out).resolve()
    if out == src:
        raise ValueError("replay output must be a new directory, not the source run")
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"{out} exists and is not empty")
    run = load_run(src, tool_outputs_dir=tool_outputs_dir)
    items = run.by_key()
    summary = ReplaySummary(out_dir=out)
    out.mkdir(parents=True, exist_ok=True)

    for cap_dir in sorted(src.glob("cap[0-9]")):
        cap = int(cap_dir.name[3:])
        if caps and cap not in caps:
            continue
        out_cap = out / cap_dir.name
        out_cap.mkdir(parents=True, exist_ok=True)
        changed = 0
        for pred_path in sorted(cap_dir.glob("*.json")):
            if is_sidecar(pred_path):
                if pred_path.stem.endswith("_tools"):
                    shutil.copy2(pred_path, out_cap / pred_path.name)
                continue
            records = read_json(pred_path)
            if not isinstance(records, list):
                continue
            new_records, trajectories = [], []
            for rec in records:
                rec = copy.deepcopy(rec)
                it = items.get((cap, str(rec.get("uuid"))))
                if it is None or not it.has_prediction:
                    new_records.append(rec)
                    continue
                traj = it.trajectory_record()
                verdict = step(traj)
                v = verdict.model_dump(mode="json")
                summary.n_tasks += 1
                summary.outcomes[(verdict.b1_path, verdict.outcome)] += 1
                summary.tool_outputs_source[traj.get("tool_outputs_source") or (
                    "trajectory" if traj.get("tool_calls") is not None else "none")] += 1
                if verdict.action == "abstained":
                    _set_last_answer(rec, verdict.answer_returned)
                    changed += 1
                traj["verification"] = v
                trajectories.append(traj)
                new_records.append(rec)
            (out_cap / pred_path.name).write_text(
                json.dumps(new_records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            write_trajectories(trajectories, trajectory_path(out_cap, pred_path.stem))
        summary.n_answers_changed += changed
        src_eval = src / "eval" / f"cap{cap}.json"
        if src_eval.exists() and changed == 0:
            (out / "eval").mkdir(exist_ok=True)
            shutil.copy2(src_eval, out / "eval" / src_eval.name)
            summary.eval_copied.append(cap)
        elif src_eval.exists():
            summary.needs_rescore.append(cap)

    manifest = dict(run.manifest)
    manifest.update(
        {
            "run_id": out.name,
            "agent_variant": "B1",
            "replay_of": {"run_id": run.run_id, "path": str(src),
                          "agent_variant": run.manifest.get("agent_variant")},
            "b1": step.describe(),
            "replay": summary.as_dict(),
        }
    )
    manifest.setdefault("timestamps", {})
    manifest["timestamps"] = {**manifest["timestamps"],
                              "replayed_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    (out / "config.json").write_text(json.dumps(manifest, indent=2, default=str) + "\n",
                                     encoding="utf-8")
    return summary
