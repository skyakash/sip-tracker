"""
Monthly GST collections (Rs crore) -- the consumption/economic-activity
proxy for Study C.

Why these sources (investigated live, in order of what actually worked):
- Official: PIB publishes per-month press releases and gst.gov.in hosts
  per-month PDFs, but neither exposes a single time-series table, and the
  GST portal stats page is a JS shell. data.gov.in's API returned nothing
  for GST collections. FADA auto retail (the second consumption proxy in
  the original plan) renders an empty page even in a real browser -- heavy
  bot protection -- so it's DEFERRED; GST alone proxies consumption here.
- Wikipedia "Goods and Services Tax (India) Revenue Statistics" carries
  exact per-month collections in Rs crore with PIB citations, FY 2017-18
  through ~Jan 2025 (the page lags a few months).
- Tata Nexarc's GST blog table covers the recent months (Mar 2025 onward)
  but only to 0.01 lakh-crore precision (~Rs 1,000 cr, i.e. ~0.5% on
  current collection levels) and has occasional gaps (Sep 2025 missing at
  the time of writing). Good enough for YoY-change studies on a series
  growing 8-13%/yr; the `source` column records which rows are coarse.

Validated: Apr 2024 = 210,267 cr (the widely-reported first Rs 2-lakh-crore
month), Apr 2026 ~ 2.43 lakh cr (record high per press coverage), May 2026
~ 1.94 lakh cr (matches press).

Cached to data/processed/gst_monthly.csv.
"""

import pathlib
import re
from datetime import datetime, timezone
from io import StringIO

import pandas as pd
import requests

PROCESSED_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "processed"
CACHE_PATH = PROCESSED_DIR / "gst_monthly.csv"

WIKI_URL = "https://en.wikipedia.org/wiki/Goods_and_Services_Tax_(India)_Revenue_Statistics"
NEXARC_URL = "https://blog.tatanexarc.com/msme/gst-collection-monthly-and-yearly-trends/"

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

_MONTH_NUM = {
    "april": 4, "may": 5, "june": 6, "july": 7, "august": 8, "september": 9,
    "october": 10, "november": 11, "december": 12, "january": 1,
    "february": 2, "march": 3,
}

# e.g. "₹210,267 crore (US$22 billion)[2]" / "₹1,76,200 crore" / "193384"
_CRORE_RE = re.compile(r"([\d,]+)")


def _parse_crore_cell(cell) -> float | None:
    if pd.isna(cell):
        return None
    text = str(cell).replace("₹", "").strip()
    m = _CRORE_RE.search(text)
    if not m:
        return None
    val = float(m.group(1).replace(",", ""))
    # Guard against picking up stray footnote digits or US$ figures.
    # Lower bound must clear Apr 2020 (~32,294 cr, the COVID-lockdown
    # collapse -- a real value, initially filtered by a 50k floor).
    return val if 30_000 <= val <= 400_000 else None


def _fy_month_to_iso(fy_label: str, month_name: str) -> str | None:
    """('2024-25', 'January') -> '2025-01'; Apr-Dec belong to the FY's
    first year, Jan-Mar to the second."""
    m = re.match(r"(20\d{2})", str(fy_label))
    month = _MONTH_NUM.get(month_name.strip().lower())
    if not m or month is None:
        return None
    year = int(m.group(1)) + (1 if month <= 3 else 0)
    return f"{year}-{month:02d}"


def fetch_gst_wikipedia() -> pd.DataFrame:
    """Exact per-month collections from the Wikipedia revenue-statistics
    page (FY 2017-18 -> wherever the page currently ends)."""
    resp = requests.get(WIKI_URL, headers=UA, timeout=30)
    resp.raise_for_status()
    tables = pd.read_html(StringIO(resp.text))

    rows = []
    for table in tables:
        if not isinstance(table.columns, pd.MultiIndex):
            continue
        top = [str(c[0]) for c in table.columns]
        sub = [str(c[1]) for c in table.columns]
        if "Month" not in top or "Collections" not in sub:
            continue
        for _, row in table.iterrows():
            month_name = str(row.iloc[0]).strip()
            if month_name.lower() not in _MONTH_NUM:
                continue  # Annual Average etc.
            for col_idx, (fy, kind) in enumerate(zip(top, sub)):
                if kind != "Collections":
                    continue
                iso = _fy_month_to_iso(fy, month_name)
                val = _parse_crore_cell(row.iloc[col_idx])
                if iso and val is not None:
                    rows.append({"month": iso, "gst_collection_cr": val, "source": "wikipedia"})

    df = pd.DataFrame(rows).drop_duplicates(subset="month")
    return df


def fetch_gst_nexarc() -> pd.DataFrame:
    """Recent months from Tata Nexarc's table -- values in Rs lakh crore at
    2-decimal precision (~Rs 1,000 cr), converted to crore."""
    resp = requests.get(NEXARC_URL, headers=UA, timeout=30)
    resp.raise_for_status()
    tables = pd.read_html(StringIO(resp.text))

    table = next(
        (t for t in tables
         if any("GST collection" in str(c) for c in t.columns) and len(t) > 5),
        None,
    )
    if table is None:
        raise RuntimeError("Nexarc GST table not found -- page layout changed?")

    month_col = table.columns[0]
    value_col = next(c for c in table.columns if "GST collection" in str(c))

    rows = []
    for _, row in table.iterrows():
        try:
            dt = datetime.strptime(str(row[month_col]).strip(), "%B %Y")
        except ValueError:
            continue
        text = str(row[value_col]).replace("₹", "").replace("+", "").strip()
        try:
            lakh_cr = float(text)
        except ValueError:
            continue
        rows.append({
            "month": f"{dt.year}-{dt.month:02d}",
            "gst_collection_cr": lakh_cr * 100_000,
            "source": "nexarc_approx",
        })

    return pd.DataFrame(rows)


# Months missing from both scraped sources, filled from press coverage of
# the official PIB figures (verified via multiple outlets 2026-07):
#   Feb 2025: Rs 1,83,646 cr ("grew 9.1% to about Rs 1.84 lakh crore")
#   Sep 2025: Rs 1,89,017 cr ("rises 9.1% to Rs 1.89 lakh crore")
_PRESS_PATCHES = [
    {"month": "2025-02", "gst_collection_cr": 183_646.0, "source": "press_published"},
    {"month": "2025-09", "gst_collection_cr": 189_017.0, "source": "press_published"},
]


def fetch_gst_monthly(force: bool = False) -> pd.DataFrame:
    """Merged [month, gst_collection_cr, source], Wikipedia preferred where
    both cover a month (exact beats ~1,000-cr-rounded), cached."""
    if CACHE_PATH.exists() and not force:
        return pd.read_csv(CACHE_PATH)

    wiki = fetch_gst_wikipedia()
    nexarc = fetch_gst_nexarc()
    nexarc_only = nexarc[~nexarc["month"].isin(wiki["month"])]
    merged = pd.concat([wiki, nexarc_only])
    patches = pd.DataFrame([p for p in _PRESS_PATCHES if p["month"] not in set(merged["month"])])
    merged = (
        pd.concat([merged, patches])
        .sort_values("month")
        .reset_index(drop=True)
    )

    this_month = datetime.now(timezone.utc).strftime("%Y-%m")
    merged = merged[merged["month"] < this_month].reset_index(drop=True)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    merged.to_csv(CACHE_PATH, index=False)
    return merged


def load_gst() -> pd.DataFrame:
    """Read the cached GST series with no network access. Bootstraps with a
    full fetch if there's no cache yet. (Unlike NSDL's per-year postback
    loop, Wikipedia+Nexarc are single-page fetches regardless of history
    length, so fetch_gst_monthly(force=True) is already cheap -- this
    wrapper exists for the same read/refresh naming split as flows_fii and
    market_data, not because a full refetch here is expensive.)"""
    if not CACHE_PATH.exists():
        return fetch_gst_monthly(force=True)
    return pd.read_csv(CACHE_PATH)


def merge_gst(df: pd.DataFrame) -> pd.DataFrame:
    """Left-join GST collections onto a monthly dataframe. Reads from
    cache -- no network access."""
    gst = load_gst()
    return df.merge(gst[["month", "gst_collection_cr"]], on="month", how="left")


if __name__ == "__main__":
    df = fetch_gst_monthly(force=True)
    print(f"{len(df)} months, {df['month'].iloc[0]} -> {df['month'].iloc[-1]}")
    print("by source:", df["source"].value_counts().to_dict())
    missing = pd.period_range(df["month"].iloc[0], df["month"].iloc[-1], freq="M").strftime("%Y-%m")
    gaps = sorted(set(missing) - set(df["month"]))
    print("gaps:", gaps)
    print(df.tail(8).to_string())
