"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer
} from "recharts";
import { formatCurrency } from "@/lib/utils/formatters";
import { TrendingUp, Calendar } from "lucide-react";
import clsx from "clsx";

const PERIOD_OPTIONS = [
  { key: "1M", label: "1M" },
  { key: "6M", label: "6M" },
  { key: "1Y", label: "1Y" },
  { key: "ALL", label: "All" },
  { key: "CUSTOM", label: "Custom" },
] as const;

type PeriodKey = (typeof PERIOD_OPTIONS)[number]["key"];

interface Props {
  period?: string;
  currency?: string;
}

function ChartTooltip({ active, payload, label, currency = "AUD" }: any) {
  if (active && payload && payload.length) {
    return (
      <div className="bg-gray-900 border border-gray-700 rounded-lg p-3 shadow-xl">
        <p className="text-xs text-gray-400 mb-1">
          {new Date(label).toLocaleDateString("en-US", {
            year: "numeric", month: "short", day: "numeric",
          })}
        </p>
        <p className="text-sm font-semibold text-gray-100">
          {formatCurrency(payload[0].value, false, currency)}
        </p>
      </div>
    );
  }
  return null;
}

/** Return the right date format for X-axis labels based on the selected period. */
function formatXTick(dateStr: string, period: PeriodKey, dataLen: number): string {
  const d = new Date(dateStr);
  if (period === "1M") {
    // Daily ticks: "Mar 5"
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  }
  if (period === "6M") {
    // Weekly-ish: "Mar 5"
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  }
  if (period === "1Y") {
    // Monthly: "Mar '26"
    return d.toLocaleDateString("en-US", { month: "short" }) +
      " '" + d.getFullYear().toString().slice(-2);
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
  if (period === "6M") return Math.max(Math.floor(dataLen / 6), 1);
  if (period === "1Y") return Math.max(Math.floor(dataLen / 6), 1);
  // ALL / CUSTOM
  if (dataLen > 1000) return Math.floor(dataLen / 5);
  if (dataLen > 365) return Math.floor(dataLen / 6);
  return Math.max(Math.floor(dataLen / 6), 1);
}

export function PortfolioValueChart({ period: _initialPeriod = "1Y", currency = "AUD" }: Props) {
  const [activePeriod, setActivePeriod] = useState<PeriodKey>("1Y");
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");
  const [appliedCustom, setAppliedCustom] = useState<{ start: string; end: string } | null>(null);

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
  if (currency && currency !== "AUD") {
    queryParams.set("currency", currency);
  }

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ["portfolio", "value-history", queryPeriod, appliedCustom, currency],
    queryFn: () =>
      api.get(`/analytics/portfolio-value-history?${queryParams.toString()}`).then((r) => r.data),
    staleTime: 60 * 1000,
    enabled: activePeriod !== "CUSTOM" || !!appliedCustom,
  });

  const chartData = data?.data ?? [];
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

  return (
    <div className="card-glass p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
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
        <div className="flex items-center gap-1 bg-gray-800/60 rounded-lg p-0.5 border border-gray-700/50">
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

      {/* Custom Date Range Picker */}
      {activePeriod === "CUSTOM" && (
        <div className="flex items-center gap-2 mb-4 text-xs">
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
            <AreaChart data={chartData} margin={{ top: 5, right: 5, left: 5, bottom: 5 }}>
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
              <Tooltip content={<ChartTooltip currency={currency} />} />
              <Area
                type="monotone"
                dataKey="value"
                stroke={isPositive ? "#3b82f6" : "#ef4444"}
                strokeWidth={2}
                fill="url(#portfolioGradient)"
                dot={false}
                activeDot={{ r: 4, fill: isPositive ? "#3b82f6" : "#ef4444" }}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
