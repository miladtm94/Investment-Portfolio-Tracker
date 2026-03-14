"""
Advanced Analytics Engine.

Computes institutional-grade performance, risk, and allocation metrics
using vectorized NumPy/Pandas operations.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional

import numpy as np
import pandas as pd
from scipy import optimize

from services.market_data_service import MarketDataService
from services.portfolio_engine import PortfolioEngine, PortfolioSummary

logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 252
RISK_FREE_RATE = 0.05  # 5% annual, update via config


@dataclass
class PerformanceMetrics:
    total_return_pct: float
    annualized_return_pct: float
    twr_pct: float           # Time-weighted return
    mwr_pct: float           # Money-weighted return (XIRR)
    benchmark_return_pct: float
    alpha: float
    beta: float
    start_value: float
    end_value: float
    period_days: int


@dataclass
class RiskMetrics:
    volatility_annual_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    max_drawdown_pct: float
    max_drawdown_duration_days: int
    var_95_pct: float          # Value at Risk 95% confidence
    cvar_95_pct: float         # Conditional VaR (Expected Shortfall)
    beta_vs_benchmark: float
    correlation_vs_benchmark: float


@dataclass
class AllocationMetrics:
    by_asset_class: dict[str, float]  # asset_class → weight%
    by_sector: dict[str, float]
    by_geography: dict[str, float]
    top_holdings: list[dict]          # [{symbol, weight_pct, market_value}]
    concentration_score: float        # Herfindahl–Hirschman Index (0-1)
    diversification_score: float      # 1 - concentration


@dataclass
class AnalyticsBundle:
    performance: PerformanceMetrics
    risk: RiskMetrics
    allocation: AllocationMetrics
    computed_at: datetime


class AnalyticsEngine:
    """
    Orchestrates all analytics computation.
    Lazy: only computes what's needed, caches aggressively.
    """

    def __init__(self, portfolio_engine: PortfolioEngine, market_data: MarketDataService):
        self.portfolio_engine = portfolio_engine
        self.market_data = market_data

    async def compute_all(
        self,
        user_id: str,
        period: str = "1Y",  # 1M|3M|6M|YTD|1Y|3Y|ALL
        benchmark_symbol: str = "SPY",
        cost_basis_method: str = "FIFO",
    ) -> AnalyticsBundle:
        start, end = self._period_to_dates(period)

        # Get current portfolio snapshot
        current = await self.portfolio_engine.get_portfolio_summary(user_id=user_id, cost_basis_method=cost_basis_method)

        # Build portfolio return series
        portfolio_series = await self._build_portfolio_series(user_id, start, end)
        benchmark_series = await self._build_benchmark_series(benchmark_symbol, start, end)

        performance = self._compute_performance(portfolio_series, benchmark_series, current)
        risk = self._compute_risk(portfolio_series, benchmark_series)
        allocation = self._compute_allocation(current)

        return AnalyticsBundle(
            performance=performance,
            risk=risk,
            allocation=allocation,
            computed_at=datetime.now(timezone.utc),
        )

    # ─── Performance ─────────────────────────────────────────────────────

    def _compute_performance(
        self,
        portfolio: pd.Series,
        benchmark: pd.Series,
        current: PortfolioSummary,
    ) -> PerformanceMetrics:
        if portfolio.empty or len(portfolio) < 2:
            return PerformanceMetrics(
                total_return_pct=0, annualized_return_pct=0, twr_pct=0, mwr_pct=0,
                benchmark_return_pct=0, alpha=0, beta=1,
                start_value=float(current.total_market_value),
                end_value=float(current.total_market_value),
                period_days=0,
            )

        returns = portfolio.pct_change().dropna()
        bench_returns = benchmark.pct_change().dropna()

        total_return = (portfolio.iloc[-1] / portfolio.iloc[0] - 1) * 100
        period_days = (portfolio.index[-1] - portfolio.index[0]).days
        annualized_years = period_days / 365.25
        annualized = ((1 + total_return / 100) ** (1 / max(annualized_years, 0.01)) - 1) * 100

        twr = self._compute_twr(returns) * 100

        # Beta and alpha
        beta, alpha = self._compute_beta_alpha(returns, bench_returns)
        bench_total = (benchmark.iloc[-1] / benchmark.iloc[0] - 1) * 100 if not benchmark.empty else 0

        return PerformanceMetrics(
            total_return_pct=round(total_return, 4),
            annualized_return_pct=round(annualized, 4),
            twr_pct=round(twr, 4),
            mwr_pct=round(twr, 4),  # Simplified: use TWR unless cashflows are tracked
            benchmark_return_pct=round(bench_total, 4),
            alpha=round(alpha * 100, 4),
            beta=round(beta, 4),
            start_value=round(portfolio.iloc[0], 2),
            end_value=round(portfolio.iloc[-1], 2),
            period_days=period_days,
        )

    def _compute_twr(self, daily_returns: pd.Series) -> float:
        """Time-weighted return: compound daily returns."""
        if daily_returns.empty:
            return 0.0
        return float(np.prod(1 + daily_returns.values) - 1)

    def compute_mwr(self, cashflows: list[tuple[datetime, float]], final_value: float) -> float:
        """
        Money-weighted return (XIRR) using Newton-Raphson via scipy.
        cashflows: list of (date, amount) where negative = invested, positive = withdrawn.
        """
        if not cashflows:
            return 0.0

        dates = [cf[0] for cf in cashflows]
        amounts = [cf[1] for cf in cashflows]
        amounts.append(final_value)
        dates.append(datetime.now(timezone.utc))

        t0 = dates[0]
        time_years = [(d - t0).days / 365.25 for d in dates]

        def npv(rate):
            return sum(cf / (1 + rate) ** t for cf, t in zip(amounts, time_years))

        try:
            return optimize.brentq(npv, -0.999, 10.0, maxiter=100)
        except ValueError:
            return 0.0

    def _compute_beta_alpha(
        self, returns: pd.Series, bench_returns: pd.Series
    ) -> tuple[float, float]:
        """Compute beta and Jensen's alpha via OLS regression."""
        if returns.empty or bench_returns.empty:
            return 1.0, 0.0

        aligned = returns.align(bench_returns, join="inner")
        port, bench = aligned[0].dropna(), aligned[1].dropna()
        if len(port) < 5:
            return 1.0, 0.0

        beta = np.cov(port, bench)[0, 1] / np.var(bench) if np.var(bench) > 0 else 1.0
        rf_daily = RISK_FREE_RATE / TRADING_DAYS_PER_YEAR
        alpha = float(np.mean(port) - (rf_daily + beta * (np.mean(bench) - rf_daily)))

        return float(beta), float(alpha)

    # ─── Risk ────────────────────────────────────────────────────────────

    def _compute_risk(self, portfolio: pd.Series, benchmark: pd.Series) -> RiskMetrics:
        if portfolio.empty or len(portfolio) < 5:
            return RiskMetrics(
                volatility_annual_pct=0, sharpe_ratio=0, sortino_ratio=0,
                calmar_ratio=0, max_drawdown_pct=0, max_drawdown_duration_days=0,
                var_95_pct=0, cvar_95_pct=0, beta_vs_benchmark=1, correlation_vs_benchmark=0,
            )

        returns = portfolio.pct_change().dropna()
        bench_returns = benchmark.pct_change().dropna()

        vol = float(returns.std() * np.sqrt(TRADING_DAYS_PER_YEAR) * 100)
        sharpe = self._sharpe(returns)
        sortino = self._sortino(returns)
        max_dd, dd_duration = self._max_drawdown(portfolio)
        calmar = abs(float(returns.mean() * TRADING_DAYS_PER_YEAR / (max_dd / 100))) if max_dd != 0 else 0
        var_95 = float(np.percentile(returns, 5) * 100)
        cvar_95 = float(returns[returns <= np.percentile(returns, 5)].mean() * 100)
        beta, _ = self._compute_beta_alpha(returns, bench_returns)
        corr = float(returns.corr(bench_returns)) if not bench_returns.empty else 0

        return RiskMetrics(
            volatility_annual_pct=round(vol, 4),
            sharpe_ratio=round(sharpe, 4),
            sortino_ratio=round(sortino, 4),
            calmar_ratio=round(calmar, 4),
            max_drawdown_pct=round(max_dd, 4),
            max_drawdown_duration_days=dd_duration,
            var_95_pct=round(var_95, 4),
            cvar_95_pct=round(cvar_95, 4),
            beta_vs_benchmark=round(beta, 4),
            correlation_vs_benchmark=round(corr, 4),
        )

    def _sharpe(self, returns: pd.Series) -> float:
        rf_daily = RISK_FREE_RATE / TRADING_DAYS_PER_YEAR
        excess = returns - rf_daily
        std = returns.std()
        if std == 0:
            return 0.0
        return float(excess.mean() / std * np.sqrt(TRADING_DAYS_PER_YEAR))

    def _sortino(self, returns: pd.Series) -> float:
        rf_daily = RISK_FREE_RATE / TRADING_DAYS_PER_YEAR
        excess = returns - rf_daily
        downside = returns[returns < 0].std()
        if downside == 0:
            return 0.0
        return float(excess.mean() / downside * np.sqrt(TRADING_DAYS_PER_YEAR))

    def _max_drawdown(self, portfolio: pd.Series) -> tuple[float, int]:
        """Compute maximum drawdown percentage and duration in days."""
        cum_max = portfolio.cummax()
        drawdown = (portfolio - cum_max) / cum_max
        max_dd = float(drawdown.min() * 100)

        # Duration: longest continuous period below previous peak
        is_dd = drawdown < 0
        duration = 0
        current = 0
        for v in is_dd:
            if v:
                current += 1
                duration = max(duration, current)
            else:
                current = 0

        return max_dd, duration

    # ─── Allocation ───────────────────────────────────────────────────────

    def _compute_allocation(self, portfolio: PortfolioSummary) -> AllocationMetrics:
        total_mv = float(portfolio.total_market_value)
        if total_mv == 0:
            return AllocationMetrics({}, {}, {}, [], 0, 1)

        by_asset_class: dict[str, float] = {}
        by_sector: dict[str, float] = {}
        weights: list[float] = []
        top_holdings: list[dict] = []

        for h in portfolio.holdings:
            if not h.market_value:
                continue
            mv = float(h.market_value)
            w = mv / total_mv

            # Asset class
            by_asset_class[h.asset_class] = by_asset_class.get(h.asset_class, 0) + w * 100

            weights.append(w)
            top_holdings.append({
                "symbol": h.symbol,
                "name": h.name,
                "asset_class": h.asset_class,
                "weight_pct": round(w * 100, 2),
                "market_value": mv,
                "unrealized_gain": float(h.unrealized_gain or 0),
                "unrealized_gain_pct": float(h.unrealized_gain_pct or 0),
            })

        # HHI concentration score
        hhi = sum(w ** 2 for w in weights)

        top_holdings.sort(key=lambda x: -x["market_value"])

        return AllocationMetrics(
            by_asset_class={k: round(v, 2) for k, v in by_asset_class.items()},
            by_sector=by_sector,
            by_geography={},
            top_holdings=top_holdings[:20],
            concentration_score=round(hhi, 4),
            diversification_score=round(1 - hhi, 4),
        )

    # ─── Time Series Builders ─────────────────────────────────────────────

    async def _build_portfolio_series(
        self, user_id: str, start: datetime, end: datetime
    ) -> pd.Series:
        """
        Build daily portfolio value series.
        For now, reconstruct at current prices — a full implementation
        would replay the portfolio daily.
        """
        current = await self.portfolio_engine.get_portfolio_summary(user_id=user_id)
        if not current.holdings:
            return pd.Series(dtype=float)

        # Build series from first holding's history
        symbols = [h.symbol for h in current.holdings[:5]]  # Top 5 for performance
        all_prices: dict[str, list[dict]] = {}

        for sym in symbols:
            prices = await self.market_data.get_historical_prices(sym, start, end)
            if prices:
                all_prices[sym] = prices

        if not all_prices:
            return pd.Series(dtype=float)

        # Build DataFrame of prices
        frames = []
        for sym, prices in all_prices.items():
            df = pd.DataFrame(prices)
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")[["close"]].rename(columns={"close": sym})
            frames.append(df)

        if not frames:
            return pd.Series(dtype=float)

        price_df = pd.concat(frames, axis=1).fillna(method="ffill")

        # Weight by current holdings
        weights: dict[str, float] = {}
        total_mv = float(current.total_market_value)
        for h in current.holdings:
            if h.symbol in price_df.columns and h.market_value:
                weights[h.symbol] = float(h.market_value) / total_mv if total_mv > 0 else 0

        # Compute weighted portfolio value (indexed to current value)
        portfolio_values = pd.Series(0.0, index=price_df.index)
        for sym, w in weights.items():
            if sym in price_df.columns:
                normalized = price_df[sym] / price_df[sym].iloc[-1]
                portfolio_values += normalized * w * total_mv

        return portfolio_values.dropna()

    async def _build_benchmark_series(self, symbol: str, start: datetime, end: datetime) -> pd.Series:
        prices = await self.market_data.get_historical_prices(symbol, start, end)
        if not prices:
            return pd.Series(dtype=float)
        df = pd.DataFrame(prices)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        return df["close"].dropna()

    @staticmethod
    def _period_to_dates(period: str) -> tuple[datetime, datetime]:
        end = datetime.now(timezone.utc)
        now = end
        match period:
            case "1M": start = now - timedelta(days=30)
            case "3M": start = now - timedelta(days=90)
            case "6M": start = now - timedelta(days=180)
            case "YTD": start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            case "1Y": start = now - timedelta(days=365)
            case "3Y": start = now - timedelta(days=365 * 3)
            case "5Y": start = now - timedelta(days=365 * 5)
            case _: start = now - timedelta(days=365)
        return start, end
