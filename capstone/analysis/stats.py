"""Small, dependency-free statistics for paired run comparisons."""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class McNemarResult:
    n_pairs: int
    b: int  # A correct, B wrong
    c: int  # A wrong, B correct
    p_exact: float
    chi2_cc: float
    p_chi2_cc: float


def mcnemar(a_correct: Sequence[bool], b_correct: Sequence[bool]) -> McNemarResult:
    """McNemar test on paired binary outcomes.

    Reports the exact two-sided binomial p-value (recommended when b + c < 25)
    and the continuity-corrected chi-square approximation.
    """
    if len(a_correct) != len(b_correct):
        raise ValueError("paired sequences must have equal length")
    b = sum(1 for x, y in zip(a_correct, b_correct) if x and not y)
    c = sum(1 for x, y in zip(a_correct, b_correct) if y and not x)
    n = b + c
    if n == 0:
        return McNemarResult(len(a_correct), b, c, 1.0, 0.0, 1.0)
    k = min(b, c)
    p_exact = min(1.0, 2.0 * sum(math.comb(n, i) for i in range(k + 1)) / 2.0**n)
    chi2 = (abs(b - c) - 1) ** 2 / n
    p_chi2 = math.erfc(math.sqrt(chi2 / 2.0))  # survival function of chi2 with 1 dof
    return McNemarResult(len(a_correct), b, c, p_exact, chi2, p_chi2)


@dataclass(frozen=True)
class BootstrapResult:
    mean_diff: float
    ci_low: float
    ci_high: float
    n_pairs: int
    n_resamples: int
    confidence: float


def paired_bootstrap(
    a: Sequence[float],
    b: Sequence[float],
    *,
    n_resamples: int = 10_000,
    confidence: float = 0.95,
    seed: int = 0,
) -> BootstrapResult:
    """Percentile bootstrap CI for mean(b - a) over paired items."""
    if len(a) != len(b):
        raise ValueError("paired sequences must have equal length")
    diffs = [y - x for x, y in zip(a, b)]
    n = len(diffs)
    if n == 0:
        nan = float("nan")
        return BootstrapResult(nan, nan, nan, 0, n_resamples, confidence)
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(diffs, k=n)) / n for _ in range(n_resamples))
    alpha = (1.0 - confidence) / 2.0
    lo = means[math.floor(alpha * (n_resamples - 1))]
    hi = means[math.ceil((1.0 - alpha) * (n_resamples - 1))]
    return BootstrapResult(sum(diffs) / n, lo, hi, n, n_resamples, confidence)


def wilson_interval(successes: float, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (0..1)."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))
