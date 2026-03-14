"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer
} from "recharts";
import { formatCurrency } from "@/lib/utils/formatters";
import { TrendingUp } from "lucide-react";

interface Props {
  period?: string;
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    return (
      <div className="bg-gray-900 border border-gray-700 rounded-lg p-3 shadow-xl">
        <p className="text-xs text-gray-400 mb-1">{label}</p>
        <p className="text-sm font-semibold text-gray-100">
          {formatCurrency(payload[0].value)}
        </p>
      </div>
    );
  }
  return null;
};

export function PortfolioValueChart({ period = "1Y" }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ["portfolio", "value-history", period],
    queryFn: () =>
      api.get(`/analytics/portfolio-value-history?period=${period}`).then((r) => r.data),
    staleTime: 60 * 1000,
  });

  const chartData = data?.data ?? [];
  const startVal = chartData[0]?.value ?? 0;
  const endVal = chartData[chartData.length - 1]?.value ?? 0;
  const change = endVal - startVal;
  const changePct = startVal > 0 ? ((change / startVal) * 100).toFixed(2) : "0.00";
  const isPositive = change >= 0;

  return (
    <div className="card-glass p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h3 className="text-base font-semibold text-gray-100 flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-blue-400" />
            Portfolio Value
          </h3>
          <div className="flex items-center gap-3 mt-1">
            <span className="text-lg font-bold text-gray-100">
              {formatCurrency(endVal)}
            </span>
            <span className={`text-sm font-medium ${isPositive ? "text-green-400" : "text-red-400"}`}>
              {isPositive ? "+" : ""}{formatCurrency(change)} ({isPositive ? "+" : ""}{changePct}%)
            </span>
          </div>
        </div>
        <div className="text-xs text-gray-500 bg-gray-800 px-2 py-1 rounded">{period}</div>
      </div>

      {isLoading ? (
        <div className="h-48 bg-gray-800/50 rounded-lg animate-pulse" />
      ) : chartData.length === 0 ? (
        <div className="h-48 flex items-center justify-center text-gray-500 text-sm">
          No historical data available
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={200}>
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
              interval="preserveStartEnd"
              tickFormatter={(v) => new Date(v).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
            />
            <YAxis
              tick={{ fill: "#6b7280", fontSize: 10 }}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
              width={50}
            />
            <Tooltip content={<CustomTooltip />} />
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
      )}
    </div>
  );
}
