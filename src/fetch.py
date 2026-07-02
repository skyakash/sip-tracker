"""
Downloads a file (PDF or Excel) to data/raw/, named predictably by month + type.
"""

import pathlib

import requests

from .discover import HEADERS

RAW_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "raw"


def download(url: str, month_label: str, kind: str, force: bool = False) -> pathlib.Path:
    """
    kind: "pdf" | "excel"
    month_label: e.g. "May 2026" -> normalized to "2026-05" for the filename
    force: re-download even if cached (AMFI restates figures occasionally)
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    normalized = _normalize_month(month_label)
    if kind == "pdf":
        ext = "pdf"
    else:
        # AMFI serves these as legacy .xls (OLE2) regardless of any .xlsx
        # elsewhere in the pipeline's naming; keep the real extension so
        # pandas picks the right engine (xlrd for .xls, openpyxl for .xlsx).
        ext = url.rsplit(".", 1)[-1].lower()
    dest = RAW_DIR / f"{normalized}_{kind}.{ext}"

    if dest.exists():
        if not force:
            return dest  # already have it; use force=True to re-download
        dest.unlink()

    resp = requests.get(url, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    return dest


def _normalize_month(month_label: str) -> str:
    """'May 2026' -> '2026-05'"""
    months = {
        "january": "01", "february": "02", "march": "03", "april": "04",
        "may": "05", "june": "06", "july": "07", "august": "08",
        "september": "09", "october": "10", "november": "11", "december": "12",
    }
    name, year = month_label.strip().split()
    return f"{year}-{months[name.lower()]}"
