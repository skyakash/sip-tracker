"""
Monthly FII/FPI and domestic mutual-fund net equity flows -- the two legs of
Study A ("who absorbs FII selling, and what happens next").

Two sources, both validated against independently published figures before
being trusted (same discipline as the AMFI parser):

1. FPI equity net investment -- NSDL FPI monitor (fpi.nsdl.co.in), the
   authoritative depository source, monthly back to 2002. The page is an
   ASP.NET form: year selection is a __VIEWSTATE postback on the `ddl`
   dropdown, scriptable with plain requests (no Playwright needed).
   Validated: Mar 2020 = -61,973 cr (the canonical COVID-crash figure) and
   all of 2026 matches other mirrors to the rupee.
   NOTE: the "Mutual Funds" columns in NSDL's table are FPIs investing
   *via* the MF route (tiny numbers), NOT domestic MF flows -- ignore them.

2. Domestic MF net equity investment (the "absorption" leg) -- Trendlyne's
   monthly FII/DII snapshot (originally SEBI mutual-fund trends data),
   monthly back to Jul 2014. JS-rendered, so fetched via Playwright.
   Validated: Mar 2020 = 30,285.6 vs Rs 30,285 cr published from SEBI data
   (exact); Mar 2026 = 98,746 matches the "record ~Rs 1 trillion MF equity
   buying" press coverage; Trendlyne's FII column matches NSDL exactly for
   2026, showing they mirror the authoritative sources.

Cached to data/processed/fii_dii_monthly.csv. The current calendar month is
always dropped (both sources publish partial month-to-date figures).
"""

import pathlib
import re
from datetime import datetime, timezone
from io import StringIO

import pandas as pd
import requests

PROCESSED_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "processed"
CACHE_PATH = PROCESSED_DIR / "fii_dii_monthly.csv"

NSDL_URL = "https://www.fpi.nsdl.co.in/Reports/Yearwise.aspx?RptType=6"
TRENDLYNE_URL = "https://trendlyne.com/macro-data/fii-dii/latest/snapshot-month/"

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}


def _hidden_field(name: str, html: str) -> str:
    m = re.search(r'id="' + name + r'" value="([^"]*)"', html)
    return m.group(1) if m else ""


def fetch_fpi_monthly(start_year: int = 2007) -> pd.DataFrame:
    """FPI net equity investment (Rs crore) per month from NSDL, one
    __VIEWSTATE postback per year. Returns [month, fpi_equity_cr]."""
    import time

    session = requests.Session()

    def fetch_year(year: int) -> list[dict]:
        # Fresh GET per year: chaining postbacks off the previous response's
        # viewstate silently stops working after ~10 years (stale state),
        # which surfaced as 2017+ returning no data.
        resp = session.get(NSDL_URL, headers=UA, timeout=30)
        resp.raise_for_status()
        data = {
            "__EVENTTARGET": "ddl",
            "__EVENTARGUMENT": "",
            "__VIEWSTATE": _hidden_field("__VIEWSTATE", resp.text),
            "__VIEWSTATEGENERATOR": _hidden_field("__VIEWSTATEGENERATOR", resp.text),
            "__EVENTVALIDATION": _hidden_field("__EVENTVALIDATION", resp.text),
            "ddl": str(year),
        }
        resp = session.post(NSDL_URL, data=data, headers=UA, timeout=30)
        resp.raise_for_status()

        table = pd.read_html(StringIO(resp.text))[1]
        table.columns = range(len(table.columns))
        # Column layout varies by year (5 cols in 2015, 14 in 2026) but
        # column 0 is always the month name and column 1 FPI equity.
        year_rows = []
        for _, row in table.iterrows():
            label = str(row[0]).strip().lower().replace("*", "").strip()
            if label not in _MONTHS:
                continue  # Total rows, footnotes
            val = pd.to_numeric(str(row[1]).replace(",", ""), errors="coerce")
            if pd.isna(val):
                continue
            year_rows.append(
                {"month": f"{year}-{_MONTHS[label]:02d}", "fpi_equity_cr": float(val)}
            )
        return year_rows

    rows = []
    current_year = datetime.now().year
    for year in range(start_year, current_year + 1):
        # The NSDL server intermittently returns an empty/error page with
        # HTTP 200; treat "no month rows" as retryable, not structural.
        year_rows = []
        for attempt in range(3):
            year_rows = fetch_year(year)
            if year_rows:
                break
            time.sleep(2 * (attempt + 1))
        if not year_rows:
            print(f"WARNING: NSDL returned no monthly rows for {year} after 3 attempts")
        rows.extend(year_rows)

    return pd.DataFrame(rows)


def fetch_mf_monthly() -> pd.DataFrame:
    """Domestic mutual-fund net equity investment (Rs crore) per month from
    Trendlyne (JS-rendered -> Playwright). Returns [month, mf_equity_cr]."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=UA["User-Agent"])
        page.goto(TRENDLYNE_URL, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(6000)
        html = page.content()
        browser.close()

    tables = pd.read_html(StringIO(html))
    # The data table is the one with a DATE column and FII/MF columns.
    table = next(
        (t for t in tables if len(t) > 12 and "DATE" in [str(c) for c in t.columns]),
        None,
    )
    if table is None:
        raise RuntimeError("Trendlyne FII/DII table not found -- page layout changed?")

    rows = []
    for _, row in table.iterrows():
        try:
            dt = datetime.strptime(str(row["DATE"]).strip(), "%b %Y")
        except ValueError:
            continue
        val = pd.to_numeric(row.get("MF Equity"), errors="coerce")
        if pd.isna(val):
            continue
        rows.append({"month": f"{dt.year}-{dt.month:02d}", "mf_equity_cr": float(val)})

    return pd.DataFrame(rows)


def build_flows(force: bool = False) -> pd.DataFrame:
    """Merged monthly [month, fpi_equity_cr, mf_equity_cr], cached."""
    if CACHE_PATH.exists() and not force:
        return pd.read_csv(CACHE_PATH)

    fpi = fetch_fpi_monthly()
    mf = fetch_mf_monthly()
    merged = fpi.merge(mf, on="month", how="outer").sort_values("month").reset_index(drop=True)

    # Drop the current (incomplete) calendar month -- both sources publish
    # partial month-to-date figures for it.
    this_month = datetime.now(timezone.utc).strftime("%Y-%m")
    merged = merged[merged["month"] < this_month].reset_index(drop=True)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    merged.to_csv(CACHE_PATH, index=False)
    return merged


def merge_flows(df: pd.DataFrame) -> pd.DataFrame:
    """Left-join FII/MF flows onto the SIP dataframe by month."""
    flows = build_flows()
    return df.merge(flows, on="month", how="left")


if __name__ == "__main__":
    df = build_flows(force=True)
    print(f"{len(df)} months, {df['month'].iloc[0]} -> {df['month'].iloc[-1]}")
    print(df.tail(15).to_string())
