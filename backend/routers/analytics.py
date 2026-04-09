"""Analytics router — performance, risk, allocation metrics."""
from typing import Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from shared.models import Account, Transaction, User
from shared.auth import get_current_user
from services.analytics_engine import AnalyticsEngine, AnalyticsBundle
from services.portfolio_engine import PortfolioEngine
from services.market_data_service import MarketDataService

router = APIRouter()


class PerformanceResponse(BaseModel):
    total_return_pct: float
    annualized_return_pct: float
    twr_pct: float
    mwr_pct: float
    benchmark_return_pct: float
    alpha: float
    beta: float
    start_value: float
    end_value: float
    period_days: int


class RiskResponse(BaseModel):
    volatility_annual_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    max_drawdown_pct: float
    max_drawdown_duration_days: int
    var_95_pct: float
    cvar_95_pct: float
    beta_vs_benchmark: float
    correlation_vs_benchmark: float


class AllocationResponse(BaseModel):
    by_asset_class: dict[str, float]
    by_sector: dict[str, float]
    by_geography: dict[str, float]
    top_holdings: list[dict]
    concentration_score: float
    diversification_score: float


class AnalyticsBundleResponse(BaseModel):
    performance: PerformanceResponse
    risk: RiskResponse
    allocation: AllocationResponse
    computed_at: str
    period: str
    benchmark: str


def _get_engine(db: AsyncSession) -> AnalyticsEngine:
    market = MarketDataService()
    portfolio = PortfolioEngine(db, market)
    return AnalyticsEngine(portfolio, market)


async def _active_account_ids(user_id: str, db: AsyncSession) -> list[str]:
    """Get IDs of active accounts for a user."""
    result = await db.execute(
        select(Account.id).where(Account.user_id == user_id, Account.is_active == True)
    )
    return [row[0] for row in result.all()]


@router.get("/", response_model=AnalyticsBundleResponse)
async def get_analytics(
    period: str = Query("1Y", description="1M|3M|6M|YTD|1Y|3Y|ALL"),
    benchmark: str = Query("SPY", description="Benchmark ticker"),
    currency: Optional[str] = Query(None, description="Display currency (AUD|USD)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Compute full analytics bundle (performance + risk + allocation)."""
    engine = _get_engine(db)
    active_ids = await _active_account_ids(current_user.id, db)
    bundle = await engine.compute_all(
        user_id=current_user.id,
        period=period,
        benchmark_symbol=benchmark,
        cost_basis_method=current_user.cost_basis_method,
        account_ids=active_ids or None,
        display_currency=currency.upper() if currency else "AUD",
    )

    resp = AnalyticsBundleResponse(
        performance=PerformanceResponse(**bundle.performance.__dict__),
        risk=RiskResponse(**bundle.risk.__dict__),
        allocation=AllocationResponse(**bundle.allocation.__dict__),
        computed_at=bundle.computed_at.isoformat(),
        period=period,
        benchmark=benchmark,
    )

    return resp


@router.get("/performance", response_model=PerformanceResponse)
async def get_performance(
    period: str = Query("1Y"),
    benchmark: str = Query("SPY"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    engine = _get_engine(db)
    active_ids = await _active_account_ids(current_user.id, db)
    bundle = await engine.compute_all(current_user.id, period, benchmark, current_user.cost_basis_method, account_ids=active_ids or None)
    return PerformanceResponse(**bundle.performance.__dict__)


@router.get("/risk", response_model=RiskResponse)
async def get_risk(
    period: str = Query("1Y"),
    benchmark: str = Query("SPY"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    engine = _get_engine(db)
    active_ids = await _active_account_ids(current_user.id, db)
    bundle = await engine.compute_all(current_user.id, period, benchmark, current_user.cost_basis_method, account_ids=active_ids or None)
    return RiskResponse(**bundle.risk.__dict__)


@router.get("/allocation", response_model=AllocationResponse)
async def get_allocation(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    engine = _get_engine(db)
    active_ids = await _active_account_ids(current_user.id, db)
    bundle = await engine.compute_all(current_user.id, "ALL", "SPY", current_user.cost_basis_method, account_ids=active_ids or None)
    return AllocationResponse(**bundle.allocation.__dict__)


@router.get("/portfolio-value-history")
async def get_portfolio_value_history(
    period: str = Query("1Y"),
    start_date: Optional[str] = Query(None, description="Custom start (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="Custom end (YYYY-MM-DD)"),
    currency: Optional[str] = Query(None, description="Display currency (AUD|USD)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get daily portfolio value timeseries for charting."""
    from datetime import datetime as dt, timezone as tz, timedelta
    engine = _get_engine(db)
    if start_date and end_date:
        start = dt.strptime(start_date, "%Y-%m-%d").replace(tzinfo=tz.utc)
        end = dt.strptime(end_date, "%Y-%m-%d").replace(tzinfo=tz.utc)
    else:
        start, end = AnalyticsEngine._period_to_dates(period)

    # For "ALL", use the earliest transaction date instead of a hardcoded 20-year lookback
    if period.upper() == "ALL":
        active_acct_ids = await _active_account_ids(current_user.id, db)
        q = select(func.min(Transaction.transacted_at)).where(
            Transaction.user_id == current_user.id,
        )
        if active_acct_ids:
            q = q.where(Transaction.account_id.in_(active_acct_ids))
        result = await db.execute(q)
        earliest = result.scalar()
        if earliest:
            # Start a few days before the earliest transaction
            start = earliest - timedelta(days=7)
            if start.tzinfo is None:
                start = start.replace(tzinfo=tz.utc)
    portfolio_engine = PortfolioEngine(db, MarketDataService())
    analytics = AnalyticsEngine(portfolio_engine, MarketDataService())
    active_ids = await _active_account_ids(current_user.id, db)
    series = await analytics._build_portfolio_series(
        current_user.id,
        start,
        end,
        active_ids or None,
        display_currency=currency.upper() if currency else "AUD",
    )

    if series.empty:
        return {"data": [], "period": period}

    return {
        "data": [
            {"date": str(date.date()), "value": round(float(val), 2)}
            for date, val in series.items()
        ],
        "period": period,
    }
