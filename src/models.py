"""
Schema for one month of AMFI SIP data.

Kept deliberately flat (one row per month) so it maps 1:1 onto a CSV row and is
trivial to load into pandas for charting later.
"""

from dataclasses import dataclass, fields, asdict
from typing import Optional


@dataclass
class MonthlyRecord:
    # Identity
    month: str  # e.g. "2026-05" (ISO year-month, always the calendar month the data describes)
    source: str  # "amfi_excel" | "amfi_pdf" | "bootstrap_seed"
    retrieved_at: Optional[str] = None  # ISO timestamp of when we pulled this, for revision tracking

    # Core SIP figures
    sip_contribution_cr: Optional[float] = None       # ₹ crore, that month's SIP inflow
    sip_aum_lakh_cr: Optional[float] = None            # ₹ lakh crore, SIP AUM at month end
    sip_aum_pct_of_total_aum: Optional[float] = None   # SIP AUM as % of total industry AUM
    contributing_accounts_cr: Optional[float] = None   # crore, number of active contributing SIP accounts

    # Registration / churn (units: lakh, i.e. 100,000s — matches how AMFI usually reports these)
    new_sips_registered_lakh: Optional[float] = None
    sips_discontinued_lakh: Optional[float] = None
    stoppage_ratio_pct: Optional[float] = None          # discontinued / new_registered * 100

    # Wider context (helps interpret SIP numbers, not SIP-specific)
    total_industry_aum_lakh_cr: Optional[float] = None
    total_folios_cr: Optional[float] = None
    net_equity_inflow_cr: Optional[float] = None
    net_debt_inflow_cr: Optional[float] = None    # ₹ crore, signed (negative = net outflow)
    net_hybrid_inflow_cr: Optional[float] = None   # ₹ crore, signed (negative = net outflow)

    # Free-text notes worth keeping (e.g. "AMFI folio reconciliation event")
    notes: Optional[str] = None

    @staticmethod
    def field_names():
        return [f.name for f in fields(MonthlyRecord)]

    def to_dict(self):
        return asdict(self)
