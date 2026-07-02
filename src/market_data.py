"""
Market context series via yfinance, monthly:

- Nifty 50 close (^NSEI, history from Sep 2007) -- the single most useful
  external check on the SIP data: does systematic retail investing hold
  steady through market drawdowns (the "SIP resilience" narrative)?
- India VIX monthly mean (^INDIAVIX) -- volatility regime context.

History starts 2007 (not just the SIP window) because Study A conditions
Nifty forward returns on FII/domestic flows, whose series go back that far.
The current (incomplete) calendar month is dropped -- yfinance's last 1mo
bar is a partial month-to-date bar, which would poison forward-return math.

Cached to data/processed/nifty_monthly.csv so a normal `report` run doesn't
hit the network; re-fetch explicitly (fetch_market_monthly(force=True)) to
pick up new months.
"""

import pathlib
from datetime import datetime, timezone

import pandas as pd

PROCESSED_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "processed"
CACHE_PATH = PROCESSED_DIR / "nifty_monthly.csv"

NIFTY_TICKER = "^NSEI"
VIX_TICKER = "^INDIAVIX"


def _monthly_series(raw: pd.DataFrame, ticker: str, field: str) -> pd.Series:
    col = raw[field][ticker] if isinstance(raw.columns, pd.MultiIndex) else raw[field]
    col.index = col.index.strftime("%Y-%m")
    return col


def fetch_market_monthly(start: str = "2007-01-01", force: bool = False) -> pd.DataFrame:
    """Returns [month, nifty_close, india_vix], month as 'YYYY-MM'."""
    if CACHE_PATH.exists() and not force:
        return pd.read_csv(CACHE_PATH)

    import yfinance as yf

    nifty_raw = yf.download(NIFTY_TICKER, start=start, interval="1mo", progress=False)
    vix_raw = yf.download(VIX_TICKER, start=start, interval="1mo", progress=False)
    if nifty_raw.empty:
        return pd.DataFrame(columns=["month", "nifty_close", "india_vix"])

    nifty_close = _monthly_series(nifty_raw, NIFTY_TICKER, "Close")
    out = pd.DataFrame({"month": nifty_close.index, "nifty_close": nifty_close.values})

    if not vix_raw.empty:
        # Close of the monthly bar; a true intra-month mean needs daily data,
        # and month-end close is fine for regime context.
        vix_close = _monthly_series(vix_raw, VIX_TICKER, "Close")
        out = out.merge(
            pd.DataFrame({"month": vix_close.index, "india_vix": vix_close.values}),
            on="month", how="left",
        )
    else:
        out["india_vix"] = None

    # Drop the incomplete current month (partial month-to-date bar).
    this_month = datetime.now(timezone.utc).strftime("%Y-%m")
    out = out[out["month"] < this_month].reset_index(drop=True)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(CACHE_PATH, index=False)
    return out


# Backwards-compatible alias (report.py and older callers used this name).
def fetch_nifty_monthly(start: str = "2007-01-01", force: bool = False) -> pd.DataFrame:
    return fetch_market_monthly(start=start, force=force)


def merge_market_data(df: pd.DataFrame) -> pd.DataFrame:
    """Left-joins Nifty close, its MoM %, and India VIX onto the SIP
    dataframe by month."""
    market = fetch_market_monthly()
    if market.empty:
        df = df.copy()
        df["nifty_close"] = None
        df["nifty_mom_pct"] = None
        df["india_vix"] = None
        return df

    market = market.sort_values("month").reset_index(drop=True)
    market["nifty_mom_pct"] = market["nifty_close"].pct_change() * 100
    return df.merge(market, on="month", how="left")


if __name__ == "__main__":
    df = fetch_market_monthly(force=True)
    print(f"{len(df)} months, {df['month'].iloc[0]} -> {df['month'].iloc[-1]}")
    print(df.tail(6).to_string())
