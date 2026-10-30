"""Command line entry point: ``python -m capstone.analysis <command> ...``.

Commands:
  summarize RUN [RUN ...]   accuracy / latency / tokens / error labels (+ CSV, MD, PNG)
  compare RUN_A RUN_B       paired comparison: McNemar + bootstrap CI (B minus A)
  trace RUN                 one compact example trace (Markdown) for slides
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from capstone.analysis import report
from capstone.analysis.compare import compare_runs
from capstone.analysis.labels import (
    LABEL_FIELDS,
    Label,
    auto_label,
    label_rows,
    read_human_labels,
)
from capstone.analysis.loader import Item, Run, load_run, read_uuid_list
from capstone.analysis.metrics import accuracy_table, cost_table, is_correct
from capstone.analysis.traces import render_trace

log = logging.getLogger("capstone.analysis")


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--out", type=Path, default=Path("analysis_out"), help="output directory"
    )
    p.add_argument(
        "--gt-root",
        type=Path,
        default=Path("data/train"),
        help="VAKRA ground-truth root (contains capability_*/output); enables tool-path heuristics",
    )
    p.add_argument(
        "--exclude-uuids",
        type=Path,
        default=None,
        help="file of known reference-wrong uuids (one per line, '#' comments); excluded from accuracy",
    )
    p.add_argument(
        "--threshold",
        type=float,
        default=1.0,
        help="score >= threshold counts as correct (default 1.0)",
    )
    p.add_argument("--no-plots", action="store_true", help="skip PNG output")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m capstone.analysis",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    s = sub.add_parser("summarize", help="per-run accuracy, cost and error labels")
    s.add_argument("runs", nargs="+", type=Path)
    s.add_argument(
        "--labels",
        type=Path,
        default=None,
        help="filled labeling CSV; human labels override auto",
    )
    s.add_argument(
        "--price-in",
        type=float,
        default=None,
        help="USD per 1M prompt tokens (for cost estimate)",
    )
    s.add_argument(
        "--price-out", type=float, default=None, help="USD per 1M completion tokens"
    )
    _common(s)

    c = sub.add_parser("compare", help="paired comparison of two runs (B minus A)")
    c.add_argument("run_a", type=Path)
    c.add_argument("run_b", type=Path)
    c.add_argument("--resamples", type=int, default=10_000)
    c.add_argument("--seed", type=int, default=0)
    _common(c)

    t = sub.add_parser("trace", help="export one compact example trace as Markdown")
    t.add_argument("run", type=Path)
    t.add_argument(
        "--uuid",
        default=None,
        help="item uuid (default: pick a representative wrong answer)",
    )
    t.add_argument("--capability", type=int, default=None)
    t.add_argument("--labels", type=Path, default=None)
    _common(t)
    return parser


def _gt_root(path: Path) -> Path | None:
    if path.is_dir():
        return path
    log.warning("ground-truth root %s not found; tool-path heuristics disabled", path)
    return None


def _labels_for(
    run: Run, items: list[Item], reference_wrong: set[str], human: dict
) -> dict:
    labels: dict[tuple[int, str], Label] = {}
    for it in items:
        labels[it.key] = human.get(it.key) or auto_label(
            it, reference_wrong=reference_wrong
        )
    return labels


def _wrong_items(run: Run, threshold: float) -> list[Item]:
    return [it for it in run.items if it.scored and not is_correct(it, threshold)]


def cmd_summarize(args: argparse.Namespace) -> int:
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    excluded = read_uuid_list(args.exclude_uuids)
    human = read_human_labels(args.labels) if args.labels else {}
    gt_root = _gt_root(args.gt_root)
    runs = [load_run(p, gt_root) for p in args.runs]

    by_cap, by_dom, overall, costs, label_csv, err_summary = [], [], [], [], [], []
    latencies: dict[str, list[float]] = {}
    md = ["# VAKRA run summary", ""]
    for run in runs:
        by_cap += accuracy_table(
            run, by="capability", threshold=args.threshold, excluded=excluded
        )
        by_dom += accuracy_table(
            run, by="domain", threshold=args.threshold, excluded=excluded
        )
        overall += accuracy_table(
            run, by="overall", threshold=args.threshold, excluded=excluded
        )
        costs += cost_table(
            run, price_in_per_m=args.price_in, price_out_per_m=args.price_out
        )
        wrong = _wrong_items(run, args.threshold)
        labels = _labels_for(run, wrong, excluded, human)
        label_csv += label_rows(wrong, labels)
        err_summary += report.error_summary_rows(run.run_id, labels.values())
        latencies[run.run_id] = [
            float(it.duration_s) for it in run.items if it.duration_s is not None
        ]
        m = run.manifest
        md += [
            f"## {run.run_id}",
            "",
            (
                f"- variant: {run.variant} · model: {m.get('model', '?')} · commit: {m.get('git', {}).get('sha', '?')}"
                f" · N/domain: {m.get('max_samples_per_domain', '?')} · spans: {'yes' if run.has_spans else 'no'}"
            ),
            "",
        ]

    write = report.write_csv
    write(out / "accuracy_by_capability.csv", by_cap + overall)
    write(out / "accuracy_by_domain.csv", by_dom)
    write(out / "cost_latency.csv", costs)
    write(out / "error_labels.csv", label_csv, LABEL_FIELDS)
    write(
        out / "error_summary.csv",
        err_summary,
        ["run_id", "headline", "subreason", "n", "share"],
    )

    md += [
        "## Accuracy by capability (scored items only)",
        "",
        f"Correct = score ≥ {args.threshold}. Excluded reference-wrong uuids: {len(excluded)}.",
        "",
        report.accuracy_md(by_cap + overall),
        "",
        "## Latency and tokens",
        "",
        report.cost_md(costs),
        "",
        "Tokens come from tracing spans (`$RUN/traces`); blank when the run was not traced.",
        "",
        "## Error labels (auto first pass; human labels override)",
        "",
        report.md_table(
            ["run", "headline", "sub-reason", "n", "share"],
            [
                [r["run_id"], r["headline"], r["subreason"], r["n"], r["share"]]
                for r in err_summary
            ],
        ),
        "",
        (
            "Label the rows in `error_labels.csv` (human_headline / human_subreason / human_notes), then re-run "
            "with `--labels error_labels.csv`."
        ),
        "",
        "## Accuracy by domain",
        "",
        report.accuracy_md(by_dom, with_domain=True),
        "",
    ]
    if not args.no_plots:
        report.plot_accuracy(out / "accuracy_by_capability.png", by_cap)
        report.plot_errors(out / "error_breakdown.png", err_summary)
        report.plot_latency(out / "latency.png", latencies)
        md[2:2] = [
            "![accuracy](accuracy_by_capability.png)",
            "",
            "![errors](error_breakdown.png)",
            "",
        ]
    (out / "report.md").write_text("\n".join(md), encoding="utf-8")
    print(report.accuracy_md(by_cap + overall))
    print(f"\nWrote {out}/report.md and CSV/PNG files.")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    excluded = read_uuid_list(args.exclude_uuids)
    gt_root = _gt_root(args.gt_root)
    a, b = load_run(args.run_a, gt_root), load_run(args.run_b, gt_root)
    rows, pairs = compare_runs(
        a,
        b,
        threshold=args.threshold,
        excluded=excluded,
        n_resamples=args.resamples,
        seed=args.seed,
    )
    if not rows:
        log.error("no items scored by both runs; nothing to compare")
        return 1
    report.write_csv(out / "comparison.csv", report.comparison_flat(rows))
    report.write_csv(
        out / "paired_items.csv",
        [
            {
                "capability": x.capability,
                "domain": x.domain,
                "uuid": x.uuid,
                "score_a": x.score,
                "score_b": y.score,
                "correct_a": is_correct(x, args.threshold),
                "correct_b": is_correct(y, args.threshold),
            }
            for x, y in pairs
        ],
    )
    md = [
        f"# Paired comparison: {b.run_id} (B) vs {a.run_id} (A)",
        "",
        (
            f"Items scored in both runs; {len(excluded)} reference-wrong uuids excluded. Correct = score ≥ "
            f"{args.threshold}. Difference is B − A in mean score; CI is a percentile bootstrap over paired "
            f"items ({args.resamples} resamples, seed {args.seed}). McNemar uses the exact binomial test on "
            "discordant pairs (b = only A correct, c = only B correct)."
        ),
        "",
        report.comparison_md(rows),
        "",
    ]
    if not args.no_plots and report.plot_comparison(out / "comparison.png", rows):
        md.insert(2, "![comparison](comparison.png)\n")
    (out / "comparison.md").write_text("\n".join(md), encoding="utf-8")
    print(report.comparison_md(rows))
    print(f"\nWrote {out}/comparison.md and CSV/PNG files.")
    return 0


def _pick_example(run: Run, threshold: float, capability: int | None) -> Item | None:
    pool = [
        it for it in _wrong_items(run, threshold) if capability in (None, it.capability)
    ]
    pool = [it for it in pool if it.pred_calls or it.tool_spans] or pool
    # Short, traced examples fit on a slide best.
    return min(
        pool,
        key=lambda it: (not it.tool_spans, abs(len(it.pred_calls) - 3), it.uuid),
        default=None,
    )


def cmd_trace(args: argparse.Namespace) -> int:
    run = load_run(args.run, _gt_root(args.gt_root))
    if args.uuid:
        matches = [
            it
            for it in run.items
            if it.uuid == args.uuid and args.capability in (None, it.capability)
        ]
        item = matches[0] if matches else None
    else:
        item = _pick_example(run, args.threshold, args.capability)
    if item is None:
        log.error("no matching item found")
        return 1
    label = None
    if item.scored and not is_correct(item, args.threshold):
        human = read_human_labels(args.labels) if args.labels else {}
        label = human.get(item.key) or auto_label(
            item, reference_wrong=read_uuid_list(args.exclude_uuids)
        )
    text = render_trace(item, label)
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"example_trace_cap{item.capability}_{item.uuid}.md"
    path.write_text(text, encoding="utf-8")
    print(text)
    print(f"Wrote {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    return {"summarize": cmd_summarize, "compare": cmd_compare, "trace": cmd_trace}[
        args.command
    ](args)
