"""
Study A: who absorbs FII selling, and what happens next?

Question: after months of unusually heavy FII selling, were Nifty's forward
1m/3m/6m returns different when domestic mutual funds absorbed the selling
(bought heavily) vs when domestic absorption was weak?

Mechanism: the defining Indian market dynamic of 2022-2026 -- FII exits
absorbed by domestic SIP-fed MF flows (e.g. Mar 2026: FPI -Rs 1.18 lakh cr,
MF +Rs 0.99 lakh cr, Nifty -11.3%, then +7.5% the next month).

Method notes:
- FII flow intensity is a *rolling 36-month z-score* of monthly FPI equity
  flows, not a full-sample z: rupee flow magnitudes grow over 19 years, so
  a fixed threshold (or full-sample z) would classify almost all pre-2015
  months as calm and recent months as extreme. Rolling z asks "unusual vs
  the recent norm?", which is the tradeable question.
- "Heavy FII selling" = fpi_z < -1. Among those months, absorption is
  split at the *median* MF z-score (median split keeps buckets
  non-degenerate without an arbitrary threshold).
- MF flow data starts Jul 2014, so the bucketed sample effectively starts
  mid-2017 (36m z warm-up); earlier months fall out. All bucket sizes are
  small -- treat the output as an evidence table, not a strategy backtest.
- Forward returns use month-close Nifty; the current partial month is
  already excluded upstream by market_data/flows_fii.

Sanity anchor (verified in tests below): 2026-03 must classify as heavy
FII selling WITH strong absorption.
"""

import pathlib

import pandas as pd

from . import flows_fii, market_data

Z_WINDOW = 36
SELL_THRESHOLD = -1.0
HORIZONS = (1, 3, 6)


def _rolling_z(series: pd.Series, window: int = Z_WINDOW) -> pd.Series:
    mean = series.rolling(window, min_periods=window).mean()
    std = series.rolling(window, min_periods=window).std()
    return (series - mean) / std


def build_dataset() -> pd.DataFrame:
    """Monthly frame: flows, rolling z-scores, Nifty forward returns."""
    flows = flows_fii.build_flows()
    market = market_data.fetch_market_monthly()
    df = flows.merge(market[["month", "nifty_close"]], on="month", how="inner")
    df = df.sort_values("month").reset_index(drop=True)

    df["fpi_z"] = _rolling_z(df["fpi_equity_cr"])
    df["mf_z"] = _rolling_z(df["mf_equity_cr"])

    for h in HORIZONS:
        df[f"fwd_{h}m_pct"] = (df["nifty_close"].shift(-h) / df["nifty_close"] - 1) * 100

    return df


def classify(df: pd.DataFrame) -> pd.DataFrame:
    """Adds a `bucket` column:
    - heavy_sell_strong_absorption / heavy_sell_weak_absorption
      (median split of mf_z among heavy-FII-selling months)
    - other (everything else with valid z-scores)
    """
    df = df.copy()
    df["bucket"] = None
    valid = df["fpi_z"].notna()
    selling = valid & (df["fpi_z"] < SELL_THRESHOLD) & df["mf_z"].notna()

    if selling.sum() >= 4:
        median_mf = df.loc[selling, "mf_z"].median()
        df.loc[selling & (df["mf_z"] >= median_mf), "bucket"] = "heavy_sell_strong_absorption"
        df.loc[selling & (df["mf_z"] < median_mf), "bucket"] = "heavy_sell_weak_absorption"
    df.loc[valid & df["bucket"].isna(), "bucket"] = "other"
    return df


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    """Forward-return stats per bucket. N varies by horizon (later months
    lack forward data)."""
    rows = []
    for bucket, grp in df[df["bucket"].notna()].groupby("bucket"):
        row = {"bucket": bucket, "months": len(grp)}
        for h in HORIZONS:
            fwd = grp[f"fwd_{h}m_pct"].dropna()
            row[f"fwd_{h}m_n"] = len(fwd)
            row[f"fwd_{h}m_mean"] = round(fwd.mean(), 2) if len(fwd) else None
            row[f"fwd_{h}m_median"] = round(fwd.median(), 2) if len(fwd) else None
            row[f"fwd_{h}m_pos_pct"] = round((fwd > 0).mean() * 100, 0) if len(fwd) else None
        rows.append(row)
    order = ["heavy_sell_strong_absorption", "heavy_sell_weak_absorption", "other"]
    out = pd.DataFrame(rows)
    out["__o"] = out["bucket"].map({b: i for i, b in enumerate(order)})
    return out.sort_values("__o").drop(columns="__o").reset_index(drop=True)


def run_study() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (classified per-month frame, bucket summary)."""
    df = classify(build_dataset())
    return df, summarize(df)


if __name__ == "__main__":
    df, summary = run_study()

    print(f"dataset: {len(df)} months, z-scores valid from "
          f"{df[df['fpi_z'].notna()]['month'].iloc[0]}")
    counts = df["bucket"].value_counts()
    print(f"buckets: {counts.to_dict()}\n")

    print("=== heavy FII selling months (most recent 12) ===")
    sell = df[df["bucket"].astype(str).str.startswith("heavy_sell")]
    cols = ["month", "fpi_equity_cr", "mf_equity_cr", "fpi_z", "mf_z", "bucket",
            "fwd_1m_pct", "fwd_3m_pct"]
    print(sell[cols].tail(12).to_string(index=False))

    # Sanity anchor from the plan: Mar 2026 (record FII selling, record MF
    # buying) must land in heavy_sell_strong_absorption.
    mar26 = df[df["month"] == "2026-03"]
    assert len(mar26) == 1, "2026-03 missing from dataset"
    assert mar26.iloc[0]["bucket"] == "heavy_sell_strong_absorption", (
        f"sanity check failed: 2026-03 classified as {mar26.iloc[0]['bucket']}"
    )
    print("\nsanity check OK: 2026-03 -> heavy_sell_strong_absorption")

    print("\n=== bucket summary (Nifty forward returns, %) ===")
    print(summary.to_string(index=False))
