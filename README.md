# AMFI SIP Tracker

Personal pipeline to track India's monthly SIP (Systematic Investment Plan) data
from AMFI's official releases, instead of relying on secondhand headlines that
round/revise numbers inconsistently.

## Why this exists

AMFI (Association of Mutual Funds in India) publishes two useful sources every month,
around the 8th-10th working day:

1. **AMFI Monthly** (`https://www.amfiindia.com/research-information/amfi-monthly`)
   — has a PDF *and* an Excel file for each month. The Excel is the best
   machine-readable source (no OCR / PDF-parsing needed).
2. **AMFI Monthly Note** (`https://www.amfiindia.com/otherdata/amfi-monthlynote`)
   — narrative PDF with commentary + the same core figures, useful as a fallback
   and for qualitative context (e.g. why a stoppage ratio spiked).
3. The `articles/mutual-fund` page also has a long-run "SIP contribution since
   FY2016-17" table, but it's embedded as an **image**, not text — not scriptable
   without OCR, so we don't rely on it here. If you want that history, request an
   OCR pass separately or manually key in a few anchor points.

## What this pipeline tracks per month

- SIP contribution (₹ crore)
- SIP AUM (₹ lakh crore) and SIP AUM as % of total industry AUM
- Number of contributing SIP accounts (crore)
- New SIPs registered / discontinued, and the derived stoppage ratio
- Total industry AUM, total folios
- Net equity inflows (for context — SIP vs. discretionary flow divergence)

## Project layout

```
amfi-sip-tracker/
├── README.md
├── requirements.txt
├── src/
│   ├── models.py        # MonthlyRecord dataclass — the schema for one month
│   ├── discover.py       # finds the download links on AMFI's listing pages
│   ├── fetch.py          # downloads Excel/PDF files to data/raw/
│   ├── parse_excel.py    # parses the AMFI Excel into a MonthlyRecord
│   ├── parse_pdf.py      # fallback: extracts key figures from the PDF monthly note
│   └── db.py              # reads/writes data/processed/sip_monthly.csv
├── data/
│   ├── raw/               # downloaded source PDFs -- committed to git (see below)
│   └── processed/
│       ├── sip_monthly.csv        # the clean output table, one row per month
│       └── bootstrap_seed.csv     # manually-sourced historical data (see below)
├── main.py                # CLI: fetch latest month / backfill a range / rebuild CSV
└── notebooks/              # for ad-hoc charting once you have a few months of data
```

## Data storage and fetching philosophy

**Everything is committed to the repo** -- both `data/raw/` (the source PDFs
downloaded from AMFI/NSDL) and `data/processed/` (parsed CSVs, charts, the
report). Nothing is gitignored under `data/`. The point is that the GitHub
repo itself is the full audit trail: you can reproduce every parsed number
from the exact source document that's checked in, without depending on
AMFI's site still having that file months or years later.

**Fetching is incremental, not a full re-scrape every time.** `main.py
fetch-month` already only ever downloads the one month you ask for
(`fetch.download()` skips re-downloading a cached file unless you pass
`--force`). The external data fetchers (`src/flows_fii.py`,
`src/macro.py`, `src/market_data.py`) work the same way now:

- `python main.py refresh-external` (default): re-pulls only the *recent*
  window from each source -- e.g. `flows_fii.py`'s NSDL scraper only
  re-walks the last 2 years of its year-by-year postback form instead of
  all the way back to 2007 -- and merges the fresh values over the
  existing cache. This catches new months plus any late revision to a
  recent figure without hammering the source site or re-downloading data
  that's already correct.
- `python main.py refresh-external --full`: full historical re-fetch of
  the same caches, for rebuilding from scratch or if you suspect the
  incremental merge has drifted from ground truth.

Every module that just *reads* cached data for display (`report.py`,
`verdict.py`, `sentiment.py`, `study_a.py`) calls a `load_*()` function
(`flows_fii.load_flows()`, `market_data.load_market()`,
`macro.load_gst()`) that never touches the network -- only the explicit
`refresh-external` command (or the scheduled workflow) does. This is why
`python main.py report` runs in ~1 second: it's reading CSVs, not
re-fetching Trendlyne/NSDL/yfinance every time you want to look at the
report.

## IMPORTANT — network access

This project was scaffolded in a sandbox that could **not** reach `amfiindia.com`
(it's outside the sandbox's allowlist), so none of the fetch/parse code has been
tested against live pages. The site structure (URL patterns, Excel column layout)
is inferred from search results and will very likely need small adjustments —
this is expected. Claude Code, running on your Mac mini with normal internet
access, should be able to fetch the real page, inspect the actual Excel/PDF
structure, and fix up `parse_excel.py` / `discover.py` in a couple of iterations.

Suggested first session in Claude Code:
1. `pip install -r requirements.txt`
2. Ask Claude Code to run `python main.py discover` and show you what links it finds
3. Ask it to fetch one month's Excel file and print its raw structure
   (sheet names, header rows) so `parse_excel.py` can be corrected against reality
4. Then backfill historical months and validate against `data/processed/bootstrap_seed.csv`

## Bootstrap seed data

`data/processed/bootstrap_seed.csv` has ~15 months of data points (Jan 2025 –
May 2026) that were manually reconstructed from AMFI figures as reported across
financial news/analytics sites during earlier research. These are **secondary-source
values** (some outlets round or revise slightly) — use them as a sanity check /
placeholder for charting, but treat anything scraped directly from AMFI's own
Excel/PDF as the source of truth once the scraper is working, and reconcile
differences in favor of AMFI.

## Known data quirks to encode into the parser (from earlier analysis)

- **Jan–Apr 2025 stoppage ratio is unreliable**: AMFI purged ~1.43 crore dormant
  SIP folios in this window, spiking the ratio to ~353% in April 2025. This is a
  data clean-up artifact, not investor behavior — flag or exclude this window in
  any trend analysis.
- **March every year**: stoppage ratio tends to spike (ELSS 3-year lock-ins from
  Section 80C completing, annual mandates lapsing at fiscal year-end).
- **April every year**: SIP contributions tend to jump (fresh mandates set up for
  the new financial year).
- Figures get **revised** — AMFI has restated legacy data before (e.g. a 14 May
  2025 revision). Consider keeping a `retrieved_at` timestamp per row so you can
  tell when a historical row changed on a re-fetch.

## Browser automation (Playwright)

`playwright` is in requirements.txt for one-off investigation of JS-rendered
pages that plain `requests`/`curl` can't see (used to confirm AMFI's
`research-information/amfi-data` page is just a UI wrapper around the same
Monthly/Quarterly Cumulative Report data already covered by `discover.py`,
not a separate SIP data source). It isn't wired into the actual pipeline —
`discover.py`/`fetch.py` still use plain `requests` since AMFI's real report
pages are server-rendered.

`pip install -r requirements.txt` installs the Python package but not the
browser binary; run `python -m playwright install chromium` once after that
if you need it for a future investigation.
