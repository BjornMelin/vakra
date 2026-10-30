import math

import pytest

from capstone.analysis.stats import mcnemar, paired_bootstrap, wilson_interval


def test_mcnemar_exact_matches_binomial():
    # b=1 (A only), c=6 (B only): two-sided exact p = 2 * P(X<=1 | n=7, 0.5) = 16/128
    a = [True] * 1 + [False] * 6 + [True] * 5
    b = [False] * 1 + [True] * 6 + [True] * 5
    r = mcnemar(a, b)
    assert (r.b, r.c, r.n_pairs) == (1, 6, 12)
    assert r.p_exact == pytest.approx(0.125)
    assert r.chi2_cc == pytest.approx((5 - 1) ** 2 / 7)
    assert r.p_chi2_cc == pytest.approx(math.erfc(math.sqrt(r.chi2_cc / 2)))


def test_mcnemar_no_discordant_pairs():
    r = mcnemar([True, False], [True, False])
    assert r.p_exact == 1.0 and r.b == r.c == 0


def test_mcnemar_length_mismatch():
    with pytest.raises(ValueError):
        mcnemar([True], [True, False])


def test_paired_bootstrap_is_seeded_and_brackets_mean():
    a = [0, 0, 1, 0, 1, 0, 0, 1]
    b = [1, 0, 1, 1, 1, 0, 1, 1]
    r1 = paired_bootstrap(a, b, n_resamples=2000, seed=7)
    r2 = paired_bootstrap(a, b, n_resamples=2000, seed=7)
    assert r1 == r2
    assert r1.mean_diff == pytest.approx(3 / 8)
    assert r1.ci_low <= r1.mean_diff <= r1.ci_high
    assert 0 <= r1.ci_low and r1.ci_high <= 1


def test_paired_bootstrap_constant_difference():
    r = paired_bootstrap([0.0] * 5, [1.0] * 5, n_resamples=100)
    assert (r.ci_low, r.ci_high) == (1.0, 1.0)


def test_wilson_interval():
    lo, hi = wilson_interval(5, 10)
    assert lo == pytest.approx(0.2366, abs=1e-3) and hi == pytest.approx(
        0.7634, abs=1e-3
    )
    assert all(math.isnan(x) for x in wilson_interval(0, 0))
