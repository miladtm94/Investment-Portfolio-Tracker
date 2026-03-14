"use client";

import { useState } from "react";
import { useAnalytics } from "@/lib/hooks/useAnalytics";
import { PortfolioValueChart } from "@/components/charts/PortfolioValueChart";
import { AllocationPie } from "@/components/charts/AllocationPie";
import { RiskGauge } from "@/components/charts/RiskGauge";
import { MetricCard } from "@/components/ui/MetricCard";
import { formatPercent, formatNumber } from "@/lib/utils/formatters";
import { Activity, Shield, TrendingUp, BarChart3 } from "lucide-react";
import clsx from "clsx";

const PERIODS = ["1M", "3M", "6M", "YTD", "1Y", "3Y"] as const;
type Period = (typeof PERIODS)[number];

export default function AnalyticsPage() {
  const [period, setPeriod] = useState<Period>("1Y");
  const { data, isLoading } = useAnalytics(period);

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-100">Analytics</h1>
        <div className="flex items-center gap-1 bg-gray-900 rounded-lg p-1 border border-gray-800">
          {PERIODS.map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={clsx(
                "px-3 py-1 text-sm rounded-md transition-all",
                p === period
                  ? "bg-blue-600 text-white"
                  : "text-gray-400 hover:text-gray-200"
              )}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      {/* Performance Metrics */}
      <div>
        <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-3 flex items-center gap-2">
          <TrendingUp className="w-4 h-4" /> Performance
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <MetricCard
            title="Total Return"
            value={formatPercent(data?.performance.total_return_pct ?? 0)}
            subtitle={`vs ${formatPercent(data?.performance.benchmark_return_pct ?? 0)} benchmark`}
            loading={isLoading}
            positive={(data?.performance.total_return_pct ?? 0) >= 0}
          />
          <MetricCard
            title="Annualized Return"
            value={formatPercent(data?.performance.annualized_return_pct ?? 0)}
            subtitle="CAGR"
            loading={isLoading}
            positive={(data?.performance.annualized_return_pct ?? 0) >= 0}
          />
          <MetricCard
            title="Alpha"
            value={formatPercent(data?.performance.alpha ?? 0)}
            subtitle="vs benchmark"
            loading={isLoading}
            positive={(data?.performance.alpha ?? 0) >= 0}
          />
          <MetricCard
            title="Beta"
            value={formatNumber(data?.performance.beta ?? 1, 2)}
            subtitle="market sensitivity"
            loading={isLoading}
          />
        </div>
      </div>

      {/* Risk Metrics */}
      <div>
        <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider mb-3 flex items-center gap-2">
          <Shield className="w-4 h-4" /> Risk
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <MetricCard
            title="Volatility (Ann.)"
            value={formatPercent(data?.risk.volatility_annual_pct ?? 0)}
            subtitle="annualized std dev"
            loading={isLoading}
          />
          <MetricCard
            title="Sharpe Ratio"
            value={formatNumber(data?.risk.sharpe_ratio ?? 0, 2)}
            subtitle="risk-adjusted return"
            loading={isLoading}
            positive={(data?.risk.sharpe_ratio ?? 0) > 1}
          />
          <MetricCard
            title="Sortino Ratio"
            value={formatNumber(data?.risk.sortino_ratio ?? 0, 2)}
            subtitle="downside-adjusted"
            loading={isLoading}
            positive={(data?.risk.sortino_ratio ?? 0) > 1}
          />
          <MetricCard
            title="Max Drawdown"
            value={formatPercent(data?.risk.max_drawdown_pct ?? 0)}
            subtitle={`${data?.risk.max_drawdown_duration_days ?? 0} day recovery`}
            loading={isLoading}
            positive={false}
          />
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mt-4">
          <MetricCard
            title="VaR (95%)"
            value={formatPercent(data?.risk.var_95_pct ?? 0)}
            subtitle="1-day at 95% confidence"
            loading={isLoading}
            compact
          />
          <MetricCard
            title="CVaR (95%)"
            value={formatPercent(data?.risk.cvar_95_pct ?? 0)}
            subtitle="expected shortfall"
            loading={isLoading}
            compact
          />
          <MetricCard
            title="Calmar Ratio"
            value={formatNumber(data?.risk.calmar_ratio ?? 0, 2)}
            subtitle="return / max drawdown"
            loading={isLoading}
            compact
          />
        </div>
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <PortfolioValueChart period={period} />
        <AllocationPie
          data={data?.allocation.by_asset_class}
          title="Asset Class Allocation"
        />
      </div>

      {/* Top Holdings */}
      <div className="card-glass p-6">
        <h2 className="text-lg font-semibold text-gray-100 mb-4 flex items-center gap-2">
          <BarChart3 className="w-5 h-5 text-blue-400" />
          Top Holdings by Weight
        </h2>
        <div className="space-y-3">
          {(data?.allocation.top_holdings ?? []).slice(0, 8).map((h) => (
            <div key={h.symbol} className="flex items-center gap-3">
              <div className="w-16 text-xs text-gray-400 font-mono">{h.symbol}</div>
              <div className="flex-1 bg-gray-800 rounded-full h-2">
                <div
                  className="h-2 rounded-full bg-gradient-to-r from-blue-500 to-blue-400"
                  style={{ width: `${Math.min(h.weight_pct, 100)}%` }}
                />
              </div>
              <div className="w-14 text-right text-sm font-medium text-gray-200">
                {h.weight_pct.toFixed(1)}%
              </div>
              <div
                className={clsx(
                  "w-20 text-right text-xs",
                  h.unrealized_gain_pct >= 0 ? "text-green-400" : "text-red-400"
                )}
              >
                {formatPercent(h.unrealized_gain_pct)}
              </div>
            </div>
          ))}
        </div>
        <div className="mt-4 pt-4 border-t border-gray-800 flex items-center justify-between text-sm">
          <span className="text-gray-400">Concentration (HHI)</span>
          <span className="font-medium text-gray-200">
            {((data?.allocation.concentration_score ?? 0) * 100).toFixed(1)}% •{" "}
            <span className={(data?.allocation.diversification_score ?? 0) > 0.7 ? "text-green-400" : "text-yellow-400"}>
              {((data?.allocation.diversification_score ?? 0) * 100).toFixed(0)}% Diversified
            </span>
          </span>
        </div>
      </div>
    </div>
  );
}
