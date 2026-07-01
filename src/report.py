"""
Builds a static HTML report: the trend chart plus a handful of computed
key-insight bullets, both derived straight from data/processed/sip_monthly.csv
(no hardcoded figures, so it stays correct as more months are backfilled).

Usage: python main.py report -> writes data/processed/report.html
"""

import pathlib

import pandas as pd
import matplotlib.pyplot as plt

from . import db

PROCESSED_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "processed"
CHART_PATH = PROCESSED_DIR / "sip_trend.png"
REPORT_PATH = PROCESSED_DIR / "report.html"

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


def draw_chart(df: pd.DataFrame, out_path: pathlib.Path = CHART_PATH) -> pathlib.Path:
    plot_df = df.dropna(subset=["sip_contribution_cr"])

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(plot_df["month"], plot_df["sip_contribution_cr"], marker="o")
    ax.set_title("Monthly SIP Contribution (₹ crore)")
    ax.set_xlabel("Month")
    ax.set_ylabel("₹ crore")
    plt.xticks(rotation=45, ha="right")
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
        mom_month = _prior_month_label(latest_month, 1)
        mom_val = _value_for_month(df, mom_month, "sip_contribution_cr")
        mom_txt = ""
        if mom_val:
            pct = (latest_contrib - mom_val) / mom_val * 100
            mom_txt = f" ({pct:+.1f}% MoM vs {mom_month})"

        yoy_month = _prior_month_label(latest_month, 12)
        yoy_val = _value_for_month(df, yoy_month, "sip_contribution_cr")
        yoy_txt = ""
        if yoy_val:
            pct = (latest_contrib - yoy_val) / yoy_val * 100
            yoy_txt = f", {pct:+.1f}% YoY vs {yoy_month}"

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

    completeness = df["sip_contribution_cr"].notna().sum()
    insights.append(
        f"Coverage caveat: SIP contribution figure present for {completeness}/{len(df)} months -- "
        "AMFI's Monthly Note phrasing varies enough that some months' figures aren't extracted yet."
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


def build_report() -> pathlib.Path:
    df = _load_df()
    draw_chart(df)
    insights = compute_insights(df)
    return generate_html(df, insights)
