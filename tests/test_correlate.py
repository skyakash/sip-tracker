"""Unit tests for the correlation engine's statistical guardrails."""

import numpy as np
import pandas as pd
import pytest

from src.correlate import (
    corr_matrix, corr_with_stats, fisher_ci, lag_table, EXPLORATORY_N,
)


@pytest.fixture
def synthetic():
    rng = np.random.default_rng(42)
    n = 120
    base = rng.normal(0, 1, n)
    return pd.DataFrame({
        "x": base,
        "y": 0.8 * base + 0.6 * rng.normal(0, 1, n),  # rho ~ 0.8
        "z": rng.normal(0, 1, n),
        "level": np.cumsum(rng.normal(0.5, 0.2, n)),  # trending raw level
    })


def test_recovers_known_correlation(synthetic):
    out = corr_matrix(synthetic, ["x", "y", "z"])
    xy = out[(out.series_a == "x") & (out.series_b == "y")].iloc[0]
    assert 0.6 < xy.r < 0.9
    assert xy.ci_low < xy.r < xy.ci_high
    assert not xy.exploratory  # n=120 >= 30


def test_level_guard_trips(synthetic):
    with pytest.raises(ValueError, match="raw level"):
        corr_matrix(synthetic, ["level", "x"])


def test_lag_recovery(synthetic):
    df = pd.DataFrame({"lead": synthetic["x"], "follow": synthetic["x"].shift(2)})
    lt = lag_table(df, "lead", "follow")
    best = lt.loc[lt.r.abs().idxmax()]
    assert best.lag_months == 2
    assert best.r == pytest.approx(1.0)


def test_small_n_marked_exploratory():
    a = pd.Series(np.random.default_rng(1).normal(0, 1, 20))
    b = pd.Series(np.random.default_rng(2).normal(0, 1, 20))
    stats = corr_with_stats(a, b)
    assert stats["n"] == 20 < EXPLORATORY_N
    assert stats["exploratory"]


def test_fisher_ci_sane():
    lo, hi = fisher_ci(0.5, 100)
    assert lo < 0.5 < hi
    assert hi - lo < 0.4  # reasonably tight at n=100
    lo_small, hi_small = fisher_ci(0.5, 10)
    assert hi_small - lo_small > hi - lo  # wider at smaller n
