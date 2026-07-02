"""
Nifty 50 monthly close, for market-context overlay -- the single most useful
external check on the SIP data: does systematic retail investing hold steady
through market drawdowns (the "SIP resilience" narrative), or move with it?

Cached to data/processed/nifty_monthly.csv so a normal `report` run doesn't
hit the network; re-fetch explicitly (fetch_nifty_monthly(force=True)) to
pick up new months or revisions.
"""

import pathlib

import pandas as pd

PROCESSED_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "processed"
CACHE_PATH = PROCESSED_DIR / "nifty_monthly.csv"

TICKER = "^NSEI"


def fetch_nifty_monthly(start: str = "2024-05-01", force: bool = False) -> pd.DataFrame:
    """Returns a DataFrame with columns [month, nifty_close], month as 'YYYY-MM'."""
    if CACHE_PATH.exists() and not force:
        return pd.read_csv(CACHE_PATH)

    import yfinance as yf

    raw = yf.download(TICKER, start=start, interval="1mo", progress=False)
    if raw.empty:
        return pd.DataFrame(columns=["month", "nifty_close"])

    close = raw["Close"][TICKER] if isinstance(raw.columns, pd.MultiIndex) else raw["Close"]
    out = pd.DataFrame({
        "month": close.index.strftime("%Y-%m"),
        "nifty_close": close.values,
    })
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(CACHE_PATH, index=False)
    return out


def merge_market_data(df: pd.DataFrame) -> pd.DataFrame:
    """Left-joins Nifty close (+ its own MoM %) onto the SIP dataframe by month."""
    nifty = fetch_nifty_monthly()
    if nifty.empty:
        df = df.copy()
        df["nifty_close"] = None
        df["nifty_mom_pct"] = None
        return df

    nifty = nifty.sort_values("month").reset_index(drop=True)
    nifty["nifty_mom_pct"] = nifty["nifty_close"].pct_change() * 100
    return df.merge(nifty, on="month", how="left")
