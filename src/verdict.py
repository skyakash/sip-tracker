"""
Plain-English "who's buying/selling right now" read -- the actionable
summary the z-score heatmap and Study A table don't give you directly: a
one-look answer to "are foreigners / domestic funds / retail buying or
selling, and what has historically followed a setup like this."

This is a description of current + recent flow direction plus Study A's
historical precedent, NOT a sized trading signal -- every bucket in this
project has small N (12-24 months). The verdict text always carries that
caveat; treat it as a structured way to read the tape, not an instruction.

Direction is the SIGN of the latest raw flow (buying vs selling actually
happened); intensity is that flow's 36-month rolling z-score (how unusual
vs recent norms). The two are reported together because sign alone hides
whether "FII selling" is routine (-5,000 cr, well within normal range) or
a regime event (-1,00,000 cr, several sigma out) -- and z-score alone
hides direction if you don't also know the series' current sign convention.
"""

from dataclasses import dataclass

import pandas as pd

from . import flows_fii, market_data, study_a


_ADVERBS = {"extreme": "extremely", "heavy": "heavily", "moderate": "moderately", "mild": "mildly"}


def _intensity_label(z: float) -> str:
    if pd.isna(z):
        return "unknown"
    az = abs(z)
    if az >= 2:
        return "extreme"
    if az >= 1:
        return "heavy"
    if az >= 0.5:
        return "moderate"
    return "mild"


@dataclass
class FlowRead:
    month: str
    value: float
    z: float
    direction: str  # "buying" | "selling" | "accelerating" | "decelerating"
    intensity: str  # "extreme" | "heavy" | "moderate" | "mild" | "unknown"

    def sentence(self, who: str, unit: str = "cr") -> str:
        if pd.isna(self.z):
            return f"{who}: no data for {self.month}."
        qualifier = "" if self.intensity == "mild" else f"{self.intensity} "
        return (
            f"{who} ({self.month}): {qualifier}{self.direction} "
            f"(₹{self.value:,.0f} {unit}, {self.z:+.1f}σ vs 36-month norm)."
        )


def _latest_flow_read(df: pd.DataFrame, value_col: str, z_col: str,
                      buy_label: str = "buying", sell_label: str = "selling") -> FlowRead | None:
    sub = df.dropna(subset=[value_col, z_col])
    if sub.empty:
        return None
    row = sub.iloc[-1]
    direction = buy_label if row[value_col] > 0 else sell_label
    return FlowRead(
        month=row["month"], value=row[value_col], z=row[z_col],
        direction=direction, intensity=_intensity_label(row[z_col]),
    )


def _sip_conviction_read(sip_df: pd.DataFrame) -> FlowRead | None:
    """SIP contribution is almost always positive -- "buying/selling"
    doesn't apply. What matters is whether retail conviction (YoY growth)
    is accelerating or decelerating."""
    sub = sip_df.dropna(subset=["sip_contribution_cr_yoy_pct"])
    if sub.empty:
        return None
    row = sub.iloc[-1]
    yoy = row["sip_contribution_cr_yoy_pct"]
    mom = row.get("sip_contribution_cr_mom_pct")
    direction = "accelerating" if pd.notna(mom) and mom > 0 else "decelerating"
    # Reuse YoY magnitude as a rough intensity proxy (SIP YoY has run
    # 15-30% through this dataset's window; no long enough history for a
    # stable rolling z here the way FII/MF get one).
    intensity = "strong" if yoy > 20 else ("moderate" if yoy > 10 else "soft")
    return FlowRead(month=row["month"], value=yoy, z=float("nan"),
                    direction=direction, intensity=intensity)


def _vix_regime(market_df: pd.DataFrame) -> tuple[str, float, str] | None:
    sub = market_df.dropna(subset=["india_vix"])
    if sub.empty:
        return None
    row = sub.iloc[-1]
    v = row["india_vix"]
    if v >= 25:
        regime = "stressed"
    elif v >= 18:
        regime = "elevated"
    elif v >= 12:
        regime = "calm"
    else:
        regime = "complacent"
    return row["month"], v, regime


def _bucket_precedent(bucket: str) -> str | None:
    """Study A's forward-return read for a given bucket, if it has one."""
    _, summary = study_a.run_study()
    row = summary[summary["bucket"] == bucket]
    if row.empty:
        return None
    r = row.iloc[0]
    return (
        f"months like this (N={int(r['months'])}) historically saw Nifty "
        f"average {r['fwd_3m_mean']:+.1f}% over the next 3 months "
        f"({r['fwd_3m_pos_pct']:.0f}% of the time positive) -- exploratory, "
        f"small sample."
    )


def build_verdict(sip_df: pd.DataFrame) -> dict:
    """Returns the components + a rendered headline/detail text for the
    report. sip_df must already carry trends.add_derived_metrics() output."""
    flows = flows_fii.load_flows()
    flows["fpi_z"] = study_a._rolling_z(flows["fpi_equity_cr"])
    flows["mf_z"] = study_a._rolling_z(flows["mf_equity_cr"])
    market = market_data.load_market()

    fii = _latest_flow_read(flows, "fpi_equity_cr", "fpi_z")
    mf = _latest_flow_read(flows, "mf_equity_cr", "mf_z")
    sip = _sip_conviction_read(sip_df)
    vix = _vix_regime(market)

    lines = []
    if fii:
        lines.append(fii.sentence("Foreign investors (FII)"))
    if mf:
        lines.append(mf.sentence("Domestic mutual funds"))
    if sip:
        lines.append(
            f"Retail SIP conviction ({sip.month}): {sip.direction} "
            f"({sip.intensity} growth, {sip.value:+.1f}% YoY)."
        )
    if vix:
        month, val, regime = vix
        lines.append(f"India VIX ({month}): {val:.1f} -- {regime} volatility regime.")

    headline = "Not enough recent data to read the current setup."
    precedent = None
    if fii and mf:
        if fii.direction == "selling" and fii.intensity in ("heavy", "extreme"):
            fii_adv = _ADVERBS[fii.intensity]
            if mf.direction == "buying" and mf.intensity in ("heavy", "extreme"):
                bucket = "heavy_sell_strong_absorption"
                headline = (
                    f"{fii.month}: foreigners selling {fii_adv}, "
                    "domestic funds absorbing strongly."
                )
            else:
                bucket = "heavy_sell_weak_absorption"
                headline = (
                    f"{fii.month}: foreigners selling {fii_adv}, "
                    "domestic absorption is NOT keeping pace."
                )
            precedent = _bucket_precedent(bucket)
        elif fii.direction == "buying" and mf.direction == "buying":
            headline = f"{fii.month}: both foreign and domestic funds buying -- broad-based inflow."
        elif fii.direction == "selling" and mf.direction == "selling":
            headline = f"{fii.month}: both foreign and domestic funds selling -- broad-based outflow, no cushion."
        else:
            headline = f"{fii.month}: mixed -- {fii.direction} foreign flow, {mf.direction} domestic flow."

    return {
        "headline": headline,
        "precedent": precedent,
        "lines": lines,
    }


def verdict_html(sip_df: pd.DataFrame) -> str:
    v = build_verdict(sip_df)
    lines_html = "\n".join(f"<li>{line}</li>" for line in v["lines"])
    precedent_html = f"<p class='precedent'>{v['precedent']}</p>" if v["precedent"] else ""
    return f"""
<div class="verdict-box">
<h2>Current read: who's buying, who's selling</h2>
<p class="headline">{v['headline']}</p>
{precedent_html}
<ul>
{lines_html}
</ul>
<p class="caveat">Describes current + recent flow direction and cites
Study A's historical precedent where applicable. Not a sized trading
signal -- every bucket here has a small sample (12-24 months); use this to
read the tape, not as an instruction.</p>
</div>
"""
