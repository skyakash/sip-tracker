"""
Parses an AMFI Monthly Excel file into a MonthlyRecord.

CONFIRMED against a real file (May 2026): this Excel is AMFI's "Monthly
Cumulative Report" (sheet MCR_MonthlyReport: scheme count + folio count per
scheme category, e.g. "Large Cap Fund", "ELSS", broken into Open/Close-ended/
Interval; sheet NSR: new fund offers launched that month and funds mobilized).
It contains NO SIP-specific figures whatsoever -- no SIP contribution, SIP
AUM, SIP accounts, registrations, or stoppage data. LABEL_PATTERNS below is
therefore left as a best-effort scan (harmless if it matches nothing) rather
than force-fitted to labels that don't exist in this file; it will return an
all-None record for any AMFI Monthly Excel.

The actual SIP figures AMFI publishes live in the AMFI Monthly Note (see
src/parse_pdf.py), which is used as the primary source in main.py instead.
This module is kept for the Grand Total folio count (data/parse_excel::
debug_dump_labels can be used to spot-check that total against the Monthly
Note's folio figure) and in case AMFI ever adds SIP data to this file.
"""

import re
import pathlib
from datetime import datetime, timezone

import pandas as pd

from .models import MonthlyRecord

# Each key maps to a list of regex patterns that might appear as a row label
# in the Excel sheet. Add/adjust these once you've seen a real file.
LABEL_PATTERNS = {
    "sip_contribution_cr": [
        r"sip\s*contribution",
        r"amount\s*collected\s*through\s*sip",
        r"systematic\s*investment\s*plan.*contribution",
    ],
    "sip_aum_lakh_cr": [
        r"sip\s*aum",
        r"sip\s*assets?\s*under\s*management",
    ],
    "sip_aum_pct_of_total_aum": [
        r"sip.*%.*aum",
        r"sip\s*aum.*%\s*of\s*(total|industry)",
    ],
    "contributing_accounts_cr": [
        r"contributing\s*sip\s*accounts?",
        r"no\.?\s*of\s*sip\s*accounts?",
    ],
    "new_sips_registered_lakh": [
        r"new\s*sips?\s*registered",
        r"sips?\s*registered",
    ],
    "sips_discontinued_lakh": [
        r"sips?\s*discontinued",
        r"sips?\s*ceased",
        r"sips?\s*terminated",
    ],
    "total_industry_aum_lakh_cr": [
        r"total.*(industry)?\s*aum",
        r"average\s*aum",
    ],
    "total_folios_cr": [
        r"total\s*folios?",
    ],
    "net_equity_inflow_cr": [
        r"net\s*equity\s*(inflow|flow)",
    ],
}

_NUMERIC_RE = re.compile(r"-?\d[\d,]*\.?\d*")


def _extract_number(cell) -> float | None:
    if cell is None:
        return None
    if isinstance(cell, (int, float)):
        return float(cell)
    text = str(cell)
    match = _NUMERIC_RE.search(text.replace(",", ""))
    if match:
        try:
            return float(match.group(0))
        except ValueError:
            return None
    return None


def debug_dump_labels(xlsx_path: pathlib.Path) -> None:
    """Print every sheet's first two columns, to help you see real labels."""
    xls = pd.ExcelFile(xlsx_path)
    for sheet_name in xls.sheet_names:
        print(f"\n--- Sheet: {sheet_name} ---")
        df = xls.parse(sheet_name, header=None)
        for i, row in df.iterrows():
            first_cells = [c for c in row.tolist()[:4]]
            if any(pd.notna(c) for c in first_cells):
                print(i, first_cells)


def parse_excel(xlsx_path: pathlib.Path, month: str) -> MonthlyRecord:
    """
    month: ISO "YYYY-MM" for the month this file describes.
    """
    record = MonthlyRecord(
        month=month,
        source="amfi_excel",
        retrieved_at=datetime.now(timezone.utc).isoformat(),
    )

    xls = pd.ExcelFile(xlsx_path)
    for sheet_name in xls.sheet_names:
        df = xls.parse(sheet_name, header=None)
        for _, row in df.iterrows():
            cells = row.tolist()
            if not cells:
                continue
            label_cell = next((c for c in cells if isinstance(c, str) and c.strip()), None)
            if not label_cell:
                continue
            label_lower = label_cell.strip().lower()

            for field_name, patterns in LABEL_PATTERNS.items():
                if getattr(record, field_name) is not None:
                    continue  # already filled from an earlier match
                if any(re.search(p, label_lower) for p in patterns):
                    # take the first numeric value found after the label cell
                    for c in cells[1:]:
                        val = _extract_number(c)
                        if val is not None:
                            setattr(record, field_name, val)
                            break

    # Derive stoppage ratio if we have both halves
    if record.new_sips_registered_lakh and record.sips_discontinued_lakh:
        record.stoppage_ratio_pct = round(
            100 * record.sips_discontinued_lakh / record.new_sips_registered_lakh, 2
        )

    return record


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("Usage: python -m src.parse_excel <path_to_xlsx> <YYYY-MM>")
        sys.exit(1)
    path = pathlib.Path(sys.argv[1])
    rec = parse_excel(path, sys.argv[2])
    print(rec.to_dict())
