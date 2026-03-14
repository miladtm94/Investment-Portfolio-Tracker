"""
Tax reporting router.

Australian users (jurisdiction="AU") get ATO-specific endpoints that use
the ATOTaxEngine — Australian financial year, CGT discount, ATO Schedule 3
format, AUD amounts throughout, and franking credits.

Non-AU users retain the original US-oriented endpoints.
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database import get_db
from shared.models import User
from shared.auth import get_current_user
from services.tax_engine import TaxEngine
from services.ato_tax_engine import ATOTaxEngine, au_financial_year, au_fy_bounds
from services.market_data_service import MarketDataService

logger = logging.getLogger(__name__)
router = APIRouter()

_CURRENT_FY = au_financial_year(datetime.utcnow())


# ─── Shared helpers ───────────────────────────────────────────────────────────

def _get_engine(db: AsyncSession) -> TaxEngine:
    return TaxEngine(db, MarketDataService())


def _get_ato_engine(db: AsyncSession) -> ATOTaxEngine:
    return ATOTaxEngine(db)


# ─── Response schemas ─────────────────────────────────────────────────────────

class TaxSummaryResponse(BaseModel):
    """Original US-oriented response (kept for non-AU jurisdictions)."""
    tax_year: int
    short_term_gains: float
    long_term_gains: float
    total_gains: float
    dividend_income: float
    staking_income: float
    estimated_short_term_tax: float
    estimated_long_term_tax: float
    estimated_total_tax: float
    unrealized_losses: float
    tlh_opportunity_count: int
    potential_tlh_savings: float


class ATOCGTEventResponse(BaseModel):
    symbol: str
    acquired: str         # ISO date
    disposed: str         # ISO date
    holding_days: int
    discount_eligible: bool
    cost_base_aud: float
    proceeds_aud: float
    gross_gain_aud: float     # positive = gain, negative = loss


class ATOTaxSummaryResponse(BaseModel):
    """Australian-specific tax summary in ATO Schedule 3 format."""
    financial_year: str                  # e.g. "2024-25"
    fy_end_year: int

    # CGT (ATO Item 18)
    gross_capital_gains_aud: float       # 18A: Total gains before discount
    capital_losses_current_aud: float    # Losses realised this FY
    net_capital_gain_aud: float          # 18H: Net amount after discount & losses
    capital_losses_carried_forward: float  # Losses to carry to next FY

    # Discount detail
    discount_gains_before_discount: float  # Gains eligible for 50% discount
    cgt_discount_applied: float            # The 50% reduction amount

    # Income
    dividend_income_aud: float
    franking_credits_aud: float
    staking_income_aud: float
    interest_income_aud: float

    # Tax estimates
    estimated_tax_on_income: float
    effective_tax_rate: float    # %

    # Events detail
    events: list[ATOCGTEventResponse]

    # TLH
    tlh_opportunity_count: int
    potential_tlh_savings_aud: float


class TLHOpportunityResponse(BaseModel):
    symbol: str
    name: str
    asset_class: str
    quantity: float
    cost_basis: float
    current_value: float
    unrealized_loss: float
    tax_savings: float
    holding_period_days: int


# ─── ATO endpoints ────────────────────────────────────────────────────────────

@router.get("/ato/summary", response_model=ATOTaxSummaryResponse)
async def get_ato_tax_summary(
    fy: int = Query(default=_CURRENT_FY, description="Australian financial year end (e.g. 2025 for FY2024-25)"),
    method: str = Query(default="FIFO", description="Cost base method: FIFO, LIFO, HIFO"),
    other_income_aud: float = Query(default=0.0, description="Other assessable income in AUD (salary, etc.)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Full ATO tax report for a given Australian financial year.

    Uses the ATOTaxEngine which implements ITAA 1997 Division 115 (CGT discount)
    and s102-5 (loss application order). All amounts in AUD.
    """
    engine = _get_ato_engine(db)
    report = await engine.compute_ato_report(
        user_id=str(current_user.id),
        fy_end_year=fy,
        cost_method=method,
        other_income_aud=other_income_aud,
    )

    fy_label = f"{fy - 1}-{str(fy)[2:]}"  # "2024-25"

    # TLH (reuse US engine — currency-agnostic enough for now)
    us_engine = _get_engine(db)
    tlh_opportunities, _ = await us_engine._find_tlh_opportunities(str(current_user.id))
    tlh_savings = sum(opp.get("tax_savings", 0) for opp in tlh_opportunities)

    events_resp = [
        ATOCGTEventResponse(
            symbol=e.symbol,
            acquired=e.acquired_at.date().isoformat(),
            disposed=e.disposed_at.date().isoformat(),
            holding_days=e.holding_days,
            discount_eligible=e.discount_eligible,
            cost_base_aud=float(e.cost_base_aud),
            proceeds_aud=float(e.proceeds_aud),
            gross_gain_aud=float(e.gross_gain_aud),
        )
        for e in report.cgt_events
    ]

    return ATOTaxSummaryResponse(
        financial_year=fy_label,
        fy_end_year=fy,
        gross_capital_gains_aud=float(report.gross_capital_gains_aud),
        capital_losses_current_aud=float(report.capital_losses_current_aud),
        net_capital_gain_aud=float(report.net_capital_gain_aud),
        capital_losses_carried_forward=float(report.capital_losses_carried_forward),
        discount_gains_before_discount=float(report.discount_gains_before_discount),
        cgt_discount_applied=float(report.cgt_discount_applied),
        dividend_income_aud=float(report.dividend_income_aud),
        franking_credits_aud=float(report.franking_credits_aud),
        staking_income_aud=float(report.staking_income_aud),
        interest_income_aud=float(report.interest_income_aud),
        estimated_tax_on_income=float(report.estimated_tax_on_income),
        effective_tax_rate=float(report.effective_tax_rate),
        events=events_resp,
        tlh_opportunity_count=len(tlh_opportunities),
        potential_tlh_savings_aud=float(tlh_savings),
    )


@router.get("/ato/cgt-events")
async def get_ato_cgt_events(
    fy: int = Query(default=_CURRENT_FY),
    method: str = Query(default="FIFO"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return CGT events for the ATO financial year — detailed lot-by-lot view."""
    engine = _get_ato_engine(db)
    report = await engine.compute_ato_report(str(current_user.id), fy, method)
    return {
        "financial_year": f"{fy - 1}-{str(fy)[2:]}",
        "events": [
            {
                "symbol": e.symbol,
                "acquired": e.acquired_at.date().isoformat(),
                "disposed": e.disposed_at.date().isoformat(),
                "holding_days": e.holding_days,
                "discount_eligible": e.discount_eligible,
                "cost_base_aud": float(e.cost_base_aud),
                "proceeds_aud": float(e.proceeds_aud),
                "gross_gain_aud": float(e.gross_gain_aud),
                "net_gain_aud": float(e.net_gain_aud),
                "capital_loss_aud": float(e.capital_loss_aud),
            }
            for e in report.cgt_events
        ],
    }


@router.get("/ato/schedule3")
async def get_ato_schedule3(
    fy: int = Query(default=_CURRENT_FY),
    method: str = Query(default="FIFO"),
    other_income_aud: float = Query(default=0.0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Return ATO Schedule 3 / Item 18 formatted output ready for myTax.

    Labels match ATO tax return fields (18A, 18B, 18V, 18H).
    """
    from services.ato_tax_engine import format_ato_schedule3
    engine = _get_ato_engine(db)
    report = await engine.compute_ato_report(str(current_user.id), fy, method, other_income_aud)
    return format_ato_schedule3(report)


@router.get("/ato/export/csv")
async def export_ato_csv(
    fy: int = Query(default=_CURRENT_FY),
    method: str = Query(default="FIFO"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Export CGT events as CSV for the ATO financial year."""
    engine = _get_ato_engine(db)
    report = await engine.compute_ato_report(str(current_user.id), fy, method)

    fy_label = f"{fy - 1}-{str(fy)[2:]}"
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([f"Capital Gains Report — Australian Financial Year {fy_label}"])
    writer.writerow([f"All amounts in AUD. Generated {datetime.utcnow().date().isoformat()}."])
    writer.writerow([])

    writer.writerow(["Summary (ATO Schedule 3)"])
    writer.writerow(["18A — Gross capital gains (before discount)", f"${float(report.gross_capital_gains_aud):,.2f}"])
    writer.writerow(["Capital losses applied this year",            f"${float(report.capital_losses_current_aud):,.2f}"])
    writer.writerow(["50% CGT discount applied",                    f"${float(report.cgt_discount_applied):,.2f}"])
    writer.writerow(["18H — Net capital gain",                      f"${float(report.net_capital_gain_aud):,.2f}"])
    writer.writerow(["18V — Capital losses carried forward",        f"${float(report.capital_losses_carried_forward):,.2f}"])
    writer.writerow([])
    writer.writerow(["Dividend income (AUD)",                       f"${float(report.dividend_income_aud):,.2f}"])
    writer.writerow(["Franking credits (AUD)",                      f"${float(report.franking_credits_aud):,.2f}"])
    writer.writerow(["Staking/crypto income (AUD)",                 f"${float(report.staking_income_aud):,.2f}"])
    writer.writerow([])

    writer.writerow(["CGT Events"])
    writer.writerow([
        "Symbol", "Acquired", "Disposed", "Holding Days", "Discount Eligible",
        "Cost Base (AUD)", "Proceeds (AUD)", "Gross Gain/Loss (AUD)", "Net Gain/Loss (AUD)",
    ])
    for e in report.cgt_events:
        writer.writerow([
            e.symbol,
            e.acquired_at.date().isoformat(),
            e.disposed_at.date().isoformat(),
            e.holding_days,
            "Yes" if e.discount_eligible else "No",
            f"${float(e.cost_base_aud):,.2f}",
            f"${float(e.proceeds_aud):,.2f}",
            f"${float(e.gross_gain_aud):,.2f}",
            f"${float(e.net_gain_aud):,.2f}",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=cgt_report_fy{fy_label}.csv"},
    )


# ─── Original US endpoints (kept for non-AU jurisdictions) ───────────────────

class TaxSummaryResponseUS(BaseModel):
    tax_year: int
    short_term_gains: float
    long_term_gains: float
    total_gains: float
    dividend_income: float
    staking_income: float
    estimated_short_term_tax: float
    estimated_long_term_tax: float
    estimated_total_tax: float
    unrealized_losses: float
    tlh_opportunity_count: int
    potential_tlh_savings: float


@router.get("/summary", response_model=TaxSummaryResponseUS)
async def get_tax_summary(
    tax_year: int = Query(default=datetime.now().year),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """US-oriented tax summary (calendar year). Australian users should use /ato/summary."""
    engine = _get_engine(db)
    report = await engine.compute_tax_summary(
        user_id=str(current_user.id),
        tax_year=tax_year,
        include_tlh=True,
    )
    tlh_savings = sum(opp.get("tax_savings", 0) for opp in report.tlh_opportunities)
    return TaxSummaryResponseUS(
        tax_year=report.tax_year,
        short_term_gains=float(report.short_term_gains),
        long_term_gains=float(report.long_term_gains),
        total_gains=float(report.total_gains),
        dividend_income=float(report.dividend_income),
        staking_income=float(report.staking_income),
        estimated_short_term_tax=float(report.estimated_short_term_tax),
        estimated_long_term_tax=float(report.estimated_long_term_tax),
        estimated_total_tax=float(report.estimated_total_tax),
        unrealized_losses=float(report.unrealized_losses),
        tlh_opportunity_count=len(report.tlh_opportunities),
        potential_tlh_savings=tlh_savings,
    )


@router.get("/tlh-opportunities", response_model=list[TLHOpportunityResponse])
async def get_tlh_opportunities(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Tax-loss harvesting opportunities sorted by potential savings."""
    engine = _get_engine(db)
    opportunities, _ = await engine._find_tlh_opportunities(str(current_user.id))
    return [
        TLHOpportunityResponse(
            symbol=opp["symbol"],
            name=opp["name"],
            asset_class=opp["asset_class"],
            quantity=opp["quantity"],
            cost_basis=opp["cost_basis"],
            current_value=opp["current_value"],
            unrealized_loss=opp["unrealized_loss"],
            tax_savings=opp["tax_savings"],
            holding_period_days=opp["holding_period_days"],
        )
        for opp in opportunities
    ]


@router.get("/realized-gains")
async def get_realized_gains(
    tax_year: int = Query(default=datetime.now().year),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Detailed realized gains (Form 8949 / non-AU use)."""
    engine = _get_engine(db)
    lots = await engine.generate_form_8949_data(str(current_user.id), tax_year)
    return {"tax_year": tax_year, "lots": lots}


@router.get("/export/csv")
async def export_tax_csv(
    tax_year: int = Query(default=datetime.now().year),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Export capital gains CSV (non-AU / US format)."""
    engine = _get_engine(db)
    report = await engine.compute_tax_summary(str(current_user.id), tax_year, include_tlh=False)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([f"Capital Gains Report — Tax Year {tax_year}"])
    writer.writerow([])
    writer.writerow(["Summary"])
    writer.writerow(["Short-Term Gains",  f"${float(report.short_term_gains):,.2f}"])
    writer.writerow(["Long-Term Gains",   f"${float(report.long_term_gains):,.2f}"])
    writer.writerow(["Total Gains",       f"${float(report.total_gains):,.2f}"])
    writer.writerow(["Dividend Income",   f"${float(report.dividend_income):,.2f}"])
    writer.writerow(["Staking Income",    f"${float(report.staking_income):,.2f}"])
    writer.writerow(["Est. Total Tax",    f"${float(report.estimated_total_tax):,.2f}"])
    writer.writerow([])
    writer.writerow(["Realized Lots (Form 8949)"])
    writer.writerow([
        "Symbol", "Acquired", "Sold", "Quantity", "Cost Basis",
        "Proceeds", "Gain/Loss", "Term", "Wash Sale",
    ])
    for lot in report.realized_lots:
        writer.writerow([
            lot["symbol"], lot["acquired_at"][:10], (lot.get("closed_at") or "")[:10],
            lot["quantity"], f"${lot['cost_basis']:,.2f}", f"${lot['proceeds']:,.2f}",
            f"${lot['gain_loss']:,.2f}", "Long" if lot["is_long_term"] else "Short",
            "Yes" if lot["is_wash_sale"] else "No",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=capital_gains_{tax_year}.csv"},
    )
