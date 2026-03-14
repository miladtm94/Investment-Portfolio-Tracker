"use client";

import { Bell, Search, RefreshCw } from "lucide-react";
import { usePortfolioSummary } from "@/lib/hooks/usePortfolio";
import { formatCurrency } from "@/lib/utils/formatters";
import { useQueryClient } from "@tanstack/react-query";
import { useCurrency } from "@/lib/context/CurrencyContext";
import clsx from "clsx";

export function TopBar() {
  const { data: portfolio } = usePortfolioSummary();
  const queryClient = useQueryClient();
  const { displayCurrency, toggleCurrency } = useCurrency();

  const refresh = () => {
    queryClient.invalidateQueries();
  };

  return (
    <header className="h-16 flex items-center justify-between px-6 border-b border-gray-800 bg-gray-900/50 backdrop-blur-sm">
      {/* Search */}
      <div className="flex items-center gap-2 bg-gray-800/60 border border-gray-700 rounded-lg px-3 py-2 w-64">
        <Search className="w-4 h-4 text-gray-500" />
        <input
          type="text"
          placeholder="Search assets..."
          className="bg-transparent text-sm text-gray-300 placeholder-gray-500 outline-none w-full"
        />
      </div>

      {/* Center: Net Worth Summary */}
      {portfolio && (
        <div className="hidden md:flex items-center gap-6 text-sm">
          <div className="text-center">
            <div className="text-xs text-gray-500">Net Worth</div>
            <div className="font-semibold text-gray-100">
              {formatCurrency(portfolio.total_market_value, false, displayCurrency)}
            </div>
          </div>
          <div className="w-px h-8 bg-gray-700" />
          <div className="text-center">
            <div className="text-xs text-gray-500">Unrealized P&L</div>
            <div className={`font-semibold ${portfolio.total_unrealized_gain >= 0 ? "text-green-400" : "text-red-400"}`}>
              {portfolio.total_unrealized_gain >= 0 ? "+" : ""}
              {formatCurrency(portfolio.total_unrealized_gain, false, displayCurrency)}
            </div>
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center gap-2">
        {/* Currency Toggle */}
        <button
          onClick={toggleCurrency}
          className="flex items-center h-9 rounded-lg border border-gray-700 overflow-hidden text-xs font-medium transition-colors"
          title={`Display in ${displayCurrency === "AUD" ? "USD" : "AUD"}`}
        >
          <span
            className={clsx(
              "px-2.5 py-2 transition-colors",
              displayCurrency === "AUD"
                ? "bg-blue-600 text-white"
                : "bg-gray-800 text-gray-500 hover:text-gray-300"
            )}
          >
            AUD
          </span>
          <span
            className={clsx(
              "px-2.5 py-2 transition-colors",
              displayCurrency === "USD"
                ? "bg-green-600 text-white"
                : "bg-gray-800 text-gray-500 hover:text-gray-300"
            )}
          >
            USD
          </span>
        </button>

        <button
          onClick={refresh}
          className="w-9 h-9 rounded-lg bg-gray-800 hover:bg-gray-700 border border-gray-700 flex items-center justify-center transition-colors"
          title="Refresh data"
        >
          <RefreshCw className="w-4 h-4 text-gray-400" />
        </button>
        <button className="w-9 h-9 rounded-lg bg-gray-800 hover:bg-gray-700 border border-gray-700 flex items-center justify-center transition-colors relative">
          <Bell className="w-4 h-4 text-gray-400" />
          <span className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-blue-500 rounded-full" />
        </button>
        <div className="w-9 h-9 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center cursor-pointer">
          <span className="text-xs font-bold text-white">U</span>
        </div>
      </div>
    </header>
  );
}
