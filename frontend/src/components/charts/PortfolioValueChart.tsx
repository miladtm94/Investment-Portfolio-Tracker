"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import {
  ComposedChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Line
} from "recharts";
import { formatCurrency, formatPercent } from "@/lib/utils/formatters";
import { TrendingUp, Calendar } from "lucide-react";
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

type PeriodKey = (typeof PERIOD_OPTIONS)[number]["key"];
type HistoryPoint = { date: string; value: number; [key: string]: string | number | null };

interface BenchmarkMeta {
  key: string;
  symbol: string;
  label: string;
  return_pct?: number | null;
}

interface ValueHistoryResponse {
  data: HistoryPoint[];
  period: string;
  benchmarks?: BenchmarkMeta[];
}

const DEFAULT_BENCHMARKS: BenchmarkMeta[] = [
  { key: "sp500", symbol: "SPY", label: "S&P 500" },
  { key: "btc", symbol: "BTC", label: "BTC" },
];

const BENCHMARK_STYLES: Record<string, { color: string; dash?: string }> = {
  sp500: { color: "#10b981", dash: "4 4" },
  btc: { color: "#f59e0b", dash: "2 5" },
};

interface Props {
  period?: string;
  currency?: string;
}

function isPeriodKey(period?: string): period is PeriodKey {
  return PERIOD_OPTIONS.some((p) => p.key === period);
}

function normalizePeriod(period?: string): PeriodKey {
  return isPeriodKey(period) ? period : "1Y";
}

function benchmarkStyle(key: string) {
  return BENCHMARK_STYLES[key] ?? { color: "#a78bfa", dash: "4 4" };
}

function seriesLabel(key: string, benchmarks: BenchmarkMeta[]) {
  if (key === "value") return "Portfolio";
  return benchmarks.find((b) => b.key === key)?.label ?? key;
}

function ChartTooltip({
  active,
  payload,
  label,
  currency = "AUD",
  startValue = 0,
  benchmarks = [],
}: any) {
  if (!active || !payload?.length) return null;

  const rows = payload.filter((item: any) => item.value !== null && item.value !== undefined);
  if (!rows.length) return null;

  return (
    <div className="bg-gray-900 border border-gray-700 rounded-lg p-3 shadow-xl min-w-52">
      <p className="text-xs text-gray-400 mb-2">
        {new Date(label).toLocaleDateString("en-US", {
          year: "numeric", month: "short", day: "numeric",
        })}
      </p>
      <div className="space-y-1.5">
        {rows.map((item: any) => {
          const value = Number(item.value);
          const returnPct = startValue > 0 ? ((value / startValue) - 1) * 100 : null;
          return (
            <div key={item.dataKey} className="flex items-center justify-between gap-4 text-sm">
              <div className="flex items-center gap-2 text-gray-300">
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ backgroundColor: item.color }}
                />
                <span>{seriesLabel(String(item.dataKey), benchmarks)}</span>
              </div>
              <div className="text-right">
                <div className="font-semibold text-gray-100">
                  {formatCurrency(value, false, currency)}
                </div>
                {returnPct !== null && (
                  <div className={clsx(
                    "text-[11px]",
                    returnPct >= 0 ? "text-green-400" : "text-red-400"
                  )}>
                    {formatPercent(returnPct)}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** Return the right date format for X-axis labels based on the selected period. */
function formatXTick(dateStr: string, period: PeriodKey, dataLen: number): string {
  const d = new Date(dateStr);
  if (period === "1M") {
    // Daily ticks: "Mar 5"
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  }
  if (period === "3M" || period === "6M") {
    // Weekly-ish: "Mar 5"
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  }
  if (period === "YTD" || period === "1Y") {
    // Monthly: "Mar '26"
    return d.toLocaleDateString("en-US", { month: "short" }) +
      " '" + d.getFullYear().toString().slice(-2);
  }
  if (period === "3Y") {
    return d.getFullYear().toString();
  }
  if (period === "ALL" || period === "CUSTOM") {
    if (dataLen > 365) {
      // Yearly: "2025"
      return d.getFullYear().toString();
    }
    if (dataLen > 90) {
      // Monthly: "Mar '26"
      return d.toLocaleDateString("en-US", { month: "short" }) +
        " '" + d.getFullYear().toString().slice(-2);
    }
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  }
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/** Pick a good tick interval based on data length. */
function tickInterval(dataLen: number, period: PeriodKey): number | "preserveStartEnd" {
  if (dataLen <= 7) return 0; // show all
  if (period === "1M") return Math.max(Math.floor(dataLen / 6), 1);
  if (period === "3M") return Math.max(Math.floor(dataLen / 6), 1);
  if (period === "6M") return Math.max(Math.floor(dataLen / 6), 1);
  if (period === "YTD") return Math.max(Math.floor(dataLen / 6), 1);
  if (period === "1Y") return Math.max(Math.floor(dataLen / 6), 1);
  if (period === "3Y") return Math.max(Math.floor(dataLen / 6), 1);
  // ALL / CUSTOM
  if (dataLen > 1000) return Math.floor(dataLen / 5);
  if (dataLen > 365) return Math.floor(dataLen / 6);
  return Math.max(Math.floor(dataLen / 6), 1);
}

export function PortfolioValueChart({ period: _initialPeriod = "1Y", currency = "AUD" }: Props) {
  const [activePeriod, setActivePeriod] = useState<PeriodKey>(() => normalizePeriod(_initialPeriod));
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");
  const [appliedCustom, setAppliedCustom] = useState<{ start: string; end: string } | null>(null);
  const [visibleBenchmarks, setVisibleBenchmarks] = useState<Record<string, boolean>>({
    sp500: true,
    btc: true,
  });

  useEffect(() => {
    const nextPeriod = normalizePeriod(_initialPeriod);
    setActivePeriod(nextPeriod);
    if (nextPeriod !== "CUSTOM") {
      setAppliedCustom(null);
    }
  }, [_initialPeriod]);

  // Build query params
  const isCustom = activePeriod === "CUSTOM" && appliedCustom;
  const queryPeriod = isCustom ? "CUSTOM" : activePeriod;
  const queryParams = new URLSearchParams();
  if (isCustom) {
    queryParams.set("start_date", appliedCustom.start);
    queryParams.set("end_date", appliedCustom.end);
  } else {
    queryParams.set("period", activePeriod);
  }
  queryParams.set("benchmarks", "SPY,BTC");
  if (currency && currency !== "AUD") {
    queryParams.set("currency", currency);
  }

  const { data, isLoading, isFetching } = useQuery<ValueHistoryResponse>({
    queryKey: ["portfolio", "value-history", queryPeriod, appliedCustom, currency],
    queryFn: () =>
      api.get(`/analytics/portfolio-value-history?${queryParams.toString()}`).then((r) => r.data),
    staleTime: 60 * 1000,
    enabled: activePeriod !== "CUSTOM" || !!appliedCustom,
  });

  const chartData = data?.data ?? [];
  const benchmarks = data ? data.benchmarks ?? [] : DEFAULT_BENCHMARKS;
  const activeBenchmarks = benchmarks.filter((b) => visibleBenchmarks[b.key] !== false);
  const startVal = chartData[0]?.value ?? 0;
  const endVal = chartData[chartData.length - 1]?.value ?? 0;
  const change = endVal - startVal;
  const changePct = startVal > 0 ? ((change / startVal) * 100).toFixed(2) : "0.00";
  const isPositive = change >= 0;

  const handlePeriodChange = (p: PeriodKey) => {
    setActivePeriod(p);
    if (p !== "CUSTOM") {
      setAppliedCustom(null);
    }
  };

  const applyCustomRange = () => {
    if (customStart && customEnd) {
      setAppliedCustom({ start: customStart, end: customEnd });
    }
  };

  const toggleBenchmark = (key: string) => {
    setVisibleBenchmarks((prev) => ({ ...prev, [key]: prev[key] === false }));
  };

  return (
    <div className="card-glass p-6">
      {/* Header */}
      <div className="flex flex-col gap-4 mb-4 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <h3 className="text-base font-semibold text-gray-100 flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-blue-400" />
            Portfolio Value
          </h3>
          {chartData.length > 0 && (
            <div className="flex items-center gap-3 mt-1">
              <span className="text-lg font-bold text-gray-100">
                {formatCurrency(endVal, false, currency)}
              </span>
              <span className={`text-sm font-medium ${isPositive ? "text-green-400" : "text-red-400"}`}>
                {isPositive ? "+" : ""}{formatCurrency(change, false, currency)} ({isPositive ? "+" : ""}{changePct}%)
              </span>
            </div>
          )}
        </div>

        {/* Period Tabs */}
        <div className="flex flex-wrap items-center gap-1 bg-gray-800/60 rounded-lg p-0.5 border border-gray-700/50">
          {PERIOD_OPTIONS.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => handlePeriodChange(key)}
              className={clsx(
                "px-2.5 py-1 text-xs font-medium rounded-md transition-all",
                activePeriod === key
                  ? "bg-blue-600 text-white shadow-sm"
                  : "text-gray-400 hover:text-gray-200 hover:bg-gray-700/50"
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {benchmarks.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 mb-4">
          {benchmarks.map((benchmark) => {
            const style = benchmarkStyle(benchmark.key);
            const isVisible = visibleBenchmarks[benchmark.key] !== false;
            return (
              <button
                key={benchmark.key}
                type="button"
                onClick={() => toggleBenchmark(benchmark.key)}
                className={clsx(
                  "flex items-center gap-2 rounded-md border px-2.5 py-1 text-xs font-medium transition-colors",
                  isVisible
                    ? "border-gray-700 bg-gray-800/70 text-gray-200"
                    : "border-gray-800 bg-gray-900/40 text-gray-500"
                )}
              >
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ backgroundColor: isVisible ? style.color : "#4b5563" }}
                />
                <span>{benchmark.label}</span>
                {typeof benchmark.return_pct === "number" && (
                  <span className={benchmark.return_pct >= 0 ? "text-green-400" : "text-red-400"}>
                    {formatPercent(benchmark.return_pct)}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      )}

      {/* Custom Date Range Picker */}
      {activePeriod === "CUSTOM" && (
        <div className="flex flex-wrap items-center gap-2 mb-4 text-xs">
          <Calendar className="w-3.5 h-3.5 text-gray-500" />
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
      )}

      {/* Chart */}
      {isLoading || (isFetching && chartData.length === 0) ? (
        <div className="h-52 bg-gray-800/50 rounded-lg animate-pulse" />
      ) : chartData.length === 0 ? (
        <div className="h-52 flex items-center justify-center text-gray-500 text-sm">
          No historical data available
        </div>
      ) : (
        <div className="relative">
          {isFetching && (
            <div className="absolute inset-0 bg-gray-950/30 rounded-lg z-10 flex items-center justify-center">
              <div className="w-5 h-5 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
            </div>
          )}
          <ResponsiveContainer width="100%" height={220}>
            <ComposedChart data={chartData} margin={{ top: 5, right: 5, left: 5, bottom: 5 }}>
              <defs>
                <linearGradient id="portfolioGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={isPositive ? "#3b82f6" : "#ef4444"} stopOpacity={0.3} />
                  <stop offset="95%" stopColor={isPositive ? "#3b82f6" : "#ef4444"} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" vertical={false} />
              <XAxis
                dataKey="date"
                tick={{ fill: "#6b7280", fontSize: 10 }}
                tickLine={false}
                axisLine={false}
                interval={tickInterval(chartData.length, activePeriod)}
                tickFormatter={(v) => formatXTick(v, activePeriod, chartData.length)}
              />
              <YAxis
                tick={{ fill: "#6b7280", fontSize: 10 }}
                tickLine={false}
                axisLine={false}
                tickFormatter={(v) =>
                  v >= 1_000_000
                    ? `$${(v / 1_000_000).toFixed(1)}M`
                    : v >= 1_000
                    ? `$${(v / 1_000).toFixed(0)}k`
                    : `$${v.toFixed(0)}`
                }
                width={55}
              />
              <Tooltip
                content={
                  <ChartTooltip
                    currency={currency}
                    startValue={startVal}
                    benchmarks={benchmarks}
                  />
                }
              />
              <Area
                type="monotone"
                dataKey="value"
                stroke={isPositive ? "#3b82f6" : "#ef4444"}
                strokeWidth={2}
                fill="url(#portfolioGradient)"
                dot={false}
                activeDot={{ r: 4, fill: isPositive ? "#3b82f6" : "#ef4444" }}
              />
              {activeBenchmarks.map((benchmark) => {
                const style = benchmarkStyle(benchmark.key);
                return (
                  <Line
                    key={benchmark.key}
                    type="monotone"
                    dataKey={benchmark.key}
                    name={benchmark.label}
                    stroke={style.color}
                    strokeWidth={2}
                    strokeDasharray={style.dash}
                    dot={false}
                    activeDot={{ r: 3, fill: style.color }}
                    connectNulls
                  />
                );
              })}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
