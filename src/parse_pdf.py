"""
Parser for the AMFI Monthly Note PDF (narrative commentary + figures).

This is the PRIMARY source for SIP-specific figures, not a fallback: AMFI's
"AMFI Monthly" Excel/PDF (see discover.py / parse_excel.py) turns out to be
the Monthly Cumulative Report (scheme/folio counts by category) and contains
no SIP contribution, SIP AUM, or SIP account data at all. The Monthly Note is
the only place AMFI itself publishes SIP contribution, SIP AUM, SIP AUM % of
industry AUM, and contributing SIP accounts, both narratively and in a
trailing 6-month "SIP trend" table.

Known gap, confirmed by reading real notes (Apr 2025, Jul 2025, Feb/Mar/May
2026): AMFI's Monthly Note does NOT reliably publish "new SIPs registered" /
"SIPs discontinued" / stoppage ratio. "New SIPs registered" appears in some
months' narrative text (e.g. Feb 2026) but not others (Mar/Apr/May 2026,
Apr 2025); "discontinued" never appears in any note we've checked. Financial
news sites that report a stoppage ratio appear to source it from AMFI data
that isn't in this public PDF/Excel pair (possibly a paid CRISIL/AMFI feed).
So: new_sips_registered_lakh is extracted opportunistically and will often be
None; sips_discontinued_lakh and stoppage_ratio_pct are not derivable from
this source and are left for the bootstrap/secondary-source data to cover.

Uses pymupdf4llm to get markdown, then regexes out figures. Patterns match on
row/sentence structure that's held steady across the samples checked, but
AMFI does vary phrasing month to month -- treat regex misses as expected, not
bugs, and extend the patterns as new phrasings are encountered.
"""

import re
import pathlib
from datetime import datetime, timezone

from .models import MonthlyRecord

try:
    import pymupdf4llm
except ImportError:
    pymupdf4llm = None


_NUM = r"([\d,]+(?:\.\d+)?)"

# Ordered lists of regex patterns (first match wins) against the lowercased,
# newline-collapsed markdown text. Row-label patterns are used first (from the
# "SIP trend" table, which is structurally consistent even when column headers
# change), then narrative sentence patterns as a fallback for older layouts.
PATTERNS = {
    "sip_contribution_cr": [
        # SIP trend table row: "|SIP monthly contribution (crore)|30,954|31,115|...|"
        rf"sip\s*monthly\s*contributions?\s*\(?in?\s*crores?\)?\|{_NUM}",
        rf"sip\s*monthly\s*contributions?\s*\(crore\)\|{_NUM}",
        # Narrative: "SIP monthly contributions saw inflows of Rs 30,954 crore"
        rf"sip\s*(?:monthly\s*)?contributions?\s*(?:saw\s*inflows?\s*of|stood\s*at|of|at)\s*rs\.?\s*{_NUM}\s*crore",
        # Older phrasing: "at Rs 21,262 crore, monthly systematic investment
        # plan (SIP) contributions crossed the Rs 21,000 crore mark"
        rf"at\s*rs\.?\s*{_NUM}\s*crore,?\s*monthly\s*systematic\s*investment\s*plan\s*\(sip\)\s*contributions?",
        # "SIP inflows touched a new all-time high of Rs 29,361 crore"
        rf"sip\s*inflows?\s*(?:touched|reached|hit)\s*(?:a\s*)?(?:new\s*)?(?:all-time\s*high\s*of|record\s*high\s*of)\s*rs\.?\s*{_NUM}\s*crore",
        # "monthly SIP contributions reached an all-time high of Rs 24,509 crore"
        rf"contributions?\s*reached\s*an\s*all-time\s*high\s*of\s*rs\.?\s*{_NUM}\s*crore",
        # "SIP flows remained steadfast at Rs. 25,320" / "holding steady at Rs 25,320 crore"
        rf"sip\s*(?:contributions?|flows?)\s*(?:remained\s*steadfast\s*at|holding\s*steady\s*at|held\s*steady\s*at)\s*rs\.?\s*{_NUM}\s*crore?",
        # "SIP contributions, which totalled Rs 26,459 crore" / "totalling Rs 26,400 crore for the month"
        rf"sip\s*contributions?.{{0,40}}?totall(?:ed|ing)\s*rs\.?\s*{_NUM}\s*crore",
    ],
    "sip_aum_lakh_cr": [
        rf"sip\s*assets?\s*\(rs\.?\s*in?\s*lakh\s*crore\)\|{_NUM}",
        rf"sip\s*assets?\s*\(rs\s*lakh\s*crore\)\|{_NUM}",
        rf"sip\s*assets?\s*(?:increased|rose|declined|grew|remained).{{0,40}}?rs\.?\s*{_NUM}\s*lakh\s*crore",
        rf"sip\s*assets?\s*.{{0,20}}?rs\.?\s*{_NUM}\s*lakh\s*crore",
    ],
    "sip_aum_pct_of_total_aum": [
        # SIP trend table row, pipe- or space-delimited depending on how the
        # PDF's table extracted, and "as % of" or "as a % of" depending on
        # which year's template AMFI used:
        # "|SIP assets as a % of industry assets|20.3|...|" / "sip assets as % of indus[try assets] 20.1 20.2..."
        rf"sip\s*assets?\s*as\s*(?:a\s*)?%?\s*(?:of\s*industry\s*assets|percentage\s*of\s*industry\s*(?:\s*<br>)?\s*assets)\|{_NUM}",
        rf"sip\s*assets?\s*as\s*(?:a\s*)?%?\s*of\s*industry\s*assets\s*{_NUM}",
        rf"constituting\s*~?{_NUM}\s*%\s*of\s*the\s*industry'?s?\s*aum",
        # "SIP assets ... accounting for ~19.9% of the industry's assets"
        rf"accounting\s*for\s*~?{_NUM}\s*%\s*of\s*the\s*industry'?s?\s*assets",
        # "SIP assets as a percentage of industry assets were around 20%"
        rf"sip\s*assets?\s*as\s*a\s*percentage\s*of\s*industry\s*assets\s*(?:were|was)\s*around\s*{_NUM}\s*%",
    ],
    "contributing_accounts_cr": [
        rf"(?:number|no\.?)\s*of\s*contributing\s*(?:\(active\)\s*)?sip\s*accounts?\s*(?:\(crore\))?\|{_NUM}",
        rf"(?:count|number)\s*of\s*contributing\s*\(active\)\s*sip\s*accounts?\s*remained\s*steady\s*at\s*{_NUM}\s*crore",
        rf"contributing\s*sip\s*accounts?\s*.{{0,40}}?{_NUM}\s*crore",
        # "SIP accounts totalled 8.99 crore" / "SIP accounts crossed 9.61 crore"
        rf"sip\s*accounts?\s*(?:totalled|crossed)\s*{_NUM}\s*crore",
        # Bare SIP trend table row (no "no. of contributing" prefix), pipe-
        # or space-delimited depending on how the PDF's table extracted:
        # "|SIP accounts (crore)|9.87|..." / "sip accounts (crore) 9.87 9.61..."
        rf"sip\s*accounts?\s*\(crore\)\|{_NUM}",
        rf"sip\s*accounts?\s*\(crore\)\s*{_NUM}",
    ],
    "new_sips_registered_lakh": [
        rf"{_NUM}\s*lakh\s*new\s*sips?\s*(?:were\s*)?registered",
        rf"new\s*sips?\s*registered.{{0,20}}?{_NUM}\s*lakh",
    ],
    "total_folios_cr": [
        rf"taking\s*the\s*total\s*(?:count\s*)?to\s*{_NUM}\s*crore",
        rf"taking\s*the\s*total\s*to\s*{_NUM}\s*crore",
        # "bringing the overall/total folio count to 22.50 crore"
        rf"(?:bringing|taking)\s*the\s*(?:overall|total)\s*folio\s*count\s*to\s*{_NUM}\s*crore",
    ],
    "net_equity_inflow_cr": [
        rf"equity\s*inflows?\s*came\s*in\s*at\s*rs\.?\s*{_NUM}\s*crore",
        rf"equity\s*fund[s]?\s*category\s*(?:logged|saw|witnessed).{{0,60}}?(?:totalling|amounting\s*to)\s*rs\.?\s*{_NUM}\s*crore",
        rf"category\s*witnessed\s*net\s*inflow\s*of\s*rs\.?\s*{_NUM}\s*crore",
        rf"equity\s*funds?\s*(?:recorded|saw).{{0,80}}?(?:highest-ever\s*)?(?:monthly\s*)?inflows?,?\s*totalling\s*rs\.?\s*{_NUM}\s*crore",
    ],
}


def _clean_text(raw: str) -> str:
    # Collapse markdown table/line breaks and lowercase for matching, but
    # keep digits/commas/periods intact.
    text = raw.replace("<br>", " ")
    text = re.sub(r"\s+", " ", text)
    text = text.replace("’", "'")  # curly apostrophe -> straight
    return text.lower()


_AUM_NUM_RE = re.compile(r"rs\.?\s*([\d,]+\.?\d*)\s*lakh\s*crore")
_AUM_EXCLUDE_WORDS = ("equity", "debt fund", "hybrid", "sip ", "income/debt", "solution")


_PCT_RE = re.compile(r"~?([\d.]+)\s*%")
_PCT_OF_AUM_TAIL_RE = re.compile(r"^\s*of\b.{0,40}?(aum|assets)")


def _find_sip_aum_pct(text: str) -> float | None:
    """
    We want "SIP assets as a % of industry/total AUM", not e.g. "flows into
    SIPs grew 34.53% on-year" (a YoY growth rate) or "~33% of the total AUM"
    for an unrelated scheme category -- both of which contain "sip"/"aum"
    somewhere nearby and previously caused false matches. Require "sip" shortly
    before the percentage AND the percentage to be immediately followed by
    "of ... aum/assets" (the proportion phrasing), not just "aum" anywhere
    in a fixed window.
    """
    for m in _PCT_RE.finditer(text):
        ctx = text[max(0, m.start() - 100):m.start()]
        tail = text[m.end():m.end() + 60]
        if "sip" in ctx and _PCT_OF_AUM_TAIL_RE.search(tail):
            return float(m.group(1))
    return None


def _find_total_industry_aum(text: str) -> float | None:
    """
    Total industry AUM is stated in varying sentence shapes ("remained
    largely steady at Rs X lakh crore", "grew N% from Rs A ... to Rs B lakh
    crore"), and the same paragraph often also states equity/debt/SIP AUM in
    lakh crore nearby. A single regex kept mismatching (wrong sub-category,
    or the "from" value instead of the current month's "to" value), so this
    scans all "Rs N lakh crore" occurrences and picks the one anchored to
    "industry" that isn't a "from" (comparison) value.
    """
    candidates = []
    for m in _AUM_NUM_RE.finditer(text):
        start = max(0, m.start() - 100)
        ctx = text[start:m.start()]
        if "industry" in ctx and not any(w in ctx[-60:] for w in _AUM_EXCLUDE_WORDS):
            preceding_word = ctx.strip().split()[-1] if ctx.strip() else ""
            candidates.append((preceding_word, float(m.group(1).replace(",", ""))))
    for word, val in candidates:
        if word != "from":
            return val
    return candidates[0][1] if candidates else None


_FLOW_RE = re.compile(
    r"(?:net\s*)?(inflows?|outflows?)(?:\s*of|,?\s*totalling|\s*amounting\s*to)?\s*rs\.?\s*([\d,]+\.?\d*)\s*crore"
)


_ALL_CATEGORY_WORDS = ("equity fund", "debt fund", "hybrid fund", "sip ")


def _find_category_net_flow(text: str, keywords: tuple[str, ...]) -> float | None:
    """
    Category-wise (debt/hybrid) net flow phrasing varies a lot more than the
    SIP-specific figures -- "net outflows of Rs X crore from debt funds",
    "hybrid fund net inflows of Rs X crore", "net positive inflows of Rs X
    crore" attributed to debt-oriented schemes elsewhere in the paragraph.
    A summary bullet often mentions multiple categories in one sentence
    ("led by debt funds (60%) ... equity funds ... record inflows of Rs
    42,702 crore" -- an equity figure, not debt's, despite "debt fund"
    appearing 100+ chars earlier), so this requires the category keyword in
    the *near* context and no other category name in between.
    Sign: positive = net inflow, negative = net outflow.
    """
    other_categories = [w for w in _ALL_CATEGORY_WORDS if not any(w in k or k in w for k in keywords)]
    for m in _FLOW_RE.finditer(text):
        ctx = text[max(0, m.start() - 150):m.start()]
        near_ctx = ctx[-80:]
        if any(k in ctx for k in keywords) and not any(w in near_ctx for w in other_categories):
            val = float(m.group(2).replace(",", ""))
            return -val if "out" in m.group(1) else val
    return None


def debug_dump_text(pdf_path: pathlib.Path) -> str:
    """Return the cleaned, lowercased text used for matching -- handy for
    building/checking new regex patterns against a real note."""
    if pymupdf4llm is None:
        raise RuntimeError("pymupdf4llm not installed -- pip install pymupdf4llm")
    raw = pymupdf4llm.to_markdown(str(pdf_path))
    return _clean_text(raw)


def parse_pdf(pdf_path: pathlib.Path, month: str) -> MonthlyRecord:
    if pymupdf4llm is None:
        raise RuntimeError("pymupdf4llm not installed -- pip install pymupdf4llm")

    raw = pymupdf4llm.to_markdown(str(pdf_path))
    text = _clean_text(raw)

    record = MonthlyRecord(
        month=month,
        source="amfi_pdf",
        retrieved_at=datetime.now(timezone.utc).isoformat(),
    )

    for field_name, patterns in PATTERNS.items():
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                value = float(match.group(1).replace(",", ""))
                setattr(record, field_name, value)
                break

    record.total_industry_aum_lakh_cr = _find_total_industry_aum(text)
    if record.sip_aum_pct_of_total_aum is None:
        record.sip_aum_pct_of_total_aum = _find_sip_aum_pct(text)
    record.net_debt_inflow_cr = _find_category_net_flow(
        text, ("debt fund", "debt-oriented", "debt category")
    )
    record.net_hybrid_inflow_cr = _find_category_net_flow(
        text, ("hybrid fund", "hybrid category")
    )

    notes = []
    if record.new_sips_registered_lakh is None:
        notes.append("new_sips_registered not stated in this month's note")
    notes.append(
        "sips_discontinued/stoppage_ratio not published in AMFI Monthly Note; "
        "not derivable from this source"
    )
    record.notes = "; ".join(notes)

    return record


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("Usage: python -m src.parse_pdf <path_to_pdf> <YYYY-MM>")
        sys.exit(1)
    path = pathlib.Path(sys.argv[1])
    rec = parse_pdf(path, sys.argv[2])
    print(rec.to_dict())
