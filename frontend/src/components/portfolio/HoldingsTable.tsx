"use client";

import clsx from "clsx";
import { formatCurrency, formatPercent } from "@/lib/utils/formatters";

interface Holding {
  symbol: string;
  name: string;
  asset_class: string;
  quantity: number;
  average_cost_basis?: number;
  market_value?: number;
  weight_pct?: number;
  unrealized_gain?: number;
  unrealized_gain_pct?: number;
}

interface Props {
  holdings: Holding[];
  loading?: boolean;
}

const ASSET_CLASS_COLORS: Record<string, string> = {
  EQUITY: "text-blue-400 bg-blue-400/10",
  CRYPTO: "text-purple-400 bg-purple-400/10",
  ETF: "text-green-400 bg-green-400/10",
  MUTUAL_FUND: "text-yellow-400 bg-yellow-400/10",
  BOND: "text-gray-400 bg-gray-400/10",
  CASH: "text-teal-400 bg-teal-400/10",
};

export function HoldingsTable({ holdings, loading = false }: Props) {
  if (loading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-12 bg-gray-800/50 rounded-lg animate-pulse" />
        ))}
      </div>
    );
  }

  if (!holdings.length) {
    return (
      <div className="text-center py-8 text-gray-500 text-sm">
        No holdings found. Add accounts and import transactions to get started.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs text-gray-500 uppercase tracking-wider border-b border-gray-800">
            <th className="text-left py-2 pr-4">Asset</th>
            <th className="text-right py-2 pr-4">Quantity</th>
            <th className="text-right py-2 pr-4">Avg Cost</th>
            <th className="text-right py-2 pr-4">Market Value</th>
            <th className="text-right py-2 pr-4">Weight</th>
            <th className="text-right py-2">P&L</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-800/50">
          {holdings.map((h) => {
            const isPositive = (h.unrealized_gain ?? 0) >= 0;
            const classStyle = ASSET_CLASS_COLORS[h.asset_class] || ASSET_CLASS_COLORS.EQUITY;

            return (
              <tr key={h.symbol} className="hover:bg-gray-800/30 transition-colors">
                <td className="py-3 pr-4">
                  <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 rounded-lg bg-gray-800 border border-gray-700 flex items-center justify-center text-xs font-bold text-gray-300">
                      {h.symbol.slice(0, 2)}
                    </div>
                    <div>
                      <div className="font-medium text-gray-100">{h.symbol}</div>
                      <div className="text-xs text-gray-500 truncate max-w-[120px]">{h.name}</div>
                    </div>
                    <span className={clsx("text-xs px-1.5 py-0.5 rounded ml-1 hidden sm:block", classStyle)}>
                      {h.asset_class}
                    </span>
                  </div>
                </td>
                <td className="py-3 pr-4 text-right font-mono text-gray-300">
                  {h.quantity.toFixed(h.quantity < 1 ? 6 : 4)}
                </td>
                <td className="py-3 pr-4 text-right font-mono text-gray-400">
                  {h.average_cost_basis ? formatCurrency(h.average_cost_basis) : "—"}
                </td>
                <td className="py-3 pr-4 text-right font-mono font-medium text-gray-100">
                  {h.market_value ? formatCurrency(h.market_value) : "—"}
                </td>
                <td className="py-3 pr-4 text-right">
                  {h.weight_pct !== undefined ? (
                    <div className="flex items-center justify-end gap-2">
                      <div className="w-12 bg-gray-800 rounded-full h-1.5">
                        <div
                          className="h-1.5 rounded-full bg-blue-500"
                          style={{ width: `${Math.min(h.weight_pct, 100)}%` }}
                        />
                      </div>
                      <span className="text-gray-400 text-xs w-10 text-right">
                        {h.weight_pct.toFixed(1)}%
                      </span>
                    </div>
                  ) : "—"}
                </td>
                <td className="py-3 text-right">
                  {h.unrealized_gain !== undefined ? (
                    <div>
                      <div className={clsx("font-mono font-medium", isPositive ? "text-green-400" : "text-red-400")}>
                        {isPositive ? "+" : ""}{formatCurrency(h.unrealized_gain)}
                      </div>
                      <div className={clsx("text-xs", isPositive ? "text-green-500" : "text-red-500")}>
                        {isPositive ? "+" : ""}{formatPercent(h.unrealized_gain_pct ?? 0)}
                      </div>
                    </div>
                  ) : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
