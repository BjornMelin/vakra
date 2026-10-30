"""CSV, Markdown and PNG writers. matplotlib is imported lazily (plots only)."""

from __future__ import annotations

import csv
import logging
import math
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from capstone.analysis.compare import ComparisonRow
from capstone.analysis.labels import SUBREASONS, Label
from capstone.analysis.loader import CAPABILITY_LABELS
from capstone.analysis.metrics import AccuracyRow, CostRow

logger = logging.getLogger(__name__)


def _fmt(v: Any, digits: int = 3) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return "" if math.isnan(v) else f"{v:.{digits}f}"
    return str(v)


def write_csv(
    path: Path, rows: Sequence[Any], fields: Sequence[str] | None = None
) -> Path:
    dict_rows = [asdict(r) if is_dataclass(r) else dict(r) for r in rows]
    fields = list(fields or (dict_rows[0].keys() if dict_rows else []))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(dict_rows)
    return path


def md_table(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(_fmt(c) for c in row) + " |" for row in rows]
    return "\n".join(out)


def cap_name(cap: int | str) -> str:
    return f"{cap} · {CAPABILITY_LABELS[cap]}" if cap in CAPABILITY_LABELS else str(cap)


def accuracy_md(rows: Sequence[AccuracyRow], with_domain: bool = False) -> str:
    headers = ["run", "variant", "capability"] + (["domain"] if with_domain else [])
    headers += [
        "scored/items",
        "excluded",
        "correct",
        "accuracy",
        "95% CI",
        "mean score",
        "coverage",
    ]
    body = []
    for r in rows:
        row = [r.run_id, r.variant, cap_name(r.capability)] + (
            [r.domain] if with_domain else []
        )
        row += [
            f"{r.n_scored}/{r.n_items}",
            r.n_excluded,
            r.n_correct,
            r.accuracy,
            f"[{_fmt(r.acc_ci_low, 2)}, {_fmt(r.acc_ci_high, 2)}]",
            r.mean_score,
            r.coverage,
        ]
        body.append(row)
    return md_table(headers, body)


def cost_md(rows: Sequence[CostRow]) -> str:
    headers = [
        "run",
        "capability",
        "n",
        "latency mean s",
        "p50",
        "p90",
        "max",
        "tokens/item",
        "LLM calls/item",
        "tool calls/item",
        "est. cost $",
    ]
    body = [
        [
            r.run_id,
            cap_name(r.capability),
            r.n,
            r.latency_mean_s,
            r.latency_p50_s,
            r.latency_p90_s,
            r.latency_max_s,
            r.total_tokens_mean if r.n_with_tokens else None,
            r.llm_calls_mean if r.n_with_tokens else None,
            r.tool_calls_mean,
            r.est_cost_usd,
        ]
        for r in rows
    ]
    return md_table(headers, body)


def error_summary_rows(run_id: str, labels: Iterable[Label]) -> list[dict[str, Any]]:
    counts = Counter(
        (lab.headline or "unlabeled", lab.subreason or "unlabeled") for lab in labels
    )
    total = sum(counts.values())
    order = [(h, s) for h, subs in SUBREASONS.items() for s in subs] + [
        ("unlabeled", "unlabeled")
    ]
    return [
        {
            "run_id": run_id,
            "headline": h,
            "subreason": s,
            "n": counts[(h, s)],
            "share": counts[(h, s)] / total,
        }
        for h, s in order
        if counts.get((h, s))
    ]


def comparison_md(rows: Sequence[ComparisonRow]) -> str:
    headers = [
        "capability",
        "pairs",
        "acc A",
        "acc B",
        "B-A mean score",
        "95% bootstrap CI",
        "A only ✓ (b)",
        "B only ✓ (c)",
        "McNemar exact p",
    ]
    body = [
        [
            cap_name(r.capability),
            r.n_pairs,
            r.acc_a,
            r.acc_b,
            r.bootstrap.mean_diff,
            f"[{_fmt(r.bootstrap.ci_low)}, {_fmt(r.bootstrap.ci_high)}]",
            r.mcnemar.b,
            r.mcnemar.c,
            r.mcnemar.p_exact,
        ]
        for r in rows
    ]
    return md_table(headers, body)


def comparison_flat(rows: Sequence[ComparisonRow]) -> list[dict[str, Any]]:
    return [
        {
            "run_a": r.run_a,
            "run_b": r.run_b,
            "capability": r.capability,
            "n_pairs": r.n_pairs,
            "acc_a": r.acc_a,
            "acc_b": r.acc_b,
            "mean_score_a": r.mean_score_a,
            "mean_score_b": r.mean_score_b,
            "diff_mean": r.bootstrap.mean_diff,
            "diff_ci_low": r.bootstrap.ci_low,
            "diff_ci_high": r.bootstrap.ci_high,
            "bootstrap_resamples": r.bootstrap.n_resamples,
            "mcnemar_b_a_only": r.mcnemar.b,
            "mcnemar_c_b_only": r.mcnemar.c,
            "mcnemar_p_exact": r.mcnemar.p_exact,
            "mcnemar_chi2_cc": r.mcnemar.chi2_cc,
            "mcnemar_p_chi2_cc": r.mcnemar.p_chi2_cc,
        }
        for r in rows
    ]


# ----------------------------------------------------------------- plots ----


def _pyplot():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        logger.warning("matplotlib not installed; skipping PNG plots")
        return None
    return plt


def plot_accuracy(path: Path, rows: Sequence[AccuracyRow]) -> Path | None:
    plt = _pyplot()
    if plt is None or not rows:
        return None
    runs = list(dict.fromkeys(r.run_id for r in rows))
    caps = list(dict.fromkeys(r.capability for r in rows))
    width = 0.8 / len(runs)
    fig, ax = plt.subplots(figsize=(1.8 + 1.6 * len(caps), 3.6))
    for i, run in enumerate(runs):
        sub = {r.capability: r for r in rows if r.run_id == run}
        xs, ys, err = [], [], [[], []]
        for j, cap in enumerate(caps):
            r = sub.get(cap)
            if r is None or math.isnan(r.accuracy):
                continue
            xs.append(j + (i - (len(runs) - 1) / 2) * width)
            ys.append(r.accuracy)
            err[0].append(r.accuracy - r.acc_ci_low)
            err[1].append(r.acc_ci_high - r.accuracy)
        variant = next((r.variant for r in rows if r.run_id == run), "?")
        ax.bar(xs, ys, width, yerr=err, capsize=3, label=f"{run} ({variant})")
    ax.set_xticks(
        range(len(caps)), [cap_name(c).replace(" · ", "\n") for c in caps], fontsize=8
    )
    ax.set_ylim(0, 1)
    ax.set_ylabel("accuracy (scored items, Wilson 95% CI)")
    ax.legend(fontsize=8, frameon=False, loc="lower right")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def plot_errors(path: Path, summary: Sequence[dict[str, Any]]) -> Path | None:
    plt = _pyplot()
    if plt is None or not summary:
        return None
    labels = [f"{r['headline']}\n{r['subreason']}" for r in summary]
    fig, ax = plt.subplots(figsize=(6.4, 0.45 * len(summary) + 1.2))
    colors = [
        "#c0504d" if r["headline"] == "not_supported" else "#4f81bd" for r in summary
    ]
    ax.barh(labels[::-1], [r["n"] for r in summary][::-1], color=colors[::-1])
    ax.set_xlabel("wrong answers")
    ax.tick_params(axis="y", labelsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def plot_latency(path: Path, latencies: dict[str, list[float]]) -> Path | None:
    plt = _pyplot()
    data = {k: v for k, v in latencies.items() if v}
    if plt is None or not data:
        return None
    fig, ax = plt.subplots(figsize=(1.5 + 1.2 * len(data), 3.4))
    ax.boxplot(list(data.values()), showfliers=True)
    ax.set_xticks(range(1, len(data) + 1), list(data.keys()), fontsize=8)
    ax.set_ylabel("seconds per item")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def plot_comparison(path: Path, rows: Sequence[ComparisonRow]) -> Path | None:
    plt = _pyplot()
    if plt is None or not rows:
        return None
    caps = [cap_name(r.capability).replace(" · ", "\n") for r in rows]
    diffs = [r.bootstrap.mean_diff for r in rows]
    err = [
        [r.bootstrap.mean_diff - r.bootstrap.ci_low for r in rows],
        [r.bootstrap.ci_high - r.bootstrap.mean_diff for r in rows],
    ]
    fig, ax = plt.subplots(figsize=(1.8 + 1.4 * len(rows), 3.4))
    ax.bar(range(len(rows)), diffs, yerr=err, capsize=4, color="#4f81bd")
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks(range(len(rows)), caps, fontsize=8)
    ax.set_ylabel(f"{rows[0].run_b} − {rows[0].run_a}\nmean score (95% bootstrap CI)")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path
