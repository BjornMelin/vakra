"""Offline B1 commands: ``python -m capstone.b1 <command> ...``.

Commands:
  collect SRC OUT        re-execute a past run's tool calls on MCP (no LLM) and
                         write trajectory sidecars with the tool outputs
  replay SRC OUT         run the B1 check over a finished run, writing a new
                         B1 run dir (the source run is never modified)
  eval RUN               B1 verdict vs gold 2x2 per path (WS2.3), with latency
  gold-check             false alarms on gold answers + seeded-error detection
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from capstone.b1.config import VerifierConfig

log = logging.getLogger("capstone.b1")


def _caps(text: str | None) -> set[int] | None:
    return {int(c) for c in text.split(",") if c.strip()} if text else None


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    cols: list[str] = []
    for r in rows:
        cols += [k for k in r if k not in cols]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m capstone.b1", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    c = sub.add_parser("collect", help="re-execute a run's tool calls to recover tool outputs")
    c.add_argument("src", type=Path)
    c.add_argument("out", type=Path, help="sidecar dir (cap<C>/<domain>_trajectory.json)")
    c.add_argument("--mcp-config", type=Path, default=Path("benchmark/mcp_connection_config.yaml"))
    c.add_argument("--caps", default=None, help="comma list, e.g. 1,2")

    r = sub.add_parser("replay", help="apply B1 to a finished run -> new run dir")
    r.add_argument("src", type=Path)
    r.add_argument("out", type=Path)
    r.add_argument("--verifier-config", type=Path, default=None)
    r.add_argument("--tool-outputs", type=Path, default=None, help="dir written by collect")
    r.add_argument("--caps", default=None)
    r.add_argument("--no-judge", action="store_true",
                   help="deterministic path only (judge-bound answers become insufficient_evidence)")

    e = sub.add_parser("eval", help="B1 verdicts vs gold (2x2 per path)")
    e.add_argument("run", type=Path)
    e.add_argument("--gt-root", type=Path, default=Path("data/train"))
    e.add_argument("--exclude-uuids", type=Path, default=None)
    e.add_argument("--out", type=Path, default=None, help="default: RUN/b1_eval")

    g = sub.add_parser("gold-check", help="false alarms on gold + seeded-error detection")
    g.add_argument("--gt-root", type=Path, default=Path("data/train"))
    g.add_argument("--caps", default="1,2,3,4")
    g.add_argument("--verifier-config", type=Path, default=None)
    g.add_argument("--with-judge", action="store_true", help="call the configured judge (default: off)")
    g.add_argument("--max-file-mb", type=float, default=200.0,
                   help="skip gold files larger than this (parsed whole); 0 = no limit")
    g.add_argument("--max-answer-chars", type=int, default=100_000,
                   help="skip gold cases whose answer is longer than this; 0 = no limit")
    g.add_argument("--out", type=Path, required=True)
    return parser


def _step(args: argparse.Namespace):
    from capstone.b1.judge import build_judge
    from capstone.b1.step import B1Step

    cfg = VerifierConfig.load(args.verifier_config)
    judge = None if getattr(args, "no_judge", False) else build_judge(cfg.judge)
    return B1Step(cfg, judge)


def cmd_collect(args: argparse.Namespace) -> int:
    from capstone.b1.collect import collect_run

    counts = asyncio.run(collect_run(args.src, args.out, mcp_config=args.mcp_config, caps=_caps(args.caps)))
    print(json.dumps(counts, indent=2))
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    from capstone.b1.replay import replay_run

    summary = replay_run(args.src, args.out, _step(args),
                         tool_outputs_dir=args.tool_outputs, caps=_caps(args.caps))
    print(json.dumps(summary.as_dict(), indent=2))
    if summary.needs_rescore:
        print(f"answers changed in caps {summary.needs_rescore}: re-run the evaluator on {args.out}")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    from capstone.analysis.loader import load_run, read_uuid_list
    from capstone.b1.verifier_eval import evaluate_verdicts, markdown

    run = load_run(args.run, gt_root=args.gt_root if args.gt_root.exists() else None)
    ev = evaluate_verdicts(run, excluded=read_uuid_list(args.exclude_uuids))
    out = args.out or Path(args.run) / "b1_eval"
    out.mkdir(parents=True, exist_ok=True)
    (out / "b1_eval.json").write_text(json.dumps(asdict(ev), indent=2) + "\n", encoding="utf-8")
    (out / "b1_eval.md").write_text(markdown(ev), encoding="utf-8")
    _write_rows(out / "b1_eval_cells.csv", ev.cells)
    _write_rows(out / "b1_eval_by_label.csv", ev.catch_by_headline)
    print(markdown(ev))
    return 0


def cmd_gold_check(args: argparse.Namespace) -> int:
    from capstone.b1.judge import build_judge
    from capstone.b1.seeded import gold_check

    cfg = VerifierConfig.load(args.verifier_config)
    judge = build_judge(cfg.judge) if args.with_judge else None
    limit = int(args.max_file_mb * 1e6) if args.max_file_mb > 0 else None
    rep = gold_check(args.gt_root, cfg, judge, caps=sorted(_caps(args.caps) or ()), max_file_bytes=limit,
                     max_answer_chars=args.max_answer_chars or None)
    args.out.mkdir(parents=True, exist_ok=True)
    rows = rep.rows()
    payload = {"config_sha256": cfg.sha256(), "judge": bool(judge), "rows": rows,
               "skipped_files": rep.skipped_files, "skipped_cases": rep.skipped_cases,
               "false_alarms": rep.false_alarms,
               "misses": rep.misses}
    (args.out / "gold_check.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    _write_rows(args.out / "gold_check.csv", rows)
    for row in rows:
        print(row)
    if rep.skipped_files:
        print("skipped (too large):", ", ".join(rep.skipped_files))
    for c in rep.skipped_cases:
        print(f"skipped case (answer {c['answer_chars']} chars): cap{c['cap']}/{c['domain']} {c['uuid']}")
    return 0


COMMANDS = {"collect": cmd_collect, "replay": cmd_replay, "eval": cmd_eval, "gold-check": cmd_gold_check}


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    return COMMANDS[args.command](args)
