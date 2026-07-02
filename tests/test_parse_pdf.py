"""
Regression tests for the AMFI Monthly Note parser.

The LABEL patterns in src/parse_pdf.py are load-bearing regexes that were
tuned by hand against real notes and validated against bootstrap_seed.csv /
published figures. These tests pin the extracted values for four
representative months (each a different template/phrasing era) so future
pattern edits can't silently regress them.

Fixtures are the real cached PDFs in data/raw/ (gitignored). Tests skip if
a fixture is missing (e.g. fresh clone) -- run `python main.py fetch-month`
for the months below to materialize them.
"""

import pathlib

import pytest

from src.parse_pdf import parse_pdf

RAW_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "raw"

# month -> expected extracted fields (validated against bootstrap_seed.csv
# and AMFI's own tables during development)
EXPECTED = {
    "2026-05": {  # current template: pipe-delimited SIP trend table
        "sip_contribution_cr": 30954.0,
        "sip_aum_lakh_cr": 17.12,
        "sip_aum_pct_of_total_aum": 21.0,
        "contributing_accounts_cr": 9.64,
        "total_industry_aum_lakh_cr": 81.58,
        "total_folios_cr": 27.65,
        "net_equity_inflow_cr": 22907.0,
    },
    "2025-03": {  # prose variants: "34.53% y-o-y" must NOT be picked as AUM%
        "sip_contribution_cr": 25926.0,
        "sip_aum_lakh_cr": 13.35,
        "sip_aum_pct_of_total_aum": 20.3,
        "contributing_accounts_cr": 8.11,
        "total_industry_aum_lakh_cr": 65.74,
    },
    "2024-09": {  # "reached an all-time high of Rs 24,509 crore" phrasing
        "sip_contribution_cr": 24509.0,
        "sip_aum_lakh_cr": 13.82,
        "contributing_accounts_cr": 9.87,
        "total_industry_aum_lakh_cr": 67.09,
    },
    "2024-06": {  # oldest template: "at Rs 21,262 crore, monthly ... (SIP)"
        "sip_contribution_cr": 21262.0,
        "sip_aum_lakh_cr": 12.43,
        "sip_aum_pct_of_total_aum": 20.0,
        "contributing_accounts_cr": 8.99,
        "total_industry_aum_lakh_cr": 61.16,
    },
}


@pytest.mark.parametrize("month", sorted(EXPECTED))
def test_parse_pdf_extracts_expected_fields(month):
    pdf_path = RAW_DIR / f"{month}_pdf.pdf"
    if not pdf_path.exists():
        pytest.skip(f"{pdf_path.name} not cached -- run fetch-month first")

    record = parse_pdf(pdf_path, month)
    for field, expected in EXPECTED[month].items():
        actual = getattr(record, field)
        assert actual == pytest.approx(expected), (
            f"{month} {field}: expected {expected}, got {actual}"
        )


def test_stoppage_fields_stay_empty():
    """AMFI's Monthly Note doesn't publish discontinued-SIP counts; the
    parser must not hallucinate them from unrelated numbers."""
    pdf_path = RAW_DIR / "2026-05_pdf.pdf"
    if not pdf_path.exists():
        pytest.skip("fixture not cached")
    record = parse_pdf(pdf_path, "2026-05")
    assert record.sips_discontinued_lakh is None
    assert record.stoppage_ratio_pct is None
