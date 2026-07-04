"""
Fear/Greed composite: the same methodology as CNN's Fear & Greed Index
(each input percentile-ranked against its own history, then averaged into
a 0-100 score), built from data this pipeline already fetches -- no new
sources needed.

Components (each converted to a 0-100 "greed score" -- 100 = greediest
reading in that series' history, 0 = most fearful):
- Volatility: India VIX, INVERTED (low VIX = complacency = greed)
- Momentum: Nifty 50 trailing 3-month return
- Foreign flow: FII/FPI monthly net equity flow (buying = greed)
- Domestic flow: domestic MF monthly net equity flow (buying = greed)
- Retail conviction: SIP contribution YoY% growth (accelerating = greed)

This is a sentiment/positioning read, not a valuation or forward-return
model -- see src/study_a.py and the report's "Current read" verdict for
those. SIP YoY has only ~12 non-null months in this dataset (need a prior
year to compute YoY at all), so its percentile is on a much smaller
reference distribution than the other four (140-230+ months); it's
included because retail conviction is this project's core signal, but
flagged as low-confidence in the rendered output.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import flows_fii, market_data

LABELS = [
    (0, 25, "Extreme Fear"),
    (25, 45, "Fear"),
    (45, 55, "Neutral"),
    (55, 75, "Greed"),
    (75, 101, "Extreme Greed"),
]


def label_for(score: float) -> str:
    for lo, hi, label in LABELS:
        if lo <= score < hi:
            return label
    return "Neutral"


def _percentile_rank(series: pd.Series) -> pd.Series:
    """Each value's percentile (0-100) within the series' own full
    history -- NaN-safe, so months with an unknown value get NaN back."""
    s = pd.to_numeric(series, errors="coerce")
    return s.rank(pct=True, na_option="keep") * 100


@dataclass
class Component:
    name: str
    score: float  # 0-100 greed score, latest available
    month: str
    raw_value: float
    n_history: int
    low_confidence: bool = False


def build_fear_greed_frame(sip_df: pd.DataFrame) -> pd.DataFrame:
    """One row per month with each component's 0-100 greed score plus the
    composite (mean of whichever components have data that month)."""
    flows = flows_fii.load_flows()
    market = market_data.load_market()

    market = market.copy()
    market["nifty_3m_return"] = market["nifty_close"].pct_change(3) * 100
    market["vix_greed"] = 100 - _percentile_rank(market["india_vix"])
    market["momentum_greed"] = _percentile_rank(market["nifty_3m_return"])

    flows = flows.copy()
    flows["fii_greed"] = _percentile_rank(flows["fpi_equity_cr"])
    flows["mf_greed"] = _percentile_rank(flows["mf_equity_cr"])

    sip = sip_df[["month", "sip_contribution_cr_yoy_pct"]].copy()
    sip["sip_greed"] = _percentile_rank(sip["sip_contribution_cr_yoy_pct"])

    frame = (
        market[["month", "vix_greed", "momentum_greed"]]
        .merge(flows[["month", "fii_greed", "mf_greed"]], on="month", how="outer")
        .merge(sip[["month", "sip_greed"]], on="month", how="outer")
        .sort_values("month")
        .reset_index(drop=True)
    )
    score_cols = ["vix_greed", "momentum_greed", "fii_greed", "mf_greed", "sip_greed"]
    frame["composite"] = frame[score_cols].mean(axis=1, skipna=True)
    frame["n_components"] = frame[score_cols].notna().sum(axis=1)
    return frame


def latest_reading(sip_df: pd.DataFrame) -> dict:
    """Composite score + per-component breakdown for the most recent month
    that has at least 3 of the 5 components available."""
    frame = build_fear_greed_frame(sip_df)
    usable = frame[frame["n_components"] >= 3]
    if usable.empty:
        return {"month": None, "composite": None, "label": None, "components": []}

    row = usable.iloc[-1]
    month = row["month"]

    flows = flows_fii.load_flows()
    market = market_data.load_market().copy()
    market["nifty_3m_return"] = market["nifty_close"].pct_change(3) * 100

    def _raw_and_n(df, col, month):
        n_hist = df[col].notna().sum()
        m = df[df["month"] == month]
        raw = float(m.iloc[0][col]) if not m.empty and pd.notna(m.iloc[0][col]) else None
        return raw, int(n_hist)

    specs = [
        ("Volatility (India VIX, inverted)", "vix_greed", market, "india_vix", False),
        ("Momentum (Nifty 3m return)", "momentum_greed", market, "nifty_3m_return", False),
        ("Foreign flow (FII equity)", "fii_greed", flows, "fpi_equity_cr", False),
        ("Domestic flow (MF equity)", "mf_greed", flows, "mf_equity_cr", False),
        ("Retail conviction (SIP YoY%)", "sip_greed", sip_df, "sip_contribution_cr_yoy_pct", True),
    ]
    components = []
    for name, score_col, src_df, raw_col, low_conf in specs:
        score = row.get(score_col)
        if pd.isna(score):
            continue
        raw, n_hist = _raw_and_n(src_df, raw_col, month)
        components.append(Component(
            name=name, score=float(score), month=str(month),
            raw_value=raw, n_history=n_hist, low_confidence=low_conf,
        ))

    return {
        "month": month,
        "composite": float(row["composite"]),
        "label": label_for(row["composite"]),
        "components": components,
    }
