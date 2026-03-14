"""Analytics router — performance, risk, allocation metrics."""
from typing import Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from shared.models import User
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


@router.get("/", response_model=AnalyticsBundleResponse)
async def get_analytics(
    period: str = Query("1Y", description="1M|3M|6M|YTD|1Y|3Y|ALL"),
    benchmark: str = Query("SPY", description="Benchmark ticker"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Compute full analytics bundle (performance + risk + allocation)."""
    engine = _get_engine(db)
    bundle = await engine.compute_all(
        user_id=current_user.id,
        period=period,
        benchmark_symbol=benchmark,
        cost_basis_method=current_user.cost_basis_method,
    )

    return AnalyticsBundleResponse(
        performance=PerformanceResponse(**bundle.performance.__dict__),
        risk=RiskResponse(**bundle.risk.__dict__),
        allocation=AllocationResponse(**bundle.allocation.__dict__),
        computed_at=bundle.computed_at.isoformat(),
        period=period,
        benchmark=benchmark,
    )


@router.get("/performance", response_model=PerformanceResponse)
async def get_performance(
    period: str = Query("1Y"),
    benchmark: str = Query("SPY"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    engine = _get_engine(db)
    bundle = await engine.compute_all(current_user.id, period, benchmark, current_user.cost_basis_method)
    return PerformanceResponse(**bundle.performance.__dict__)


@router.get("/risk", response_model=RiskResponse)
async def get_risk(
    period: str = Query("1Y"),
    benchmark: str = Query("SPY"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    engine = _get_engine(db)
    bundle = await engine.compute_all(current_user.id, period, benchmark, current_user.cost_basis_method)
    return RiskResponse(**bundle.risk.__dict__)


@router.get("/allocation", response_model=AllocationResponse)
async def get_allocation(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    engine = _get_engine(db)
    bundle = await engine.compute_all(current_user.id, "ALL", "SPY", current_user.cost_basis_method)
    return AllocationResponse(**bundle.allocation.__dict__)


@router.get("/portfolio-value-history")
async def get_portfolio_value_history(
    period: str = Query("1Y"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get daily portfolio value timeseries for charting."""
    engine = _get_engine(db)
    start, end = AnalyticsEngine._period_to_dates(period)
    portfolio_engine = PortfolioEngine(db, MarketDataService())
    analytics = AnalyticsEngine(portfolio_engine, MarketDataService())
    series = await analytics._build_portfolio_series(current_user.id, start, end)

    if series.empty:
        return {"data": [], "period": period}

    return {
        "data": [
            {"date": str(date.date()), "value": round(float(val), 2)}
            for date, val in series.items()
        ],
        "period": period,
    }
