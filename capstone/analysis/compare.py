"""Paired comparison of two runs on the items both of them scored."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from capstone.analysis.loader import Item, Run
from capstone.analysis.metrics import is_correct
from capstone.analysis.stats import (
    BootstrapResult,
    McNemarResult,
    mcnemar,
    paired_bootstrap,
)


@dataclass
class ComparisonRow:
    run_a: str
    run_b: str
    capability: int | str
    n_pairs: int
    acc_a: float
    acc_b: float
    mean_score_a: float
    mean_score_b: float
    mcnemar: McNemarResult
    bootstrap: BootstrapResult


def paired_items(
    a: Run, b: Run, excluded: set[str] | None = None
) -> list[tuple[Item, Item]]:
    excluded = excluded or set()
    b_items = b.by_key()
    pairs = []
    for it in a.items:
        other = b_items.get(it.key)
        if other and it.scored and other.scored and it.uuid not in excluded:
            pairs.append((it, other))
    return pairs


def compare_runs(
    a: Run,
    b: Run,
    *,
    threshold: float = 1.0,
    excluded: set[str] | None = None,
    n_resamples: int = 10_000,
    seed: int = 0,
) -> tuple[list[ComparisonRow], list[tuple[Item, Item]]]:
    """Per-capability and overall rows; difference is B minus A."""
    pairs = paired_items(a, b, excluded)
    groups: dict[int | str, list[tuple[Item, Item]]] = defaultdict(list)
    for pa, pb in pairs:
        groups[pa.capability].append((pa, pb))
        groups["all"].append((pa, pb))
    rows = []
    for cap, grp in sorted(groups.items(), key=lambda kv: str(kv[0])):
        ca = [is_correct(x, threshold) for x, _ in grp]
        cb = [is_correct(y, threshold) for _, y in grp]
        sa = [x.score or 0.0 for x, _ in grp]
        sb = [y.score or 0.0 for _, y in grp]
        n = len(grp)
        rows.append(
            ComparisonRow(
                run_a=a.run_id,
                run_b=b.run_id,
                capability=cap,
                n_pairs=n,
                acc_a=sum(ca) / n,
                acc_b=sum(cb) / n,
                mean_score_a=sum(sa) / n,
                mean_score_b=sum(sb) / n,
                mcnemar=mcnemar(ca, cb),
                bootstrap=paired_bootstrap(sa, sb, n_resamples=n_resamples, seed=seed),
            )
        )
    return rows, pairs
