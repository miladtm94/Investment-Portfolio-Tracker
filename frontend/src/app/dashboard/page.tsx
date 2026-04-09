"use client";

import { usePortfolioSummary } from "@/lib/hooks/usePortfolio";
import { useAnalytics } from "@/lib/hooks/useAnalytics";
import { PortfolioValueChart } from "@/components/charts/PortfolioValueChart";
import { AllocationPie } from "@/components/charts/AllocationPie";
import { MetricCard } from "@/components/ui/MetricCard";
import { HoldingsTable } from "@/components/portfolio/HoldingsTable";
import { formatCurrency, formatPercent, formatNumber } from "@/lib/utils/formatters";
import {
  TrendingUp, TrendingDown, DollarSign, Activity,
  BarChart3, Shield, Zap, ArrowUpRight
} from "lucide-react";
import { useCurrency } from "@/lib/context/CurrencyContext";

export default function DashboardPage() {
  const { displayCurrency } = useCurrency();
  const ccy = displayCurrency;
  const isToggled = ccy !== "AUD";
  const { data: portfolio, isLoading: portfolioLoading } = usePortfolioSummary(undefined, ccy);
  const { data: analytics, isLoading: analyticsLoading } = useAnalytics("1Y", "SPY", ccy);

  const isPositive = (portfolio?.total_unrealized_gain ?? 0) >= 0;

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">Portfolio Dashboard</h1>
          <p className="text-gray-400 text-sm mt-1">
            {portfolio && `As of ${new Date(portfolio.as_of).toLocaleDateString("en-US", { dateStyle: "long" })}`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 text-xs text-green-400 bg-green-400/10 px-2.5 py-1.5 rounded-full border border-green-400/20">
            <div className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
            Live
          </div>
        </div>
      </div>

      {/* Key Metrics Row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard
          title="Total Net Worth"
          value={portfolioLoading ? null : formatCurrency(portfolio?.total_market_value ?? 0, false, ccy)}
          subtitle="Market Value"
          icon={<DollarSign className="w-4 h-4" />}
          loading={portfolioLoading}
          accent="blue"
          highlighted={isToggled}
        />
        <MetricCard
          title="Unrealized P&L"
          value={portfolioLoading ? null : formatCurrency(portfolio?.total_unrealized_gain ?? 0, false, ccy)}
          subtitle={portfolioLoading ? "" : formatPercent(portfolio?.total_unrealized_gain_pct ?? 0)}
          icon={isPositive ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
          positive={isPositive}
          loading={portfolioLoading}
          highlighted={isToggled}
        />
        <MetricCard
          title="Annual Return"
          value={analyticsLoading ? null : formatPercent(analytics?.performance.total_return_pct ?? 0)}
          subtitle={`Alpha: ${formatPercent(analytics?.performance.alpha ?? 0)}`}
          icon={<Activity className="w-4 h-4" />}
          positive={(analytics?.performance.total_return_pct ?? 0) >= 0}
          loading={analyticsLoading}
        />
        <MetricCard
          title="Sharpe Ratio"
          value={analyticsLoading ? null : formatNumber(analytics?.risk.sharpe_ratio ?? 0, 2)}
          subtitle={`Volatility: ${formatPercent(analytics?.risk.volatility_annual_pct ?? 0)}`}
          icon={<Shield className="w-4 h-4" />}
          loading={analyticsLoading}
        />
      </div>

      {/* Secondary Metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard
          title="Realized Gains (ST)"
          value={portfolioLoading ? null : formatCurrency(portfolio?.total_realized_gain_short ?? 0, false, ccy)}
          subtitle="Short-term"
          icon={<BarChart3 className="w-4 h-4" />}
          compact
          loading={portfolioLoading}
          highlighted={isToggled}
        />
        <MetricCard
          title="Realized Gains (LT)"
          value={portfolioLoading ? null : formatCurrency(portfolio?.total_realized_gain_long ?? 0, false, ccy)}
          subtitle="Long-term"
          icon={<BarChart3 className="w-4 h-4" />}
          compact
          loading={portfolioLoading}
          highlighted={isToggled}
        />
        <MetricCard
          title="Dividend Income"
          value={portfolioLoading ? null : formatCurrency(portfolio?.dividend_income ?? 0, false, ccy)}
          subtitle="This year"
          icon={<Zap className="w-4 h-4" />}
          compact
          loading={portfolioLoading}
          highlighted={isToggled}
        />
        <MetricCard
          title="Staking Income"
          value={portfolioLoading ? null : formatCurrency(portfolio?.staking_income ?? 0, false, ccy)}
          subtitle="Crypto rewards"
          icon={<ArrowUpRight className="w-4 h-4" />}
          compact
          loading={portfolioLoading}
          highlighted={isToggled}
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <PortfolioValueChart currency={ccy} />
        </div>
        <div>
          <AllocationPie data={analytics?.allocation.by_asset_class} />
        </div>
      </div>

      {/* Holdings Table */}
      <div className="card-glass p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-100">Holdings</h2>
        </div>
        <HoldingsTable holdings={portfolio?.holdings ?? []} loading={portfolioLoading} currency={ccy} />
      </div>
    </div>
  );
}
