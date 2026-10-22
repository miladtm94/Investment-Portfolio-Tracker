"""Portfolio router — accounts, holdings, net worth."""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, func, select

from database import get_db
from shared.models import Account, ApiCredential, Transaction, User
from shared.auth import get_current_user
from shared.cache import cache_invalidate_user
from services.portfolio_engine import PortfolioEngine, HoldingSnapshot, PortfolioSummary
from services.market_data_service import MarketDataService
from services.analytics_engine import AnalyticsEngine
from services.fx_service import FXService
from services.period_utils import cap_period_start_to_earliest_transaction

router = APIRouter()
ZERO = Decimal("0")


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
    has_api_connection: bool = False
    api_provider: Optional[str] = None
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
    original_currency: str = "AUD"  # Quote currency used for current market prices
    exchange: Optional[str] = None
    period_income: Optional[float] = None
    period_price_return_pct: Optional[float] = None


class PortfolioSummaryResponse(BaseModel):
    total_market_value: float
    total_cost_basis: float
    total_unrealized_gain: float
    total_unrealized_gain_pct: float
    total_realized_gain_short: float
    total_realized_gain_long: float
    total_realized_gain: float
    total_income: float
    total_pnl: float
    total_pnl_pct: float
    dividend_income: float
    staking_income: float
    holdings: list[HoldingResponse]
    as_of: datetime
    period: Optional[str] = None
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    period_market_value_change: Optional[float] = None
    period_realized_gain_short: Optional[float] = None
    period_realized_gain_long: Optional[float] = None
    period_realized_gain: Optional[float] = None
    period_income: Optional[float] = None
    period_pnl: Optional[float] = None
    period_pnl_pct: Optional[float] = None


class PeriodMetrics(BaseModel):
    period: str
    period_start: datetime
    period_end: datetime
    market_value_change: float
    realized_gain_short: float
    realized_gain_long: float
    realized_gain: float
    income: float
    pnl: float
    pnl_pct: float
    income_by_asset: dict[str, float]
    price_return_by_asset: dict[str, float]


def _to_holding_response(
    h: HoldingSnapshot,
    total_mv: Decimal,
    period_metrics: PeriodMetrics | None = None,
) -> HoldingResponse:
    mv = float(h.market_value or 0)
    weight = mv / float(total_mv) * 100 if total_mv else None
    return HoldingResponse(
        asset_id=h.asset_id,
        symbol=h.symbol,
        name=h.name,
        asset_class=h.asset_class,
        quantity=float(h.quantity),
        average_cost_basis=float(h.average_cost_basis) if h.average_cost_basis is not None else None,
        total_cost_basis=float(h.total_cost_basis) if h.total_cost_basis is not None else None,
        last_price=float(h.last_price) if h.last_price is not None else None,
        market_value=mv,
        weight_pct=round(weight, 2) if weight is not None else None,
        unrealized_gain=float(h.unrealized_gain) if h.unrealized_gain is not None else None,
        unrealized_gain_pct=float(h.unrealized_gain_pct) if h.unrealized_gain_pct is not None else None,
        currency=h.currency,
        original_currency=getattr(h, 'original_currency', h.currency),
        exchange=getattr(h, 'exchange', None),
        period_income=period_metrics.income_by_asset.get(h.asset_id) if period_metrics else None,
        period_price_return_pct=period_metrics.price_return_by_asset.get(h.asset_id) if period_metrics else None,
    )


def _to_summary_response(
    s: PortfolioSummary,
    period_metrics: PeriodMetrics | None = None,
) -> PortfolioSummaryResponse:
    return PortfolioSummaryResponse(
        total_market_value=float(s.total_market_value),
        total_cost_basis=float(s.total_cost_basis),
        total_unrealized_gain=float(s.total_unrealized_gain),
        total_unrealized_gain_pct=float(s.total_unrealized_gain_pct),
        total_realized_gain_short=float(s.total_realized_gain_short),
        total_realized_gain_long=float(s.total_realized_gain_long),
        total_realized_gain=float(s.total_realized_gain),
        total_income=float(s.total_income),
        total_pnl=float(s.total_pnl),
        total_pnl_pct=float(s.total_pnl_pct),
        dividend_income=float(s.dividend_income),
        staking_income=float(s.staking_income),
        holdings=[_to_holding_response(h, s.total_market_value, period_metrics) for h in s.holdings],
        as_of=s.as_of,
        period=period_metrics.period if period_metrics else None,
        period_start=period_metrics.period_start if period_metrics else None,
        period_end=period_metrics.period_end if period_metrics else None,
        period_market_value_change=period_metrics.market_value_change if period_metrics else None,
        period_realized_gain_short=period_metrics.realized_gain_short if period_metrics else None,
        period_realized_gain_long=period_metrics.realized_gain_long if period_metrics else None,
        period_realized_gain=period_metrics.realized_gain if period_metrics else None,
        period_income=period_metrics.income if period_metrics else None,
        period_pnl=period_metrics.pnl if period_metrics else None,
        period_pnl_pct=period_metrics.pnl_pct if period_metrics else None,
    )


def _to_account_response(
    account: Account,
    api_account_ids: set[str] | None = None,
    api_providers_by_account: dict[str, str] | None = None,
) -> AccountResponse:
    return AccountResponse(
        id=account.id,
        name=account.name,
        institution_name=account.institution_name,
        account_type=account.account_type,
        account_subtype=account.account_subtype,
        currency=account.currency,
        is_taxable=account.is_taxable,
        is_active=account.is_active,
        has_api_connection=account.id in (api_account_ids or set()),
        api_provider=(api_providers_by_account or {}).get(account.id),
        sync_status=account.sync_status,
        last_synced_at=account.last_synced_at,
        created_at=account.created_at,
    )


async def _api_connected_account_ids(user_id: str, db: AsyncSession) -> set[str]:
    return set((await _api_connected_accounts(user_id, db)).keys())


async def _api_connected_accounts(user_id: str, db: AsyncSession) -> dict[str, str]:
    result = await db.execute(
        select(ApiCredential.account_id, ApiCredential.provider).where(
            ApiCredential.user_id == user_id,
            ApiCredential.is_active == True,
            ApiCredential.account_id.isnot(None),
        )
    )
    return {row[0]: row[1] for row in result.all() if row[0]}


async def _active_account_ids(user_id: str, db: AsyncSession) -> list[str]:
    result = await db.execute(
        select(Account.id).where(Account.user_id == user_id, Account.is_active == True)
    )
    return [row[0] for row in result.all()]


async def _earliest_transaction_at(
    user_id: str,
    account_ids: list[str],
    db: AsyncSession,
):
    query = select(func.min(Transaction.transacted_at)).where(
        Transaction.user_id == user_id,
        Transaction.status == "SETTLED",
    )
    if account_ids:
        query = query.where(Transaction.account_id.in_(account_ids))
    result = await db.execute(query)
    return result.scalar()


def _get_engine(db: AsyncSession) -> PortfolioEngine:
    return PortfolioEngine(db, MarketDataService())


async def _period_dates(
    period: str,
    user_id: str,
    account_ids: list[str],
    db: AsyncSession,
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[datetime, datetime]:
    period_key = period.upper()
    if start_date and end_date:
        start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        # A date-only end is inclusive in the UI.  Midnight would otherwise
        # omit every payment made later on the selected final day.
        end = datetime.strptime(end_date, "%Y-%m-%d").replace(
            hour=23,
            minute=59,
            second=59,
            microsecond=999999,
            tzinfo=timezone.utc,
        )
    else:
        start, end = AnalyticsEngine._period_to_dates(period_key)

    start = cap_period_start_to_earliest_transaction(
        start,
        await _earliest_transaction_at(user_id, account_ids, db),
    )
    return start, end


async def _display_conversion_rate(display_currency: str, as_of: datetime) -> Decimal:
    target = FXService._normalize_currency(display_currency)
    if target == "AUD":
        return Decimal("1")
    fx = FXService()
    try:
        target_to_aud = await fx.get_rate_on_date(target, "AUD", as_of)
        if target_to_aud == Decimal("0"):
            return Decimal("1")
        return Decimal("1") / target_to_aud
    finally:
        await fx.close()


async def _amount_to_aud(txn: Transaction, fx: FXService) -> Decimal:
    if txn.net_amount_aud is not None:
        return abs(Decimal(str(txn.net_amount_aud)))

    # Imports do not all populate the same monetary column. Prefer the actual
    # cash amount, then fall back to a gross payment or quantity x payout.
    if txn.net_amount is not None:
        amount = abs(Decimal(str(txn.net_amount)))
        ccy = FXService._normalize_currency(txn.currency or "AUD")
    elif txn.gross_amount is not None:
        gross = abs(Decimal(str(txn.gross_amount)))
        withheld = abs(Decimal(str(txn.tax_withheld or 0)))
        amount = max(ZERO, gross - withheld)
        ccy = FXService._normalize_currency(txn.currency or "AUD")
    elif txn.net_amount_usd is not None:
        amount = abs(Decimal(str(txn.net_amount_usd)))
        ccy = "USD"
    elif txn.quantity is not None and (txn.dividend_per_share is not None or txn.price_per_unit is not None):
        payout = txn.dividend_per_share if txn.dividend_per_share is not None else txn.price_per_unit
        amount = abs(Decimal(str(txn.quantity)) * Decimal(str(payout)))
        ccy = FXService._normalize_currency(txn.currency or "AUD")
    else:
        return ZERO

    if ccy == "AUD":
        return amount
    if txn.fx_rate_to_aud:
        return amount * Decimal(str(txn.fx_rate_to_aud))
    return amount * await fx.get_rate_on_date(ccy, "AUD", txn.transacted_at)


async def _period_income(
    user_id: str,
    account_ids: list[str],
    start: datetime,
    end: datetime,
    display_currency: str,
    db: AsyncSession,
) -> tuple[float, dict[str, float]]:
    query = select(Transaction).where(
        and_(
            Transaction.user_id == user_id,
            Transaction.status == "SETTLED",
            Transaction.transaction_type.in_([
                "DIVIDEND", "FRANKED_DIVIDEND", "DISTRIBUTION", "INTEREST",
                "STAKE_REWARD", "STAKING_REWARD", "MINING_REWARD", "AIRDROP",
            ]),
            Transaction.transacted_at >= start,
            Transaction.transacted_at <= end,
        )
    )
    if account_ids:
        query = query.where(Transaction.account_id.in_(account_ids))

    result = await db.execute(query)
    txns = result.scalars().all()
    if not txns:
        return 0.0, {}

    aud_to_display = await _display_conversion_rate(display_currency, end)
    total_aud = ZERO
    income_by_asset: dict[str, Decimal] = {}
    fx = FXService()
    try:
        for txn in txns:
            amount = await _amount_to_aud(txn, fx)
            total_aud += amount
            if txn.asset_id:
                income_by_asset[txn.asset_id] = income_by_asset.get(txn.asset_id, ZERO) + amount
    finally:
        await fx.close()

    converted_by_asset = {
        asset_id: round(float(amount * aud_to_display), 2)
        for asset_id, amount in income_by_asset.items()
    }
    return round(float(total_aud * aud_to_display), 2), converted_by_asset


async def _period_price_return_by_asset(
    holdings: list[HoldingSnapshot],
    start: datetime,
    end: datetime,
    market_data: MarketDataService,
) -> dict[str, float]:
    fx = FXService()
    returns: dict[str, float] = {}
    semaphore = asyncio.Semaphore(6)
    try:
        async def compute_return(holding: HoldingSnapshot) -> tuple[str, float | None]:
            try:
                async with semaphore:
                    quote_ccy = FXService._normalize_currency(holding.original_currency or "AUD")
                    prices = await market_data.get_historical_prices(
                        holding.symbol,
                        start,
                        end,
                        currency=quote_ccy,
                    )
                if len(prices) < 2:
                    return holding.asset_id, None

                first = prices[0]
                last = prices[-1]
                first_price = Decimal(str(first.get("close") or 0))
                last_price = Decimal(str(last.get("close") or 0))
                if first_price <= 0:
                    return holding.asset_id, None

                first_date = datetime.fromisoformat(str(first["date"]).replace("Z", "+00:00"))
                last_date = datetime.fromisoformat(str(last["date"]).replace("Z", "+00:00"))
                if first_date.tzinfo is None:
                    first_date = first_date.replace(tzinfo=timezone.utc)
                if last_date.tzinfo is None:
                    last_date = last_date.replace(tzinfo=timezone.utc)

                if quote_ccy != "AUD":
                    first_price *= await fx.get_rate_on_date(quote_ccy, "AUD", first_date)
                    last_price *= await fx.get_rate_on_date(quote_ccy, "AUD", last_date)

                return holding.asset_id, round(float((last_price / first_price - 1) * 100), 2)
            except Exception:
                return holding.asset_id, None

        results = await asyncio.gather(*(compute_return(holding) for holding in holdings))
        returns = {
            asset_id: value
            for asset_id, value in results
            if value is not None
        }
    finally:
        await fx.close()

    return returns


async def _compute_period_metrics(
    user_id: str,
    account_ids: list[str],
    period: str,
    display_currency: str,
    cost_basis_method: str,
    current_summary: PortfolioSummary,
    db: AsyncSession,
    start_date: str | None = None,
    end_date: str | None = None,
    include_holding_period_metrics: bool = False,
) -> PeriodMetrics:
    period_key = period.upper()
    start, end = await _period_dates(period_key, user_id, account_ids, db, start_date, end_date)
    if start >= end:
        return PeriodMetrics(
            period=period_key,
            period_start=start,
            period_end=end,
            market_value_change=0,
            realized_gain_short=0,
            realized_gain_long=0,
            realized_gain=0,
            income=0,
            pnl=0,
            pnl_pct=0,
            income_by_asset={},
            price_return_by_asset={},
        )

    market_data = MarketDataService()
    engine = PortfolioEngine(db, market_data)

    start_summary = await engine.get_portfolio_summary(
        user_id=user_id,
        account_ids=account_ids,
        as_of=start,
        cost_basis_method=cost_basis_method,
        display_currency=display_currency,
    )

    def dec(value: object) -> Decimal:
        return Decimal(str(value or 0))

    unrealized_delta = dec(current_summary.total_unrealized_gain) - dec(start_summary.total_unrealized_gain)
    realized_short = dec(current_summary.total_realized_gain_short) - dec(start_summary.total_realized_gain_short)
    realized_long = dec(current_summary.total_realized_gain_long) - dec(start_summary.total_realized_gain_long)
    realized = realized_short + realized_long
    # Income is a cash-flow metric. Sum the period ledger directly instead of
    # subtracting two reconstructed lifetime summaries: the latter can miss
    # valid importer shapes and can inherit stale historical cache entries.
    try:
        period_income, income_by_asset = await _period_income(
            user_id,
            account_ids,
            start,
            end,
            display_currency,
            db,
        )
        income = dec(period_income)
    except Exception:
        income = dec(current_summary.total_income) - dec(start_summary.total_income)
        income_by_asset = {}
    pnl = unrealized_delta + realized + income
    denominator = dec(current_summary.total_cost_basis) or dec(start_summary.total_cost_basis)
    pnl_pct = (pnl / denominator * Decimal("100")) if denominator > ZERO else Decimal("0")

    price_return_by_asset = {}
    if include_holding_period_metrics:
        try:
            price_return_by_asset = await _period_price_return_by_asset(
                current_summary.holdings,
                start,
                end,
                market_data,
            )
        except Exception:
            price_return_by_asset = {}

    return PeriodMetrics(
        period=period_key,
        period_start=start,
        period_end=end,
        market_value_change=round(float(unrealized_delta), 2),
        realized_gain_short=round(float(realized_short), 2),
        realized_gain_long=round(float(realized_long), 2),
        realized_gain=round(float(realized), 2),
        income=round(float(income), 2),
        pnl=round(float(pnl), 2),
        pnl_pct=round(float(pnl_pct), 2),
        income_by_asset=income_by_asset,
        price_return_by_asset=price_return_by_asset,
    )


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
    accounts = result.scalars().all()
    api_accounts = await _api_connected_accounts(current_user.id, db)
    return [_to_account_response(account, set(api_accounts), api_accounts) for account in accounts]


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
    return _to_account_response(account)


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
    accounts = result.scalars().all()
    api_accounts = await _api_connected_accounts(current_user.id, db)
    return [_to_account_response(account, set(api_accounts), api_accounts) for account in accounts]


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
    api_accounts = await _api_connected_accounts(current_user.id, db)
    return _to_account_response(account, set(api_accounts), api_accounts)


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
    # Hard delete: remove all transactions first, then the account
    await db.execute(
        select(Transaction).where(Transaction.account_id == account_id)
    )
    from sqlalchemy import delete as sa_delete
    await db.execute(sa_delete(Transaction).where(Transaction.account_id == account_id))
    await db.delete(account)
    await db.commit()
    await cache_invalidate_user(current_user.id)


# ─── Holdings Endpoints ───────────────────────────────────────────────────────

@router.get("/summary", response_model=PortfolioSummaryResponse)
async def get_portfolio_summary(
    account_ids: Optional[list[str]] = Query(None),
    as_of: Optional[datetime] = Query(None),
    period: Optional[str] = Query(None, description="Optional performance period: 1M|3M|6M|YTD|1Y|3Y|ALL"),
    start_date: Optional[str] = Query(None, description="Custom period start (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="Custom period end (YYYY-MM-DD)"),
    currency: Optional[str] = Query(None, description="Display currency (AUD|USD)"),
    include_holding_period_metrics: bool = Query(
        False,
        description="Include slower holding-level historical return metrics",
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get consolidated portfolio summary across active (or specified) accounts.
    Only includes active accounts unless specific account_ids are provided.
    """
    # If no specific accounts requested, only use active ones
    if not account_ids:
        account_ids = await _active_account_ids(current_user.id, db)
        if not account_ids:
            return _to_summary_response(PortfolioSummary(
                total_market_value=Decimal(0), total_cost_basis=Decimal(0),
                total_unrealized_gain=Decimal(0), total_unrealized_gain_pct=Decimal(0),
                total_realized_gain_short=Decimal(0), total_realized_gain_long=Decimal(0),
                total_realized_gain=Decimal(0), total_income=Decimal(0),
                total_pnl=Decimal(0), total_pnl_pct=Decimal(0),
                dividend_income=Decimal(0), staking_income=Decimal(0),
                holdings=[], as_of=as_of or datetime.now(timezone.utc),
            ))

    engine = _get_engine(db)
    display_ccy = currency.upper() if currency else "AUD"
    summary = await engine.get_portfolio_summary(
        user_id=current_user.id,
        account_ids=account_ids,
        as_of=as_of,
        cost_basis_method=current_user.cost_basis_method,
        display_currency=display_ccy,
    )
    period_metrics = None
    if period:
        period_metrics = await _compute_period_metrics(
            user_id=current_user.id,
            account_ids=account_ids,
            period=period,
            display_currency=display_ccy,
            cost_basis_method=current_user.cost_basis_method,
            current_summary=summary,
            db=db,
            start_date=start_date,
            end_date=end_date,
            include_holding_period_metrics=include_holding_period_metrics,
        )

    result = _to_summary_response(summary, period_metrics)

    return result


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
    currency: Optional[str] = Query(None, description="Display currency (AUD|USD)"),
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
    display_ccy = currency.upper() if currency else "AUD"
    summary = await engine.get_portfolio_summary(
        user_id=current_user.id,
        account_ids=active_ids or None,
        cost_basis_method=current_user.cost_basis_method,
        display_currency=display_ccy,
    )

    by_class: dict[str, float] = {}
    for h in summary.holdings:
        mv = float(h.market_value or 0)
        by_class[h.asset_class] = by_class.get(h.asset_class, 0) + mv

    return {
        "total_net_worth": float(summary.total_market_value),
        "by_asset_class": by_class,
        "total_unrealized_gain": float(summary.total_unrealized_gain),
        "currency": display_ccy,
        "as_of": summary.as_of.isoformat(),
    }
