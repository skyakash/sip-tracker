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

Cached to data/processed/nifty_monthly.csv. `load_market()` (no network)
is what report/study/sentiment code should call; `fetch_market_monthly()`
is the network-refreshing path, incremental by default -- only re-pulls
the last INCREMENTAL_MONTHS_BACK months (new months + any late revision to
a recent bar) and merges over the cache, rather than re-downloading the
full 2007+ history every run.
"""

import pathlib
from datetime import datetime, timedelta, timezone

import pandas as pd

PROCESSED_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "processed"
CACHE_PATH = PROCESSED_DIR / "nifty_monthly.csv"

NIFTY_TICKER = "^NSEI"
VIX_TICKER = "^INDIAVIX"
INCREMENTAL_MONTHS_BACK = 6


def _monthly_series(raw: pd.DataFrame, ticker: str, field: str) -> pd.Series:
    col = raw[field][ticker] if isinstance(raw.columns, pd.MultiIndex) else raw[field]
    col.index = col.index.strftime("%Y-%m")
    return col


def _drop_current_month(df: pd.DataFrame) -> pd.DataFrame:
    # yfinance's last 1mo bar is a partial month-to-date bar.
    this_month = datetime.now(timezone.utc).strftime("%Y-%m")
    return df[df["month"] < this_month].reset_index(drop=True)


def _download(start: str) -> pd.DataFrame:
    import yfinance as yf

    nifty_raw = yf.download(NIFTY_TICKER, start=start, interval="1mo", progress=False)
    vix_raw = yf.download(VIX_TICKER, start=start, interval="1mo", progress=False)
    if nifty_raw.empty:
        return pd.DataFrame(columns=["month", "nifty_close", "india_vix"])

    nifty_close = _monthly_series(nifty_raw, NIFTY_TICKER, "Close")
    out = pd.DataFrame({"month": nifty_close.index, "nifty_close": nifty_close.values})

    if not vix_raw.empty:
        vix_close = _monthly_series(vix_raw, VIX_TICKER, "Close")
        out = out.merge(
            pd.DataFrame({"month": vix_close.index, "india_vix": vix_close.values}),
            on="month", how="left",
        )
    else:
        out["india_vix"] = None
    return _drop_current_month(out)


def fetch_market_monthly(start: str = "2007-01-01", force: bool = False) -> pd.DataFrame:
    """
    Returns [month, nifty_close, india_vix], month as 'YYYY-MM'.

    force=True (or no cache yet): full history from `start` (2007+).
    force=False (default): incremental -- re-pull only the last
    INCREMENTAL_MONTHS_BACK months and merge over the existing cache.
    """
    if not force and CACHE_PATH.exists():
        cached = pd.read_csv(CACHE_PATH)
        recent_start = (datetime.now(timezone.utc) - timedelta(days=31 * INCREMENTAL_MONTHS_BACK)).strftime("%Y-%m-%d")
        fresh = _download(recent_start)
        out = (
            pd.concat([cached[~cached["month"].isin(fresh["month"])], fresh])
            .sort_values("month")
            .reset_index(drop=True)
        )
    else:
        out = _download(start)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(CACHE_PATH, index=False)
    return out


def load_market() -> pd.DataFrame:
    """Read the cached Nifty/VIX series with no network access. Bootstraps
    with a full fetch if there's no cache yet."""
    if not CACHE_PATH.exists():
        return fetch_market_monthly(force=True)
    return pd.read_csv(CACHE_PATH)


# Backwards-compatible alias (older callers used this name for the fetch path).
def fetch_nifty_monthly(start: str = "2007-01-01", force: bool = False) -> pd.DataFrame:
    return fetch_market_monthly(start=start, force=force)


def merge_market_data(df: pd.DataFrame) -> pd.DataFrame:
    """Left-joins Nifty close, its MoM %, and India VIX onto the SIP
    dataframe by month. Reads from cache -- no network access."""
    market = load_market()
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
