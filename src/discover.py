"""
Finds the PDF/Excel download links for each month from AMFI's listing pages.

UNTESTED against the live site (sandboxed environment couldn't reach amfiindia.com).
The two target pages, per AMFI's own site search results, are:

  - AMFI Monthly (has PDF + Excel per month):
    https://www.amfiindia.com/research-information/amfi-monthly

  - AMFI Monthly Note (narrative PDF, useful for qualitative context/fallback):
    https://www.amfiindia.com/otherdata/amfi-monthlynote

Both pages appear to list months as plain text/links like "May 2026 · PDF · Excel".
The exact HTML structure (whether links are in <a> tags with predictable hrefs,
or rendered client-side via JS) needs to be confirmed by actually fetching the
page — this is the first thing to validate in Claude Code.

If the page turns out to be JS-rendered (React/Next.js, which AMFI's site appears
to be based on asset paths like /_next/image), requests+BeautifulSoup won't see
the links and you'll need a headless browser (playwright) instead. Try the simple
approach first; escalate only if needed.
"""

import re
from dataclasses import dataclass
from typing import Optional

import requests
from bs4 import BeautifulSoup

AMFI_MONTHLY_URL = "https://www.amfiindia.com/research-information/amfi-monthly"
AMFI_MONTHLY_NOTE_URL = "https://www.amfiindia.com/otherdata/amfi-monthlynote"

HEADERS = {
    # AMFI, like many Indian govt/quasi-govt sites, sometimes blocks default
    # python-requests user agents. Pretend to be a normal browser.
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


@dataclass
class MonthLinks:
    month_label: str  # e.g. "May 2026"
    pdf_url: Optional[str] = None
    excel_url: Optional[str] = None


def _fetch(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def discover_amfi_monthly() -> list[MonthLinks]:
    """
    Parse the AMFI Monthly page into a list of (month, pdf_url, excel_url).

    NOTE: This is a best-effort first pass. Inspect the actual HTML
    (save it to a file and `view` it) before trusting this parser — the
    selectors below are guesses based on how the page rendered in search results,
    not a verified DOM structure.
    """
    html = _fetch(AMFI_MONTHLY_URL)
    soup = BeautifulSoup(html, "lxml")

    results: list[MonthLinks] = []

    # Heuristic: look for anchor tags whose href ends in .pdf or .xlsx/.xls,
    # and whose visible text or nearby text contains a month name.
    month_pattern = re.compile(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}",
        re.IGNORECASE,
    )

    current_month = None
    for tag in soup.find_all(["a", "span", "div", "li"]):
        text = tag.get_text(strip=True)
        m = month_pattern.search(text) if text else None
        if m:
            current_month = m.group(0)

        href = tag.get("href") if tag.name == "a" else None
        if href and current_month:
            if href.lower().endswith(".pdf"):
                entry = next((r for r in results if r.month_label == current_month), None)
                if not entry:
                    entry = MonthLinks(month_label=current_month)
                    results.append(entry)
                entry.pdf_url = href
            elif href.lower().endswith((".xlsx", ".xls")):
                entry = next((r for r in results if r.month_label == current_month), None)
                if not entry:
                    entry = MonthLinks(month_label=current_month)
                    results.append(entry)
                entry.excel_url = href

    return results


def discover_amfi_monthly_note() -> list[MonthLinks]:
    """Same idea as above but for the narrative monthly note (PDF only)."""
    html = _fetch(AMFI_MONTHLY_NOTE_URL)
    soup = BeautifulSoup(html, "lxml")

    results: list[MonthLinks] = []
    month_pattern = re.compile(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}",
        re.IGNORECASE,
    )

    current_month = None
    for tag in soup.find_all(["a", "span", "div", "li"]):
        text = tag.get_text(strip=True)
        m = month_pattern.search(text) if text else None
        if m:
            current_month = m.group(0)

        href = tag.get("href") if tag.name == "a" else None
        if href and current_month and href.lower().endswith(".pdf"):
            entry = next((r for r in results if r.month_label == current_month), None)
            if not entry:
                entry = MonthLinks(month_label=current_month)
                results.append(entry)
            entry.pdf_url = href

    return results


if __name__ == "__main__":
    # Quick manual smoke test: run `python -m src.discover` from the project root.
    print("AMFI Monthly page:")
    for link in discover_amfi_monthly():
        print(" ", link)

    print("\nAMFI Monthly Note page:")
    for link in discover_amfi_monthly_note():
        print(" ", link)
