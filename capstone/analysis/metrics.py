"""Accuracy and cost metrics over loaded runs.

Accuracy is computed over *scored* items (those the evaluator actually
judged), not the evaluator's all-ground-truth denominator, so partial runs
(e.g. N samples per domain) are not diluted by unattempted items. Coverage
columns make the denominator explicit.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from capstone.analysis.loader import CAPABILITY_LABELS, Item, Run
from capstone.analysis.stats import wilson_interval


@dataclass
class AccuracyRow:
    run_id: str
    variant: str
    capability: int | str
    domain: str
    n_items: int  # items known to this run (GT universe seen by the evaluator)
    n_predicted: int
    n_scored: int
    n_excluded: int
    n_correct: int
    mean_score: float
    accuracy: float
    acc_ci_low: float
    acc_ci_high: float
    coverage: float

    @property
    def capability_label(self) -> str:
        return CAPABILITY_LABELS.get(self.capability, str(self.capability))  # type: ignore[arg-type]


def is_correct(item: Item, threshold: float) -> bool:
    return item.score is not None and item.score >= threshold


def _accuracy_row(
    run: Run,
    items: list[Item],
    capability: int | str,
    domain: str,
    threshold: float,
    excluded: set[str],
) -> AccuracyRow:
    scored = [it for it in items if it.scored and it.uuid not in excluded]
    n_excl = sum(1 for it in items if it.scored and it.uuid in excluded)
    n_correct = sum(1 for it in scored if is_correct(it, threshold))
    n = len(scored)
    lo, hi = wilson_interval(n_correct, n)
    return AccuracyRow(
        run_id=run.run_id,
        variant=run.variant,
        capability=capability,
        domain=domain,
        n_items=len(items),
        n_predicted=sum(1 for it in items if it.has_prediction),
        n_scored=n,
        n_excluded=n_excl,
        n_correct=n_correct,
        mean_score=(sum(it.score or 0.0 for it in scored) / n) if n else float("nan"),
        accuracy=(n_correct / n) if n else float("nan"),
        acc_ci_low=lo,
        acc_ci_high=hi,
        coverage=(n / len(items)) if items else float("nan"),
    )


def accuracy_table(
    run: Run, *, by: str, threshold: float = 1.0, excluded: set[str] | None = None
) -> list[AccuracyRow]:
    """``by`` is "capability", "domain" or "overall"."""
    excluded = excluded or set()
    groups: dict[tuple, list[Item]] = defaultdict(list)
    for it in run.items:
        if by == "capability":
            groups[(it.capability, "*")].append(it)
        elif by == "domain":
            groups[(it.capability, it.domain)].append(it)
        elif by == "overall":
            groups[("all", "*")].append(it)
        else:
            raise ValueError(by)
    return [
        _accuracy_row(run, items, cap, dom, threshold, excluded)
        for (cap, dom), items in sorted(
            groups.items(), key=lambda kv: (str(kv[0][0]), kv[0][1])
        )
    ]


@dataclass
class CostRow:
    run_id: str
    capability: int | str
    n: int
    latency_mean_s: float
    latency_p50_s: float
    latency_p90_s: float
    latency_max_s: float
    n_with_tokens: int
    prompt_tokens_mean: float
    completion_tokens_mean: float
    total_tokens_mean: float
    total_tokens_sum: int
    llm_calls_mean: float
    tool_calls_mean: float
    est_cost_usd: float | None


def _pct(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    values = sorted(values)
    idx = q * (len(values) - 1)
    lo, hi = int(idx), min(int(idx) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (idx - lo)


def _mean(values: Iterable[float]) -> float:
    values = list(values)
    return statistics.fmean(values) if values else float("nan")


def cost_table(
    run: Run,
    *,
    price_in_per_m: float | None = None,
    price_out_per_m: float | None = None,
) -> list[CostRow]:
    """Latency (from predictions) and tokens (from tracing spans, if present)."""
    groups: dict[int | str, list[Item]] = defaultdict(list)
    for it in run.items:
        if it.has_prediction:
            groups[it.capability].append(it)
            groups["all"].append(it)
    rows = []
    for cap, items in sorted(groups.items(), key=lambda kv: str(kv[0])):
        lat = [float(it.duration_s) for it in items if it.duration_s is not None]
        tok = [it for it in items if it.total_tokens is not None]
        cost = None
        if tok and price_in_per_m is not None and price_out_per_m is not None:
            cost = sum(
                (it.prompt_tokens or 0) * price_in_per_m / 1e6
                + (it.completion_tokens or 0) * price_out_per_m / 1e6
                for it in tok
            )
        rows.append(
            CostRow(
                run_id=run.run_id,
                capability=cap,
                n=len(items),
                latency_mean_s=_mean(lat),
                latency_p50_s=_pct(lat, 0.5),
                latency_p90_s=_pct(lat, 0.9),
                latency_max_s=max(lat) if lat else float("nan"),
                n_with_tokens=len(tok),
                prompt_tokens_mean=_mean(it.prompt_tokens or 0 for it in tok),
                completion_tokens_mean=_mean(it.completion_tokens or 0 for it in tok),
                total_tokens_mean=_mean(it.total_tokens or 0 for it in tok),
                total_tokens_sum=sum(it.total_tokens or 0 for it in tok),
                llm_calls_mean=_mean(it.n_llm_calls or 0 for it in tok),
                tool_calls_mean=_mean(len(it.pred_calls) for it in items),
                est_cost_usd=cost,
            )
        )
    return rows


def filter_items(run: Run, predicate: Callable[[Item], bool]) -> list[Item]:
    return [it for it in run.items if predicate(it)]
