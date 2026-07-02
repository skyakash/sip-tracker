"""
Builds a static HTML report: the trend chart plus a handful of computed
key-insight bullets, both derived straight from data/processed/sip_monthly.csv
(no hardcoded figures, so it stays correct as more months are backfilled).

Usage: python main.py report -> writes data/processed/report.html
"""

import pathlib

import pandas as pd
import matplotlib.pyplot as plt

from . import db, trends, market_data

PROCESSED_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "processed"
CHART_PATH = PROCESSED_DIR / "sip_trend.png"
REPORT_PATH = PROCESSED_DIR / "report.html"

# Jan-Apr 2025: AMFI's dormant-folio reconciliation window (~1.43cr folios
# purged). Shaded on the chart so it doesn't get misread as an organic trend.
RECONCILIATION_WINDOW = ("2025-01", "2025-04")

NUMERIC_FIELDS = [
    "sip_contribution_cr", "sip_aum_lakh_cr", "sip_aum_pct_of_total_aum",
    "contributing_accounts_cr", "new_sips_registered_lakh", "sips_discontinued_lakh",
    "stoppage_ratio_pct", "total_industry_aum_lakh_cr", "total_folios_cr",
    "net_equity_inflow_cr",
]


def _load_df() -> pd.DataFrame:
    rows = db.load_all()
    df = pd.DataFrame(rows)
    for col in NUMERIC_FIELDS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.sort_values("month").reset_index(drop=True)


def _shade_reconciliation_window(ax, dates: pd.Series) -> None:
    start, end = (pd.Timestamp(m + "-01") for m in RECONCILIATION_WINDOW)
    if start < dates.min() or end > dates.max():
        return
    ax.axvspan(start, end, color="orange", alpha=0.12, zorder=0,
               label="Jan-Apr 2025 dormant-folio reconciliation")


def draw_chart(df: pd.DataFrame, out_path: pathlib.Path = CHART_PATH) -> pathlib.Path:
    """
    Three-panel view, all sharing a real datetime x-axis (so matplotlib
    auto-spaces the tick labels instead of cramming 24 categorical strings)
    and the same month range, so gaps in one metric don't shift another's
    points out of calendar alignment: contribution (+3mo rolling avg,
    +Nifty overlay, +outlier markers, +shaded reconciliation window), SIP
    AUM as % of industry AUM, and contributing accounts.
    """
    dates = pd.to_datetime(df["month"] + "-01")

    fig, axes = plt.subplots(3, 1, figsize=(11, 13), sharex=True)
    ax0, ax1, ax2 = axes

    # Panel 1: contribution + rolling avg + Nifty overlay + outliers
    ax0.plot(dates, df["sip_contribution_cr"], marker="o", label="Monthly contribution", color="C0")
    if "sip_contribution_3m_avg" in df.columns:
        ax0.plot(dates, df["sip_contribution_3m_avg"], linestyle="--", color="C0", alpha=0.5,
                  label="3-month rolling avg")
    if "sip_contribution_cr_outlier" in df.columns:
        outlier_mask = df["sip_contribution_cr_outlier"]
        if outlier_mask.any():
            ax0.scatter(dates[outlier_mask], df.loc[outlier_mask, "sip_contribution_cr"], color="red",
                        zorder=5, marker="*", s=150, label="Unusual MoM change")
    _shade_reconciliation_window(ax0, dates)
    ax0.set_title("Monthly SIP Contribution (₹ crore)")
    ax0.set_ylabel("₹ crore")

    if "nifty_close" in df.columns and df["nifty_close"].notna().any():
        ax0b = ax0.twinx()
        ax0b.plot(dates, df["nifty_close"], color="gray", alpha=0.6, linewidth=1, label="Nifty 50 (close)")
        ax0b.set_ylabel("Nifty 50", color="gray")
        ax0b.tick_params(axis="y", labelcolor="gray")
        lines0, labels0 = ax0.get_legend_handles_labels()
        lines0b, labels0b = ax0b.get_legend_handles_labels()
        ax0.legend(lines0 + lines0b, labels0 + labels0b, fontsize=8, loc="upper left",
                   bbox_to_anchor=(1.08, 1))
    else:
        ax0.legend(fontsize=8, loc="upper left", bbox_to_anchor=(1.08, 1))

    # Panel 2: SIP AUM as % of total industry AUM
    ax1.plot(dates, df["sip_aum_pct_of_total_aum"], marker="o", color="C2")
    _shade_reconciliation_window(ax1, dates)
    ax1.set_title("SIP AUM as % of Total Industry AUM")
    ax1.set_ylabel("%")

    # Panel 3: contributing accounts
    ax2.plot(dates, df["contributing_accounts_cr"], marker="o", color="C3")
    _shade_reconciliation_window(ax2, dates)
    ax2.set_title("Contributing SIP Accounts (crore)")
    ax2.set_ylabel("crore")
    ax2.set_xlabel("Month")

    import matplotlib.dates as mdates
    ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.setp(ax2.get_xticklabels(), rotation=45, ha="right", fontsize=9)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def _latest(df: pd.DataFrame, col: str):
    """Most recent non-null (month, value) pair for a column, or (None, None)."""
    sub = df.dropna(subset=[col])
    if sub.empty:
        return None, None
    row = sub.iloc[-1]
    return row["month"], row[col]


def _value_for_month(df: pd.DataFrame, month: str, col: str):
    row = df[df["month"] == month]
    if row.empty or pd.isna(row.iloc[0][col]):
        return None
    return row.iloc[0][col]


def _prior_month_label(month: str, months_back: int) -> str:
    year, mon = (int(x) for x in month.split("-"))
    total = year * 12 + (mon - 1) - months_back
    return f"{total // 12}-{(total % 12) + 1:02d}"


def compute_insights(df: pd.DataFrame) -> list[str]:
    insights = []
    if df.empty:
        return ["No data yet -- run `python main.py fetch-month \"<Month Year>\"` first."]

    first_month, last_month = df["month"].iloc[0], df["month"].iloc[-1]
    insights.append(
        f"Covers {len(df)} months, {first_month} to {last_month}."
    )

    latest_month, latest_contrib = _latest(df, "sip_contribution_cr")
    if latest_month:
        latest_row = df[df["month"] == latest_month].iloc[0]
        mom_txt = f" ({latest_row['sip_contribution_cr_mom_pct']:+.1f}% MoM)" \
            if pd.notna(latest_row.get("sip_contribution_cr_mom_pct")) else ""
        yoy_txt = f", {latest_row['sip_contribution_cr_yoy_pct']:+.1f}% YoY" \
            if pd.notna(latest_row.get("sip_contribution_cr_yoy_pct")) else ""
        insights.append(
            f"Latest SIP contribution ({latest_month}): ₹{latest_contrib:,.0f} crore{mom_txt}{yoy_txt}."
        )

    high_row = df.loc[df["sip_contribution_cr"].idxmax()] if df["sip_contribution_cr"].notna().any() else None
    if high_row is not None:
        insights.append(
            f"All-time high in this dataset: ₹{high_row['sip_contribution_cr']:,.0f} crore in {high_row['month']}."
        )

    aum_month, aum_val = _latest(df, "sip_aum_lakh_cr")
    pct_month, pct_val = _latest(df, "sip_aum_pct_of_total_aum")
    if aum_month:
        pct_txt = f", {pct_val:.1f}% of total industry AUM" if pct_month == aum_month and pct_val else ""
        insights.append(f"SIP AUM ({aum_month}): ₹{aum_val:.2f} lakh crore{pct_txt}.")

    acc_month, acc_val = _latest(df, "contributing_accounts_cr")
    if acc_month:
        insights.append(f"Contributing SIP accounts ({acc_month}): {acc_val:.2f} crore.")

    eq_month, eq_val = _latest(df, "net_equity_inflow_cr")
    if eq_month:
        insights.append(f"Net equity inflow ({eq_month}): ₹{eq_val:,.0f} crore.")

    # Outlier months: genuinely unusual MoM swings, worth a second look
    for col, label in [("sip_contribution_cr", "SIP contribution"), ("total_industry_aum_lakh_cr", "Total industry AUM")]:
        flagged = trends.outlier_months(df, col)
        if not flagged.empty:
            parts = [f"{r['month']} ({r[f'{col}_mom_pct']:+.1f}% MoM)" for _, r in flagged.iterrows()]
            insights.append(f"Unusual {label} months (>2σ MoM move): {', '.join(parts)}.")

    # Avg ticket size -- flag the purge-window discontinuity so it isn't
    # misread as investors suddenly writing bigger cheques
    ticket_month, ticket_val = _latest(df, "avg_ticket_rs")
    if ticket_month:
        insights.append(
            f"Avg. monthly SIP ticket size ({ticket_month}): ~₹{ticket_val:,.0f} per account. "
            "Note: this jumped across Jan-Apr 2025 mechanically, because the dormant-folio purge shrank the "
            "accounts denominator faster than contribution changed -- not a sign of investors suddenly investing more per SIP."
        )

    # SIP share of net equity inflow -- flow composition signal
    share_month, share_val = _latest(df, "sip_share_of_equity_pct")
    if share_month:
        over_100 = (df["sip_share_of_equity_pct"] > 100).sum()
        insights.append(
            f"SIP contribution was {share_val:.0f}% of net equity inflow in {share_month} "
            f"(only {int(df['sip_share_of_equity_pct'].notna().sum())} months have both figures available; "
            f"{over_100} of those months had SIP contribution alone exceed total net equity inflow -- "
            "meaning discretionary/lump-sum flow was flat or negative that month)."
        )

    # Market context: does SIP contribution hold up through Nifty drawdowns?
    if "nifty_mom_pct" in df.columns and df["nifty_mom_pct"].notna().any():
        both = df.dropna(subset=["sip_contribution_cr_mom_pct", "nifty_mom_pct"])
        if len(both) >= 6:
            corr = both["sip_contribution_cr_mom_pct"].corr(both["nifty_mom_pct"])
            insights.append(
                f"SIP contribution MoM change vs. Nifty 50 MoM change: correlation {corr:+.2f} across "
                f"{len(both)} months -- close to zero/weak means SIP flow doesn't move with the market, "
                "consistent with the 'systematic investing is resilient through drawdowns' narrative."
            )
        worst_nifty = df.loc[df["nifty_mom_pct"].idxmin()] if df["nifty_mom_pct"].notna().any() else None
        if worst_nifty is not None and pd.notna(worst_nifty.get("sip_contribution_cr_mom_pct")):
            insights.append(
                f"Worst Nifty 50 month in this window: {worst_nifty['month']} ({worst_nifty['nifty_mom_pct']:+.1f}%), "
                f"vs. SIP contribution that same month: {worst_nifty['sip_contribution_cr_mom_pct']:+.1f}% MoM."
            )

    completeness = df["sip_contribution_cr"].notna().sum()
    insights.append(
        f"Coverage caveat: SIP contribution figure present for {completeness}/{len(df)} months -- "
        "AMFI's Monthly Note phrasing varies enough that some months' figures aren't extracted yet. "
        "Category-wise debt/hybrid net flows are sparser still and only meant as directional context."
    )
    insights.append(
        "Stoppage ratio / new-vs-discontinued SIP counts are not published in AMFI's Monthly Note at all "
        "and are left blank here; treat any stoppage-ratio figure from elsewhere as a secondary-source number, "
        "not something this pipeline can independently verify."
    )

    return insights


def generate_html(df: pd.DataFrame, insights: list[str], out_path: pathlib.Path = REPORT_PATH,
                   chart_filename: str = "sip_trend.png") -> pathlib.Path:
    rows_html = "\n".join(
        f"<li>{point}</li>" for point in insights
    )
    generated_at = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>AMFI SIP Tracker</title>
<style>
  body {{ font-family: -apple-system, Helvetica, Arial, sans-serif; max-width: 800px;
          margin: 40px auto; padding: 0 20px; color: #1a1a1a; }}
  h1 {{ font-size: 1.4rem; }}
  img {{ max-width: 100%; border: 1px solid #ddd; border-radius: 6px; }}
  ul {{ line-height: 1.6; }}
  .caveat {{ color: #666; font-size: 0.9rem; }}
  footer {{ margin-top: 2rem; font-size: 0.8rem; color: #999; }}
</style>
</head>
<body>
<h1>AMFI SIP Tracker</h1>
<img src="{chart_filename}" alt="Monthly SIP contribution trend">
<h2>Key insights</h2>
<ul>
{rows_html}
</ul>
<footer>Generated {generated_at} from data/processed/sip_monthly.csv.</footer>
</body>
</html>
"""
    out_path.write_text(html)
    return out_path


def load_full_df() -> pd.DataFrame:
    """The SIP series plus derived trend metrics and Nifty overlay -- what
    both the chart and the insights are computed from."""
    df = _load_df()
    df = trends.add_derived_metrics(df)
    df = market_data.merge_market_data(df)
    return df


def build_report() -> pathlib.Path:
    df = load_full_df()
    draw_chart(df)
    insights = compute_insights(df)
    return generate_html(df, insights)
