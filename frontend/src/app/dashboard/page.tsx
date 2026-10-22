"use client";

import { useState } from "react";
import { usePortfolioSummary } from "@/lib/hooks/usePortfolio";
import { PortfolioValueChart } from "@/components/charts/PortfolioValueChart";
import { AllocationPie } from "@/components/charts/AllocationPie";
import { MetricCard } from "@/components/ui/MetricCard";
import { HoldingsTable } from "@/components/portfolio/HoldingsTable";
import { formatCurrency, formatPercent } from "@/lib/utils/formatters";
import {
  TrendingUp, TrendingDown, DollarSign,
  BarChart3, Wallet, Zap, Scale, PieChart, Download
} from "lucide-react";
import { useCurrency } from "@/lib/context/CurrencyContext";
import clsx from "clsx";

const PERIOD_OPTIONS = [
  { key: "1M", label: "1M" },
  { key: "3M", label: "3M" },
  { key: "6M", label: "6M" },
  { key: "YTD", label: "YTD" },
  { key: "1Y", label: "1Y" },
  { key: "3Y", label: "3Y" },
  { key: "ALL", label: "All" },
  { key: "CUSTOM", label: "Custom" },
] as const;

const toDateInput = (date: Date) => date.toISOString().slice(0, 10);

const defaultCustomRange = () => {
  const end = new Date();
  const start = new Date(end);
  start.setFullYear(start.getFullYear() - 1);
  return { start: toDateInput(start), end: toDateInput(end) };
};

const csvCell = (value: unknown) => {
  const raw = value == null ? "" : String(value);
  return `"${raw.replace(/"/g, '""')}"`;
};

const csvNumber = (value: number | null | undefined, decimals = 2) =>
  value == null
    ? ""
    : new Intl.NumberFormat("en-AU", {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      }).format(value);

const csvQuantity = (value: number | null | undefined) => {
  if (value == null) return "";
  const decimals = Math.abs(value) < 1 ? 8 : value % 1 === 0 ? 0 : 4;
  return csvNumber(value, decimals);
};

const csvMarketLabel = (holding: { symbol: string; asset_class: string; original_currency?: string; exchange?: string | null }) => {
  const exchange = holding.exchange?.trim().toUpperCase();
  if (exchange) return exchange;
  if (holding.asset_class === "CRYPTO") return "Crypto";
  const symbol = holding.symbol.toUpperCase();
  if (symbol.endsWith(".AX") || holding.original_currency === "AUD") return "ASX";
  if (holding.original_currency === "USD") return "US";
  return holding.original_currency || "Market";
};

export default function DashboardPage() {
  const { displayCurrency } = useCurrency();
  const ccy = displayCurrency;
  const isToggled = ccy !== "AUD";
  const [period, setPeriod] = useState("1Y");
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");
  const [appliedCustom, setAppliedCustom] = useState<{ start: string; end: string } | null>(null);
  const customRange = period === "CUSTOM" ? appliedCustom : null;
  const { data: portfolio, isLoading: portfolioLoading } = usePortfolioSummary(
    undefined,
    ccy,
    period,
    customRange?.start,
    customRange?.end,
  );

  const periodPnl = portfolio?.period_pnl ?? 0;
  const periodIncome = portfolio?.period_income ?? 0;
  const periodRealized = portfolio?.period_realized_gain ?? 0;
  const periodRealizedShort = portfolio?.period_realized_gain_short ?? 0;
  const periodRealizedLong = portfolio?.period_realized_gain_long ?? 0;
  const totalPnlPositive = periodPnl >= 0;
  const unrealizedPositive = (portfolio?.total_unrealized_gain ?? 0) >= 0;
  const realizedPositive = periodRealized >= 0;
  const allocationByAssetClass = (portfolio?.holdings ?? []).reduce((acc: Record<string, number>, holding) => {
    const marketValue = holding.market_value ?? 0;
    if (!marketValue) return acc;
    const key = holding.asset_class || "Other";
    acc[key] = (acc[key] ?? 0) + marketValue;
    return acc;
  }, {});
  const allocationTotal = Object.values(allocationByAssetClass).reduce((sum, value) => sum + value, 0);
  const allocationPctByAssetClass = Object.fromEntries(
    Object.entries(allocationByAssetClass).map(([key, value]) => [
      key,
      allocationTotal > 0 ? (value / allocationTotal) * 100 : 0,
    ])
  );
  const periodReturn = portfolio?.period_pnl_pct ?? 0;
  const periodLabel = PERIOD_OPTIONS.find((p) => p.key === period)?.label ?? period;
  const effectiveStartLabel = portfolio?.period_start
    ? new Date(portfolio.period_start).toLocaleDateString("en-AU")
    : null;
  const effectivePeriodLabel = customRange
    ? `${new Date(customRange.start).toLocaleDateString("en-AU")} – ${new Date(customRange.end).toLocaleDateString("en-AU")}`
    : effectiveStartLabel
    ? `${periodLabel} from ${effectiveStartLabel}`
    : periodLabel;

  const selectPeriod = (key: string) => {
    if (key === "CUSTOM") {
      const range = appliedCustom ?? defaultCustomRange();
      setCustomStart(range.start);
      setCustomEnd(range.end);
      setAppliedCustom(range);
      setPeriod("CUSTOM");
      return;
    }
    setPeriod(key);
  };

  const applyCustomRange = () => {
    if (!customStart || !customEnd) return;
    setAppliedCustom({ start: customStart, end: customEnd });
    setPeriod("CUSTOM");
  };

  const downloadHoldingsCsv = () => {
    const holdings = portfolio?.holdings ?? [];
    if (!holdings.length) return;

    const headers = [
      "Symbol",
      "Name",
      "Asset Class",
      "Market",
      "Quantity",
      `Last Price (${ccy})`,
      `Market Value (${ccy})`,
      `Average Cost (${ccy})`,
      `Cost Basis (${ccy})`,
      `Unrealized P&L (${ccy})`,
      "Unrealized Return %",
      "Period Price Return %",
      `Period Income (${ccy})`,
      "Weight %",
      "Display Currency",
      "Market Price Currency",
    ];
    const rows = holdings.map((holding) => [
      holding.symbol,
      holding.name,
      holding.asset_class,
      csvMarketLabel(holding),
      csvQuantity(holding.quantity),
      holding.last_price == null ? "" : formatCurrency(holding.last_price, false, ccy),
      holding.market_value == null ? "" : formatCurrency(holding.market_value, false, ccy),
      holding.average_cost_basis == null ? "" : formatCurrency(holding.average_cost_basis, false, ccy),
      holding.total_cost_basis == null ? "" : formatCurrency(holding.total_cost_basis, false, ccy),
      holding.unrealized_gain == null ? "" : formatCurrency(holding.unrealized_gain, false, ccy),
      holding.unrealized_gain_pct == null ? "" : formatPercent(holding.unrealized_gain_pct),
      holding.period_price_return_pct == null ? "" : formatPercent(holding.period_price_return_pct),
      holding.period_income == null ? "" : formatCurrency(holding.period_income, false, ccy),
      holding.weight_pct == null ? "" : formatPercent(holding.weight_pct, 2),
      ccy,
      holding.original_currency,
    ]);
    const csv = [headers, ...rows].map((row) => row.map(csvCell).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `portfolio-holdings-${toDateInput(new Date())}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Page Header */}
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">Portfolio Dashboard</h1>
          <p className="text-gray-400 text-sm mt-1">
            {portfolio && `Snapshot as of ${new Date(portfolio.as_of).toLocaleDateString("en-US", { dateStyle: "long" })}; performance period ${effectivePeriodLabel}`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex flex-wrap items-center gap-1 bg-gray-800/60 rounded-lg p-0.5 border border-gray-700/50">
            {PERIOD_OPTIONS.map(({ key, label }) => (
              <button
                key={key}
                type="button"
                onClick={() => selectPeriod(key)}
                className={clsx(
                  "px-2.5 py-1 text-xs font-medium rounded-md transition-all",
                  period === key
                    ? "bg-blue-600 text-white shadow-sm"
                    : "text-gray-400 hover:text-gray-200 hover:bg-gray-700/50"
                )}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-1.5 text-xs text-green-400 bg-green-400/10 px-2.5 py-1.5 rounded-full border border-green-400/20">
            <div className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
            Live
          </div>
        </div>
      </div>

      {period === "CUSTOM" && (
        <div className="card-glass px-4 py-3">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-gray-400 font-medium">Custom range</span>
            <input
              type="date"
              value={customStart}
              onChange={(e) => setCustomStart(e.target.value)}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-gray-300 outline-none focus:border-blue-500"
            />
            <span className="text-gray-500">to</span>
            <input
              type="date"
              value={customEnd}
              onChange={(e) => setCustomEnd(e.target.value)}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-gray-300 outline-none focus:border-blue-500"
            />
            <button
              type="button"
              onClick={applyCustomRange}
              disabled={!customStart || !customEnd}
              className={clsx(
                "px-3 py-1 rounded font-medium transition-colors",
                customStart && customEnd
                  ? "bg-blue-600 text-white hover:bg-blue-500"
                  : "bg-gray-700 text-gray-500 cursor-not-allowed"
              )}
            >
              Apply
            </button>
          </div>
        </div>
      )}

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
          title="Period P&L"
          value={portfolioLoading ? null : formatCurrency(periodPnl, false, ccy)}
          subtitle={portfolioLoading ? "" : `${formatPercent(portfolio?.period_pnl_pct ?? 0)} incl. income/closed gains`}
          icon={totalPnlPositive ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
          positive={totalPnlPositive}
          loading={portfolioLoading}
          highlighted={isToggled}
        />
        <MetricCard
          title="Unrealized P&L"
          value={portfolioLoading ? null : formatCurrency(portfolio?.total_unrealized_gain ?? 0, false, ccy)}
          subtitle={portfolioLoading ? "" : formatPercent(portfolio?.total_unrealized_gain_pct ?? 0)}
          icon={unrealizedPositive ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
          positive={unrealizedPositive}
          loading={portfolioLoading}
          highlighted={isToggled}
        />
        <MetricCard
          title="Period Income"
          value={portfolioLoading ? null : formatCurrency(periodIncome, false, ccy)}
          subtitle={periodIncome === 0
            ? "No settled income in active accounts"
            : "Dividends, distributions, rewards • active accounts"}
          icon={<Wallet className="w-4 h-4" />}
          positive={periodIncome >= 0}
          loading={portfolioLoading}
          highlighted={isToggled}
        />
      </div>

      {/* Secondary Metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard
          title="Period Realized P&L"
          value={portfolioLoading ? null : formatCurrency(periodRealized, false, ccy)}
          subtitle="Closed positions"
          icon={<BarChart3 className="w-4 h-4" />}
          positive={realizedPositive}
          compact
          loading={portfolioLoading}
          highlighted={isToggled}
        />
        <MetricCard
          title="Cost Basis"
          value={portfolioLoading ? null : formatCurrency(portfolio?.total_cost_basis ?? 0, false, ccy)}
          subtitle="Open positions"
          icon={<Scale className="w-4 h-4" />}
          compact
          loading={portfolioLoading}
          highlighted={isToggled}
        />
        <MetricCard
          title="Period Return"
          value={portfolioLoading ? null : formatPercent(periodReturn)}
          subtitle={`${effectivePeriodLabel}; includes income/closed gains`}
          icon={<Zap className="w-4 h-4" />}
          positive={periodReturn >= 0}
          compact
          loading={portfolioLoading}
        />
        <MetricCard
          title="Tax Split"
          value={portfolioLoading ? null : `${formatCurrency(periodRealizedShort, true, ccy)} / ${formatCurrency(periodRealizedLong, true, ccy)}`}
          subtitle="ST / LT realized"
          icon={<PieChart className="w-4 h-4" />}
          compact
          loading={portfolioLoading}
          highlighted={isToggled}
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <PortfolioValueChart
            period={period}
            currency={ccy}
            onPeriodChange={setPeriod}
            showPeriodSelector={false}
            customStartDate={customRange?.start}
            customEndDate={customRange?.end}
          />
        </div>
        <div>
          <AllocationPie data={allocationPctByAssetClass} />
        </div>
      </div>

      {/* Holdings Table */}
      <div className="card-glass p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-100">Holdings</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              Current quantities with {effectivePeriodLabel} income where available.
            </p>
          </div>
          <button
            type="button"
            onClick={downloadHoldingsCsv}
            disabled={!portfolio?.holdings?.length}
            className={clsx(
              "inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-medium transition-colors",
              portfolio?.holdings?.length
                ? "border-gray-700 bg-gray-800/70 text-gray-200 hover:bg-gray-700"
                : "border-gray-800 bg-gray-900/40 text-gray-600 cursor-not-allowed"
            )}
          >
            <Download className="h-3.5 w-3.5" />
            Download CSV
          </button>
        </div>
        <HoldingsTable
          holdings={portfolio?.holdings ?? []}
          loading={portfolioLoading}
          currency={ccy}
          periodLabel={effectivePeriodLabel}
          showPeriodMetrics
        />
      </div>
    </div>
  );
}
