"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { Bell, Search, RefreshCw, Check, AlertCircle } from "lucide-react";
import { usePortfolioSummary } from "@/lib/hooks/usePortfolio";
import { formatCurrency } from "@/lib/utils/formatters";
import { useQueryClient } from "@tanstack/react-query";
import { useCurrency } from "@/lib/context/CurrencyContext";
import { api } from "@/lib/api/client";
import clsx from "clsx";

type RefreshPhase = "idle" | "syncing" | "fetching" | "done" | "error";

export function TopBar() {
  const { displayCurrency, toggleCurrency } = useCurrency();
  const { data: portfolio } = usePortfolioSummary(undefined, displayCurrency);
  const queryClient = useQueryClient();
  const [phase, setPhase] = useState<RefreshPhase>("idle");
  const [statusMsg, setStatusMsg] = useState("");
  const dismissTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (dismissTimer.current) clearTimeout(dismissTimer.current);
    };
  }, []);

  const isSpinning = phase === "syncing" || phase === "fetching";

  const handleRefresh = async () => {
    if (isSpinning) return;

    // Clear any previous dismiss timer
    if (dismissTimer.current) {
      clearTimeout(dismissTimer.current);
      dismissTimer.current = null;
    }

    setPhase("syncing");
    setStatusMsg("Syncing accounts & prices...");

    let syncData: any = null;

    try {
      const { data } = await api.post("/sync/refresh-all");
      syncData = data;
    } catch (e: any) {
      setStatusMsg(e?.response?.data?.detail || "Sync failed");
      setPhase("error");
      // Still try to refetch UI data
      queryClient.refetchQueries({ type: "active" });
      dismissTimer.current = setTimeout(() => {
        setPhase("idle");
        setStatusMsg("");
      }, 5000);
      return;
    }

    // Build status message from sync results
    const parts: string[] = [];
    if (syncData.accounts_synced > 0) {
      parts.push(`${syncData.accounts_synced} account${syncData.accounts_synced > 1 ? "s" : ""} synced`);
    }
    if (syncData.total_imported > 0) {
      parts.push(`${syncData.total_imported} new`);
    }
    if (syncData.errors?.length > 0) {
      parts.push(`${syncData.errors.length} error${syncData.errors.length > 1 ? "s" : ""}`);
    }

    const hasErrors = syncData.errors?.length > 0;

    // Move to "fetching" phase — spinner keeps going until all data is refetched
    setPhase("fetching");
    setStatusMsg("Updating dashboard...");

    try {
      await Promise.all([
        queryClient.refetchQueries({ queryKey: ["portfolio"], type: "all" }),
        queryClient.refetchQueries({ queryKey: ["analytics"], type: "all" }),
      ]);

      setStatusMsg(
        parts.length > 0
          ? parts.join(" · ")
          : "Prices & FX rates refreshed"
      );
      if (hasErrors) {
        setPhase("error");
        dismissTimer.current = setTimeout(() => {
          setPhase("idle");
          setStatusMsg("");
        }, 5000);
      } else {
        setPhase("done");
        dismissTimer.current = setTimeout(() => {
          setPhase("idle");
          setStatusMsg("");
        }, 4000);
      }
    } catch (e) {
      setStatusMsg("Refresh complete (some data failed to update)");
      setPhase("error");
      dismissTimer.current = setTimeout(() => {
        setPhase("idle");
        setStatusMsg("");
      }, 5000);
    }

    // Safety fallback: if spinner is still going after 30s, force stop
    setTimeout(() => {
      setPhase((prev) => {
        if (prev === "syncing" || prev === "fetching") {
          setStatusMsg(parts.length > 0 ? parts.join(" · ") : "Refresh complete");
          dismissTimer.current = setTimeout(() => {
            setPhase("idle");
            setStatusMsg("");
          }, 4000);
          return "done";
        }
        return prev;
      });
    }, 30000);
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
            <div className="text-xs text-gray-500">Net Worth{displayCurrency !== "AUD" ? ` (${displayCurrency})` : ""}</div>
            <div className={clsx(
              "font-semibold",
              displayCurrency !== "AUD" ? "text-blue-300" : "text-gray-100"
            )}>
              {formatCurrency(portfolio.total_market_value, false, displayCurrency)}
            </div>
          </div>
          <div className="w-px h-8 bg-gray-700" />
          <div className="text-center">
            <div className="text-xs text-gray-500">Unrealized P&L</div>
            <div className={clsx(
              "font-semibold",
              portfolio.total_unrealized_gain >= 0 ? "text-green-400" : "text-red-400"
            )}>
              {portfolio.total_unrealized_gain >= 0 ? "+" : ""}
              {formatCurrency(portfolio.total_unrealized_gain, false, displayCurrency)}
            </div>
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center gap-2">
        {/* Status message */}
        {statusMsg && (
          <div className={clsx(
            "flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg border animate-fade-in",
            phase === "error"
              ? "bg-red-400/10 text-red-400 border-red-400/20"
              : phase === "done"
              ? "bg-green-400/10 text-green-400 border-green-400/20"
              : "bg-blue-400/10 text-blue-400 border-blue-400/20"
          )}>
            {phase === "error" ? (
              <AlertCircle className="w-3 h-3" />
            ) : phase === "done" ? (
              <Check className="w-3 h-3" />
            ) : (
              <RefreshCw className="w-3 h-3 animate-spin" />
            )}
            {statusMsg}
          </div>
        )}

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
          onClick={handleRefresh}
          disabled={isSpinning}
          className={clsx(
            "w-9 h-9 rounded-lg border flex items-center justify-center transition-all",
            isSpinning
              ? "bg-blue-600/20 border-blue-500/30 cursor-wait"
              : "bg-gray-800 hover:bg-gray-700 border-gray-700"
          )}
          title="Sync accounts, refresh prices & FX rates"
        >
          <RefreshCw className={clsx(
            "w-4 h-4 transition-colors",
            isSpinning
              ? "text-blue-400 animate-spin"
              : "text-gray-400"
          )} />
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
