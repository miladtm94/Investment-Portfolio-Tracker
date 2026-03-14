"""Portfolio router — accounts, holdings, net worth."""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from shared.models import Account, User
from shared.auth import get_current_user
from shared.cache import cache_invalidate_user
from services.portfolio_engine import PortfolioEngine, HoldingSnapshot, PortfolioSummary
from services.market_data_service import MarketDataService

router = APIRouter()


# ─── Pydantic Models ─────────────────────────────────────────────────────────

class AccountCreate(BaseModel):
    name: str
    institution_name: Optional[str] = None
    account_type: str  # BROKERAGE|IRA|ROTH_IRA|401K|CRYPTO_EXCHANGE|WALLET
    account_subtype: Optional[str] = None
    currency: str = "USD"
    is_taxable: bool = True


class AccountResponse(BaseModel):
    id: str
    name: str
    institution_name: Optional[str]
    account_type: str
    account_subtype: Optional[str]
    currency: str
    is_taxable: bool
    is_active: bool
    sync_status: str
    last_synced_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class AccountToggle(BaseModel):
    is_active: bool


class HoldingResponse(BaseModel):
    asset_id: str
    symbol: str
    name: str
    asset_class: str
    quantity: float
    average_cost_basis: Optional[float]
    total_cost_basis: Optional[float]
    last_price: Optional[float]
    market_value: Optional[float]
    weight_pct: Optional[float]
    unrealized_gain: Optional[float]
    unrealized_gain_pct: Optional[float]
    currency: str


class PortfolioSummaryResponse(BaseModel):
    total_market_value: float
    total_cost_basis: float
    total_unrealized_gain: float
    total_unrealized_gain_pct: float
    total_realized_gain_short: float
    total_realized_gain_long: float
    dividend_income: float
    staking_income: float
    holdings: list[HoldingResponse]
    as_of: datetime


def _to_holding_response(h: HoldingSnapshot, total_mv: Decimal) -> HoldingResponse:
    mv = float(h.market_value or 0)
    weight = mv / float(total_mv) * 100 if total_mv else None
    return HoldingResponse(
        asset_id=h.asset_id,
        symbol=h.symbol,
        name=h.name,
        asset_class=h.asset_class,
        quantity=float(h.quantity),
        average_cost_basis=float(h.average_cost_basis) if h.average_cost_basis else None,
        total_cost_basis=float(h.total_cost_basis) if h.total_cost_basis else None,
        last_price=float(h.last_price) if h.last_price else None,
        market_value=mv,
        weight_pct=round(weight, 2) if weight is not None else None,
        unrealized_gain=float(h.unrealized_gain) if h.unrealized_gain else None,
        unrealized_gain_pct=float(h.unrealized_gain_pct) if h.unrealized_gain_pct else None,
        currency=h.currency,
    )


def _to_summary_response(s: PortfolioSummary) -> PortfolioSummaryResponse:
    return PortfolioSummaryResponse(
        total_market_value=float(s.total_market_value),
        total_cost_basis=float(s.total_cost_basis),
        total_unrealized_gain=float(s.total_unrealized_gain),
        total_unrealized_gain_pct=float(s.total_unrealized_gain_pct),
        total_realized_gain_short=float(s.total_realized_gain_short),
        total_realized_gain_long=float(s.total_realized_gain_long),
        dividend_income=float(s.dividend_income),
        staking_income=float(s.staking_income),
        holdings=[_to_holding_response(h, s.total_market_value) for h in s.holdings],
        as_of=s.as_of,
    )


def _get_engine(db: AsyncSession) -> PortfolioEngine:
    return PortfolioEngine(db, MarketDataService())


# ─── Account Endpoints ───────────────────────────────────────────────────────

@router.get("/accounts", response_model=list[AccountResponse])
async def list_accounts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Account).where(Account.user_id == current_user.id, Account.is_active == True)
        .order_by(Account.created_at)
    )
    return result.scalars().all()


@router.post("/accounts", response_model=AccountResponse, status_code=201)
async def create_account(
    body: AccountCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    account = Account(
        user_id=current_user.id,
        name=body.name,
        institution_name=body.institution_name,
        account_type=body.account_type,
        account_subtype=body.account_subtype,
        currency=body.currency.upper(),
        is_taxable=body.is_taxable,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


@router.get("/accounts/all", response_model=list[AccountResponse])
async def list_all_accounts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all accounts including inactive (for Investments page)."""
    result = await db.execute(
        select(Account).where(Account.user_id == current_user.id)
        .order_by(Account.created_at)
    )
    return result.scalars().all()


@router.patch("/accounts/{account_id}", response_model=AccountResponse)
async def toggle_account(
    account_id: str,
    body: AccountToggle,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Toggle account active/inactive for dashboard calculations."""
    result = await db.execute(
        select(Account).where(Account.id == account_id, Account.user_id == current_user.id)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    account.is_active = body.is_active
    await db.commit()
    await db.refresh(account)
    await cache_invalidate_user(current_user.id)
    return account


@router.delete("/accounts/{account_id}", status_code=204)
async def delete_account(
    account_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Account).where(Account.id == account_id, Account.user_id == current_user.id)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    account.is_active = False
    await db.commit()
    await cache_invalidate_user(current_user.id)


# ─── Holdings Endpoints ───────────────────────────────────────────────────────

@router.get("/summary", response_model=PortfolioSummaryResponse)
async def get_portfolio_summary(
    account_ids: Optional[list[str]] = Query(None),
    as_of: Optional[datetime] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get consolidated portfolio summary across active (or specified) accounts.
    Only includes active accounts unless specific account_ids are provided.
    """
    # If no specific accounts requested, only use active ones
    if not account_ids:
        active_result = await db.execute(
            select(Account.id).where(
                Account.user_id == current_user.id,
                Account.is_active == True,
            )
        )
        account_ids = [row[0] for row in active_result.all()]
        if not account_ids:
            return _to_summary_response(PortfolioSummary(
                total_market_value=Decimal(0), total_cost_basis=Decimal(0),
                total_unrealized_gain=Decimal(0), total_unrealized_gain_pct=Decimal(0),
                total_realized_gain_short=Decimal(0), total_realized_gain_long=Decimal(0),
                dividend_income=Decimal(0), staking_income=Decimal(0),
                holdings=[], as_of=as_of or datetime.now(timezone.utc),
            ))

    engine = _get_engine(db)
    summary = await engine.get_portfolio_summary(
        user_id=current_user.id,
        account_ids=account_ids,
        as_of=as_of,
        cost_basis_method=current_user.cost_basis_method,
    )
    return _to_summary_response(summary)


@router.get("/accounts/{account_id}/holdings", response_model=list[HoldingResponse])
async def get_account_holdings(
    account_id: str,
    as_of: Optional[datetime] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get holdings for a specific account."""
    engine = _get_engine(db)
    summary = await engine.get_portfolio_summary(
        user_id=current_user.id,
        account_ids=[account_id],
        as_of=as_of,
        cost_basis_method=current_user.cost_basis_method,
    )
    return [_to_holding_response(h, summary.total_market_value) for h in summary.holdings]


@router.get("/net-worth")
async def get_net_worth(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get total net worth breakdown by asset class (active accounts only)."""
    active_result = await db.execute(
        select(Account.id).where(
            Account.user_id == current_user.id,
            Account.is_active == True,
        )
    )
    active_ids = [row[0] for row in active_result.all()]

    engine = _get_engine(db)
    summary = await engine.get_portfolio_summary(
        user_id=current_user.id,
        account_ids=active_ids or None,
        cost_basis_method=current_user.cost_basis_method,
    )

    by_class: dict[str, float] = {}
    for h in summary.holdings:
        mv = float(h.market_value or 0)
        by_class[h.asset_class] = by_class.get(h.asset_class, 0) + mv

    return {
        "total_net_worth": float(summary.total_market_value),
        "by_asset_class": by_class,
        "total_unrealized_gain": float(summary.total_unrealized_gain),
        "currency": current_user.preferred_currency,
        "as_of": summary.as_of.isoformat(),
    }
