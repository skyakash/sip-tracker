"""
Derived trend metrics computed over the full SIP monthly series.

Everything here operates on the whole DataFrame (not a single month's
record), since these are relative/comparative by nature: MoM/YoY %% change,
a rolling average to smooth the known March/April seasonal swings, ticket
size and flow-composition ratios, and simple outlier flagging so a report
reader's eye goes to genuinely unusual months instead of routine noise.

MoM/YoY are anchored to the true calendar-adjacent month (looked up by ISO
label), not the previous/12th-previous *row* -- the two coincide today since
every month from the backfill start has a row, but that's an assumption
worth not baking in, since a skipped fetch would otherwise silently produce
a wrong multi-month "MoM" comparison.
"""

import pandas as pd

# Metrics that get full MoM/YoY change + outlier flagging. Chosen because
# they're populated for most/all months (so a z-score is meaningful) and are
# the ones a trend read actually hinges on.
TREND_METRICS = ["sip_contribution_cr", "total_industry_aum_lakh_cr"]

OUTLIER_Z_THRESHOLD = 2.0


def _prior_month_label(month: str, months_back: int) -> str:
    year, mon = (int(x) for x in month.split("-"))
    total = year * 12 + (mon - 1) - months_back
    return f"{total // 12}-{(total % 12) + 1:02d}"


def _value_for_month(df: pd.DataFrame, month: str, col: str):
    row = df[df["month"] == month]
    if row.empty or pd.isna(row.iloc[0][col]):
        return None
    return row.iloc[0][col]


def _calendar_pct_change(df: pd.DataFrame, col: str, months_back: int) -> list:
    out = []
    for _, row in df.iterrows():
        val = row[col]
        if pd.isna(val):
            out.append(None)
            continue
        ref = _value_for_month(df, _prior_month_label(row["month"], months_back), col)
        out.append((val - ref) / ref * 100 if ref else None)
    return out


def _calendar_delta(df: pd.DataFrame, col: str, months_back: int = 1) -> list:
    out = []
    for _, row in df.iterrows():
        val = row[col]
        if pd.isna(val):
            out.append(None)
            continue
        ref = _value_for_month(df, _prior_month_label(row["month"], months_back), col)
        out.append(val - ref if ref is not None else None)
    return out


def add_derived_metrics(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    for col in TREND_METRICS:
        df[f"{col}_mom_pct"] = _calendar_pct_change(df, col, 1)
        df[f"{col}_yoy_pct"] = _calendar_pct_change(df, col, 12)

        mom_series = pd.Series(df[f"{col}_mom_pct"], dtype="float64").dropna()
        if len(mom_series) >= 4 and mom_series.std() > 0:
            mu, sigma = mom_series.mean(), mom_series.std()
            df[f"{col}_outlier"] = df[f"{col}_mom_pct"].apply(
                lambda x: pd.notna(x) and abs((x - mu) / sigma) > OUTLIER_Z_THRESHOLD
            )
        else:
            df[f"{col}_outlier"] = False

    # 3-month rolling average of the flagship metric, to see through the
    # known March (ELSS lock-in led stoppage) / April (new-FY mandate) swings
    df["sip_contribution_3m_avg"] = df["sip_contribution_cr"].rolling(3, min_periods=2).mean()

    # Avg monthly SIP ticket size: contribution (Rs crore) / accounts (crore)
    # -- the crore units cancel, giving Rs per contributing account directly.
    df["avg_ticket_rs"] = df["sip_contribution_cr"] / df["contributing_accounts_cr"]

    # How much of that month's equity buying was systematic (SIP) vs.
    # discretionary/institutional -- a falling ratio means equity inflows are
    # increasingly lumpy rather than steady retail flow.
    df["sip_share_of_equity_pct"] = df["sip_contribution_cr"] / df["net_equity_inflow_cr"] * 100

    # Net new contributing accounts added that month (lakh), calendar-aware.
    df["net_new_accounts_lakh"] = [
        v * 100 if v is not None else None
        for v in _calendar_delta(df, "contributing_accounts_cr", 1)
    ]

    return df


def outlier_months(df: pd.DataFrame, col: str = "sip_contribution_cr") -> pd.DataFrame:
    """Rows flagged as MoM outliers for the given metric, most recent first."""
    flag_col = f"{col}_outlier"
    if flag_col not in df.columns:
        return df.iloc[0:0]
    return df[df[flag_col]].sort_values("month", ascending=False)
