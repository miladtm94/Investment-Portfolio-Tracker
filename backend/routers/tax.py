"""Australian investment tax workpapers and legacy tax endpoints."""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.ato_tax_engine import (
    ATOTaxEngine,
    SUPPORTED_METHODS,
    au_financial_year,
    format_ato_schedule3,
)
from services.market_data_service import MarketDataService
from services.tax_engine import TaxEngine
from shared.auth import get_current_user
from shared.database import get_db
from shared.models import TaxYearSettings, User

router = APIRouter()
_CURRENT_FY = au_financial_year(datetime.now(timezone.utc))


class TaxSettingsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    other_income_aud: float = Field(0, ge=0)
    other_deductions_aud: float = Field(0, ge=0)
    investment_deductions_aud: float = Field(0, ge=0)
    prior_year_capital_losses_aud: float = Field(0, ge=0)
    tax_withheld_aud: float = Field(0, ge=0)
    other_tax_offsets_aud: float = Field(0, ge=0)
    other_foreign_tax_offsets_aud: float = Field(0, ge=0)
    medicare_levy_exemption_pct: float = Field(0, ge=0, le=100)
    resident_full_year: bool = True
    franking_credits_eligible: bool = True

    other_franked_dividends_aud: float = Field(0, ge=0)
    other_unfranked_dividends_aud: float = Field(0, ge=0)
    other_foreign_dividends_aud: float = Field(0, ge=0)
    other_franking_credits_aud: float = Field(0, ge=0)
    foreign_tax_paid_aud: float = Field(0, ge=0)
    other_interest_income_aud: float = Field(0, ge=0)
    other_staking_income_aud: float = Field(0, ge=0)
    other_non_discount_capital_gains_aud: float = Field(0, ge=0)
    other_discount_capital_gains_aud: float = Field(0, ge=0)
    other_capital_losses_aud: float = Field(0, ge=0)
    notes: Optional[str] = Field(None, max_length=4000)


SETTINGS_FIELDS = tuple(TaxSettingsPayload.model_fields)


def _settings_dict(row: Optional[TaxYearSettings]) -> dict[str, Any]:
    if not row:
        return TaxSettingsPayload().model_dump()
    result: dict[str, Any] = {}
    for key in SETTINGS_FIELDS:
        value = getattr(row, key)
        result[key] = float(value) if isinstance(value, Decimal) else value
    return result


async def _get_settings(db: AsyncSession, user_id: str, fy: int) -> Optional[TaxYearSettings]:
    return (
        await db.execute(
            select(TaxYearSettings).where(
                TaxYearSettings.user_id == user_id,
                TaxYearSettings.fy_end_year == fy,
            )
        )
    ).scalar_one_or_none()


def _engine(db: AsyncSession) -> ATOTaxEngine:
    return ATOTaxEngine(db)


async def _compute_report(db: AsyncSession, user_id: str, fy: int, method: str):
    settings = _settings_dict(await _get_settings(db, user_id, fy))
    engine = _engine(db)
    try:
        return await engine.compute_ato_report(user_id, fy, _method(method), settings)
    finally:
        await engine.close()


def _method(value: str) -> str:
    method = value.upper()
    if method not in SUPPORTED_METHODS:
        raise HTTPException(422, f"method must be one of {', '.join(sorted(SUPPORTED_METHODS))}")
    return method


def _event_dict(event: Any) -> dict[str, Any]:
    return {
        "symbol": event.symbol,
        "name": event.name,
        "asset_class": event.asset_class,
        "account_name": event.account_name,
        "acquired": event.acquired_at.date().isoformat(),
        "disposed": event.disposed_at.date().isoformat(),
        "holding_days": event.holding_days,
        "discount_eligible": event.discount_eligible,
        "quantity": float(event.quantity),
        "cost_base_aud": float(event.cost_base_aud),
        "proceeds_aud": float(event.proceeds_aud),
        "gross_gain_aud": float(event.gross_gain_aud),
        "capital_loss_aud": float(event.capital_loss_aud),
        "opening_transaction_id": event.opening_transaction_id,
        "closing_transaction_id": event.closing_transaction_id,
    }


def _report_dict(report: Any) -> dict[str, Any]:
    numeric = (
        "gross_capital_gains_aud", "capital_losses_current_aud", "capital_losses_prior_aud",
        "capital_losses_applied_aud", "discount_gains_before_discount", "cgt_discount_applied",
        "net_capital_gain_aud", "capital_losses_carried_forward", "dividend_income_aud",
        "franked_dividends_aud", "unfranked_dividends_aud", "foreign_dividends_aud",
        "assessable_dividend_income_aud", "franking_credits_aud", "foreign_tax_paid_aud",
        "staking_income_aud", "interest_income_aud", "investment_deductions_aud",
        "other_income_aud", "other_deductions_aud", "total_taxable_income_aud",
        "basic_income_tax_aud", "lito_aud", "medicare_levy_aud", "franking_tax_offset_aud",
        "foreign_tax_offsets_aud", "other_tax_offsets_aud", "tax_withheld_aud",
        "net_tax_before_withholding_aud", "estimated_tax_payable_aud",
        "estimated_refund_aud", "estimated_tax_on_investments_aud", "effective_tax_rate",
    )
    result = {name: float(getattr(report, name)) for name in numeric}
    result.update({
        "financial_year": f"{report.financial_year - 1}-{str(report.financial_year)[-2:]}",
        "fy_end_year": report.financial_year,
        "cost_method": report.cost_method,
        "events": [_event_dict(event) for event in report.cgt_events],
        "warnings": report.warnings,
        "optimization": report.optimization,
        "rules": report.rules,
    })
    return result


@router.get("/ato/settings")
async def get_ato_settings(
    fy: int = Query(default=_CURRENT_FY, ge=2000, le=2100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await _get_settings(db, str(current_user.id), fy)
    return {"fy_end_year": fy, "saved": row is not None, **_settings_dict(row)}


@router.put("/ato/settings")
async def save_ato_settings(
    body: TaxSettingsPayload,
    fy: int = Query(default=_CURRENT_FY, ge=2000, le=2100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await _get_settings(db, str(current_user.id), fy)
    if row is None:
        row = TaxYearSettings(user_id=str(current_user.id), fy_end_year=fy)
        db.add(row)
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    await db.commit()
    await db.refresh(row)
    return {"fy_end_year": fy, "saved": True, **_settings_dict(row)}


@router.get("/ato/summary")
async def get_ato_tax_summary(
    fy: int = Query(default=_CURRENT_FY, ge=2000, le=2100),
    method: str = Query(default="FIFO"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    report = await _compute_report(db, str(current_user.id), fy, method)
    return _report_dict(report)


@router.get("/ato/cgt-events")
async def get_ato_cgt_events(
    fy: int = Query(default=_CURRENT_FY, ge=2000, le=2100),
    method: str = Query(default="FIFO"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    report = await _compute_report(db, str(current_user.id), fy, method)
    return {"financial_year": report.fy_label, "cost_method": report.cost_method,
            "events": [_event_dict(event) for event in report.cgt_events], "warnings": report.warnings}


@router.get("/ato/schedule3")
async def get_ato_schedule3(
    fy: int = Query(default=_CURRENT_FY, ge=2000, le=2100),
    method: str = Query(default="FIFO"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    report = await _compute_report(db, str(current_user.id), fy, method)
    return format_ato_schedule3(report)


@router.get("/ato/export/csv")
async def export_ato_csv(
    fy: int = Query(default=_CURRENT_FY, ge=2000, le=2100),
    method: str = Query(default="FIFO"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    report = await _compute_report(db, str(current_user.id), fy, method)
    schedule = format_ato_schedule3(report)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Australian Investment Tax Workpaper", report.fy_label])
    writer.writerow(["Generated", datetime.now(timezone.utc).isoformat()])
    writer.writerow(["Parcel method", report.cost_method])
    writer.writerow([])
    writer.writerow(["Tax return labels"])
    for key, value in schedule.items():
        if key not in {"warnings"}:
            writer.writerow([key, value])
    writer.writerow([])
    writer.writerow(["Tax estimate"])
    for label, value in (
        ("Total taxable income", report.total_taxable_income_aud),
        ("Basic income tax", report.basic_income_tax_aud),
        ("Low income tax offset", report.lito_aud),
        ("Medicare levy", report.medicare_levy_aud),
        ("Franking tax offset", report.franking_tax_offset_aud),
        ("Foreign income tax offsets", report.foreign_tax_offsets_aud),
        ("Other tax offsets", report.other_tax_offsets_aud),
        ("Tax withheld", report.tax_withheld_aud),
        ("Estimated amount due", report.estimated_tax_payable_aud),
        ("Estimated refund", report.estimated_refund_aud),
    ):
        writer.writerow([label, f"{value:.2f}"])
    writer.writerow([])
    writer.writerow(["CGT events"])
    writer.writerow(["Symbol", "Account", "Acquired", "Disposed", "Quantity", "Holding days",
                     "Discount eligible", "Cost base AUD", "Proceeds AUD", "Gain/loss AUD",
                     "Opening transaction", "Closing transaction"])
    for event in report.cgt_events:
        writer.writerow([event.symbol, event.account_name, event.acquired_at.date(), event.disposed_at.date(),
                         event.quantity, event.holding_days, "Yes" if event.discount_eligible else "No",
                         event.cost_base_aud, event.proceeds_aud, event.gross_gain_aud,
                         event.opening_transaction_id, event.closing_transaction_id])
    writer.writerow([])
    writer.writerow(["Warnings"])
    for warning in report.warnings:
        writer.writerow([warning])
    filename = f"ato-investment-tax-pack-fy{fy - 1}-{str(fy)[-2:]}.csv"
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# Legacy endpoints retained for existing non-Australian clients.
@router.get("/summary")
async def get_tax_summary(
    tax_year: int = Query(default=datetime.now().year),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    report = await TaxEngine(db, MarketDataService()).compute_tax_summary(
        str(current_user.id), tax_year, include_tlh=True
    )
    return {
        "tax_year": report.tax_year,
        "short_term_gains": float(report.short_term_gains),
        "long_term_gains": float(report.long_term_gains),
        "total_gains": float(report.total_gains),
        "dividend_income": float(report.dividend_income),
        "staking_income": float(report.staking_income),
        "estimated_short_term_tax": float(report.estimated_short_term_tax),
        "estimated_long_term_tax": float(report.estimated_long_term_tax),
        "estimated_total_tax": float(report.estimated_total_tax),
        "unrealized_losses": float(report.unrealized_losses),
        "tlh_opportunity_count": len(report.tlh_opportunities),
        "potential_tlh_savings": sum(float(item.get("tax_savings", 0)) for item in report.tlh_opportunities),
    }


@router.get("/tlh-opportunities")
async def get_tlh_opportunities(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    opportunities, _ = await TaxEngine(db, MarketDataService())._find_tlh_opportunities(str(current_user.id))
    return opportunities
