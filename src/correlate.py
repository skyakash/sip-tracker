"""
Change-space correlation engine with statistical guardrails.

Ground rules (from the analysis plan, non-negotiable):

1. Correlations are computed on CHANGES (MoM %) or z-scores, never raw
   levels. Every Indian macro series trends upward; correlating levels
   produces ~0.9 for any pair and means nothing. `corr_matrix` hard-fails
   if handed a series it judges to be a raw level (monotone-ish trending).
2. Every reported correlation carries its N and a 95% CI via the Fisher
   z-transform. N < EXPLORATORY_N is labelled exploratory.
3. Lag analysis is capped at +/-3 months -- with the series lengths in
   this project, deeper lag mining is degrees-of-freedom theatre.
"""

import numpy as np
import pandas as pd

EXPLORATORY_N = 30
MAX_LAG = 3


def pct_change_series(series: pd.Series) -> pd.Series:
    """Row-order MoM % change. Callers must pass a calendar-complete,
    month-sorted series (all builders in this repo emit those)."""
    return series.pct_change() * 100


def zscore_series(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    return (s - s.mean()) / s.std()


def _looks_like_level(series: pd.Series) -> bool:
    """Heuristic guard: a raw macro level trends -- the fraction of
    same-sign consecutive moves is high and the series drifts far from its
    starting value. Change-space series hover around zero."""
    s = pd.to_numeric(series, errors="coerce").dropna()
    if len(s) < 12:
        return False
    diffs = np.sign(s.diff().dropna())
    same_sign_frac = max((diffs > 0).mean(), (diffs < 0).mean())
    drift = abs(s.iloc[-1] - s.iloc[0]) / (s.abs().mean() + 1e-9)
    return same_sign_frac > 0.75 and drift > 1.0


def fisher_ci(r: float, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """95% CI for a Pearson r via the Fisher z-transform."""
    if n < 4 or abs(r) >= 1.0:
        return (float("nan"), float("nan"))
    z = np.arctanh(r)
    se = 1.0 / np.sqrt(n - 3)
    crit = 1.959964  # 97.5th percentile of the standard normal
    lo, hi = z - crit * se, z + crit * se
    return (float(np.tanh(lo)), float(np.tanh(hi)))


def corr_with_stats(a: pd.Series, b: pd.Series) -> dict:
    """Pearson r between two already-change-space series, with N, CI and an
    exploratory flag. NaNs pairwise-dropped."""
    df = pd.DataFrame({"a": pd.to_numeric(a, errors="coerce"),
                       "b": pd.to_numeric(b, errors="coerce")}).dropna()
    n = len(df)
    if n < 4:
        return {"r": float("nan"), "n": n, "ci_low": float("nan"),
                "ci_high": float("nan"), "exploratory": True}
    r = float(df["a"].corr(df["b"]))
    lo, hi = fisher_ci(r, n)
    return {"r": r, "n": n, "ci_low": lo, "ci_high": hi,
            "exploratory": n < EXPLORATORY_N}


def corr_matrix(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Pairwise correlation stats across change-space columns. Raises if a
    column looks like a raw level series -- convert with pct_change_series
    or zscore_series first."""
    for col in columns:
        if _looks_like_level(df[col]):
            raise ValueError(
                f"'{col}' looks like a raw level series (trending). Correlate "
                "changes, not levels: use pct_change_series()/zscore_series()."
            )
    rows = []
    for i, a in enumerate(columns):
        for b in columns[i + 1:]:
            stats = corr_with_stats(df[a], df[b])
            rows.append({"series_a": a, "series_b": b, **stats})
    return pd.DataFrame(rows)


def lag_table(df: pd.DataFrame, lead_col: str, follow_col: str,
              max_lag: int = MAX_LAG) -> pd.DataFrame:
    """Cross-correlation of lead_col at lag k vs follow_col, k in
    [-max_lag, +max_lag]. Positive k: lead_col shifted k months into the
    past (i.e. lead_col leads follow_col by k months). Both columns must
    already be change-space."""
    for col in (lead_col, follow_col):
        if _looks_like_level(df[col]):
            raise ValueError(f"'{col}' looks like a raw level series -- convert first.")
    rows = []
    for k in range(-max_lag, max_lag + 1):
        stats = corr_with_stats(df[lead_col].shift(k), df[follow_col])
        rows.append({"lag_months": k, **stats})
    return pd.DataFrame(rows)


def rolling_corr(df: pd.DataFrame, col_a: str, col_b: str,
                 window: int = 12) -> pd.Series:
    """Rolling Pearson r between two change-space columns."""
    a = pd.to_numeric(df[col_a], errors="coerce")
    b = pd.to_numeric(df[col_b], errors="coerce")
    return a.rolling(window, min_periods=window).corr(b)


if __name__ == "__main__":
    # Self-test with synthetic series of known relationships.
    rng = np.random.default_rng(42)
    n = 120
    base = rng.normal(0, 1, n)
    correlated = 0.8 * base + 0.6 * rng.normal(0, 1, n)  # rho ~ 0.8
    noise = rng.normal(0, 1, n)
    level = pd.Series(np.cumsum(rng.normal(0.5, 0.2, n)))  # trending level

    df = pd.DataFrame({"x": base, "y": correlated, "z": noise})
    out = corr_matrix(df, ["x", "y", "z"])
    print(out.to_string())
    xy = out[(out.series_a == "x") & (out.series_b == "y")].iloc[0]
    assert 0.6 < xy.r < 0.9, f"expected r~0.8, got {xy.r}"
    assert xy.ci_low < xy.r < xy.ci_high

    lagged = pd.DataFrame({"lead": pd.Series(base), "follow": pd.Series(base).shift(2)})
    lt = lag_table(lagged, "lead", "follow")
    best = lt.loc[lt.r.abs().idxmax()]
    assert best.lag_months == 2, f"expected lag 2, got {best.lag_months}"
    print(f"\nlag recovery OK (best lag = {best.lag_months}, r = {best.r:.2f})")

    try:
        corr_matrix(pd.DataFrame({"lvl": level, "x": pd.Series(base)}), ["lvl", "x"])
        raise AssertionError("level guard did NOT trip")
    except ValueError as e:
        print(f"level guard OK: {e}")
