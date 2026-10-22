"use client";

import { useState, useMemo, Fragment } from "react";
import clsx from "clsx";
import {
  ChevronUp,
  ChevronDown,
  ChevronRight,
  ArrowUpDown,
  Loader2,
} from "lucide-react";
import { formatCurrency } from "@/lib/utils/formatters";
import {
  useHoldingTransactions,
  HoldingTransaction,
} from "@/lib/hooks/usePortfolio";

export interface Holding {
  symbol: string;
  name: string;
  asset_class: string;
  quantity: number;
  average_cost_basis?: number;
  total_cost_basis?: number;
  last_price?: number;
  market_value?: number;
  weight_pct?: number;
  unrealized_gain?: number;
  unrealized_gain_pct?: number;
  currency?: string;
  original_currency?: string;
  exchange?: string | null;
  period_income?: number | null;
  period_price_return_pct?: number | null;
}

interface Props {
  holdings: Holding[];
  loading?: boolean;
  currency?: string;
  showTotals?: boolean;
  showPeriodMetrics?: boolean;
  periodLabel?: string;
}

type SortKey =
  | "symbol"
  | "last_price"
  | "quantity"
  | "market_value"
  | "unrealized_gain"
  | "average_cost_basis"
  | "total_cost_basis"
  | "unrealized_gain_pct"
  | "period_price_return_pct"
  | "period_income"
  | "weight_pct";

type SortDir = "asc" | "desc";

const COLUMNS: {
  key: SortKey;
  label: string;
  short?: string;
  align: "left" | "right";
  periodOnly?: boolean;
}[] = [
  { key: "symbol", label: "Ticker", align: "left" },
  { key: "last_price", label: "Price", align: "right" },
  { key: "quantity", label: "Quantity", align: "right" },
  { key: "market_value", label: "Value", align: "right" },
  { key: "unrealized_gain", label: "P/L", align: "right" },
  { key: "average_cost_basis", label: "Avg Cost", align: "right" },
  { key: "total_cost_basis", label: "Cost Basis", short: "Cost", align: "right" },
  { key: "unrealized_gain_pct", label: "Return %", short: "Return", align: "right" },
  { key: "period_price_return_pct", label: "Period Price", short: "Period", align: "right", periodOnly: true },
  { key: "period_income", label: "Period Income", short: "Income", align: "right", periodOnly: true },
  { key: "weight_pct", label: "Weight", align: "right" },
];

const fmtDate = (iso: string) =>
  new Date(iso).toLocaleDateString("en-AU", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });

const fmtQty = (q: number) =>
  q < 1 ? q.toFixed(6) : q % 1 === 0 ? q.toFixed(0) : q.toFixed(2);

function marketLabel(holding: Holding): string {
  const exchange = holding.exchange?.trim().toUpperCase();
  if (exchange) return exchange;
  if (holding.asset_class === "CRYPTO") return "Crypto";
  const symbol = holding.symbol.toUpperCase();
  if (symbol.endsWith(".AX") || holding.original_currency === "AUD") return "ASX";
  if (holding.original_currency === "USD") return "US";
  return holding.original_currency || "Market";
}

function marketBadgeClass(label: string) {
  if (label === "ASX") return "bg-blue-500/10 text-blue-400";
  if (label === "Crypto") return "bg-orange-500/10 text-orange-400";
  return "bg-green-500/10 text-green-400";
}

// ─── Expandable sub-row for a single holding ──────────────────────────────
function ExpandedDetail({ symbol, origCcy, colSpan }: { symbol: string; origCcy: string; colSpan: number }) {
  const { data: txns, isLoading } = useHoldingTransactions(symbol);

  if (isLoading) {
    return (
      <tr>
        <td colSpan={colSpan} className="py-4 text-center">
          <Loader2 className="w-4 h-4 animate-spin inline-block text-gray-500 mr-2" />
          <span className="text-gray-500 text-xs">Loading transactions...</span>
        </td>
      </tr>
    );
  }

  const TXN_TYPES = new Set([
    "BUY",
    "SELL",
    "TRANSFER_IN",
    "TRANSFER_OUT",
    "DIVIDEND",
    "DISTRIBUTION",
  ]);
  const trades = (txns ?? []).filter((t) => TXN_TYPES.has(t.transaction_type));

  const ccyLabel = origCcy === "USD" ? "US$" : origCcy === "AUD" ? "A$" : `${origCcy} `;

  if (trades.length === 0) {
    return (
      <tr>
        <td colSpan={colSpan} className="py-3 text-center text-gray-600 text-xs">
          No transaction history found.
        </td>
      </tr>
    );
  }

  return (
    <tr>
      <td colSpan={colSpan} className="p-0">
        <div className="bg-gray-900/60 border-y border-gray-800/60 px-4 py-3">
          <h4 className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider mb-2">
            Trades & Adjustments
          </h4>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-gray-600 border-b border-gray-800/50">
                <th className="py-1.5 text-left font-medium">Date</th>
                <th className="py-1.5 text-left font-medium">Type</th>
                <th className="py-1.5 text-right font-medium">Qty</th>
                <th className="py-1.5 text-right font-medium">Price</th>
                <th className="py-1.5 text-right font-medium">Fees</th>
                <th className="py-1.5 text-right font-medium">FX Rate</th>
                <th className="py-1.5 text-right font-medium">Value (AUD)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/30">
              {trades.map((t) => {
                const isSell = t.transaction_type === "SELL";
                const isIncome = t.transaction_type === "DIVIDEND" || t.transaction_type === "DISTRIBUTION";
                const qty = t.quantity ?? 0;
                const price = t.price_per_unit ?? 0;
                const fees = t.fees ?? 0;
                const fxRate = t.fx_rate_to_aud;
                const valueAud = t.net_amount_aud ?? t.net_amount ?? 0;

                return (
                  <tr key={t.id} className="text-gray-400 hover:bg-gray-800/20">
                    <td className="py-1.5">{fmtDate(t.transacted_at)}</td>
                    <td className="py-1.5">
                      <span
                        className={clsx(
                          "px-1.5 py-0.5 rounded text-[10px] font-medium",
                          isSell
                            ? "bg-red-500/10 text-red-400"
                            : "bg-blue-500/10 text-blue-400"
                        )}
                      >
                        {t.transaction_type.replace("_", " ")}
                      </span>
                    </td>
                    <td className="py-1.5 text-right font-mono">
                      {isIncome ? "—" : fmtQty(qty)}
                    </td>
                    <td className="py-1.5 text-right font-mono">
                      {isIncome ? "—" : `${ccyLabel}${price.toFixed(2)}`}
                    </td>
                    <td className="py-1.5 text-right font-mono text-gray-500">
                      {isIncome ? "—" : fees > 0 ? `${ccyLabel}${fees.toFixed(2)}` : "—"}
                    </td>
                    <td className="py-1.5 text-right font-mono text-gray-500">
                      {fxRate && origCcy !== "AUD"
                        ? `${fxRate.toFixed(4)} AUD/${origCcy}`
                        : "—"}
                    </td>
                    <td className="py-1.5 text-right font-mono text-gray-300">
                      A${Math.abs(valueAud).toFixed(2)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </td>
    </tr>
  );
}

// ─── Main Component ────────────────────────────────────────────────────────
export function HoldingsTable({
  holdings,
  loading = false,
  currency = "AUD",
  showTotals = true,
  showPeriodMetrics = false,
  periodLabel = "period",
}: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("market_value");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [expandedSymbol, setExpandedSymbol] = useState<string | null>(null);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "symbol" ? "asc" : "desc");
    }
  };

  const toggleExpand = (symbol: string) => {
    setExpandedSymbol((prev) => (prev === symbol ? null : symbol));
  };

  const STABLECOINS = new Set(["USDT", "USDC", "DAI", "BUSD"]);
  const filtered = useMemo(() => {
    return holdings.filter((h) => {
      if (STABLECOINS.has(h.symbol.toUpperCase())) return true;
      const marketValue = Math.abs(h.market_value ?? 0);
      const costBasis = Math.abs(h.total_cost_basis ?? 0);
      const quantity = Math.abs(h.quantity ?? 0);
      return marketValue >= 1 || costBasis >= 1 || quantity > 0;
    });
  }, [holdings]);

  const showPeriodPriceReturn =
    showPeriodMetrics && filtered.some((h) => h.period_price_return_pct != null);

  const visibleColumns = useMemo(
    () =>
      COLUMNS.filter((col) => {
        if (!col.periodOnly) return true;
        if (col.key === "period_price_return_pct") return showPeriodPriceReturn;
        return showPeriodMetrics;
      }),
    [showPeriodMetrics, showPeriodPriceReturn]
  );

  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      let aVal: any = a[sortKey] ?? 0;
      let bVal: any = b[sortKey] ?? 0;

      if (typeof aVal === "string") {
        aVal = aVal.toLowerCase();
        bVal = (bVal as string).toLowerCase();
        return sortDir === "asc"
          ? aVal.localeCompare(bVal)
          : bVal.localeCompare(aVal);
      }

      return sortDir === "asc" ? aVal - bVal : bVal - aVal;
    });
  }, [filtered, sortKey, sortDir]);

  const totals = useMemo(() => {
    if (!showTotals || !filtered.length) return null;
    const totalValue = filtered.reduce((s, h) => s + (h.market_value ?? 0), 0);
    const totalCost = filtered.reduce((s, h) => s + (h.total_cost_basis ?? 0), 0);
    const totalGain = filtered.reduce((s, h) => s + (h.unrealized_gain ?? 0), 0);
    const totalPeriodIncome = filtered.reduce((s, h) => s + (h.period_income ?? 0), 0);
    const weightedPeriodReturn =
      totalValue > 0
        ? filtered.reduce(
            (s, h) => s + ((h.period_price_return_pct ?? 0) * (h.market_value ?? 0)) / totalValue,
            0
          )
        : 0;
    const totalReturnPct = totalCost > 0 ? (totalGain / totalCost) * 100 : 0;
    return { totalValue, totalCost, totalGain, totalReturnPct, totalPeriodIncome, weightedPeriodReturn };
  }, [filtered, showTotals]);

  const isToggled = currency !== "AUD";
  const fmtMoney = (value: number) => formatCurrency(value, false, currency);

  if (loading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-12 bg-gray-800/50 rounded-lg animate-pulse" />
        ))}
      </div>
    );
  }

  if (!filtered.length) {
    return (
      <div className="text-center py-8 text-gray-500 text-sm">
        No holdings found. Add accounts and import transactions to get started.
      </div>
    );
  }

  const SortIcon = ({ col }: { col: SortKey }) => {
    if (sortKey !== col) {
      return (
        <ArrowUpDown className="w-3 h-3 text-gray-600 opacity-0 group-hover:opacity-100 transition-opacity" />
      );
    }
    return sortDir === "asc" ? (
      <ChevronUp className="w-3 h-3 text-blue-400" />
    ) : (
      <ChevronDown className="w-3 h-3 text-blue-400" />
    );
  };

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-800">
            {visibleColumns.map((col) => (
              <th
                key={col.key}
                onClick={() => handleSort(col.key)}
                className={clsx(
                  "py-2 pr-3 text-xs text-gray-500 uppercase tracking-wider font-medium cursor-pointer select-none group hover:text-gray-300 transition-colors",
                  col.align === "left" ? "text-left" : "text-right"
                )}
              >
                <span className="inline-flex items-center gap-1">
                  {col.align === "right" && <SortIcon col={col.key} />}
                  <span className="hidden lg:inline">{col.label}</span>
                  <span className="lg:hidden">{col.short || col.label}</span>
                  {col.periodOnly && (
                    <span className="hidden xl:inline normal-case text-gray-600">({periodLabel})</span>
                  )}
                  {col.align === "left" && <SortIcon col={col.key} />}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-800/50">
          {sorted.map((h) => {
            const gainPositive = (h.unrealized_gain ?? 0) >= 0;
            const returnPct =
              h.unrealized_gain_pct ??
              (h.total_cost_basis && h.total_cost_basis > 0
                ? ((h.unrealized_gain ?? 0) / h.total_cost_basis) * 100
                : 0);
            const returnPositive = returnPct >= 0;
            const origCcy = h.original_currency || "AUD";
            const market = marketLabel(h);
            const isExpanded = expandedSymbol === h.symbol;

            return (
              <Fragment key={h.symbol}>
                <tr
                  onClick={() => toggleExpand(h.symbol)}
                  className={clsx(
                    "cursor-pointer transition-colors",
                    isExpanded
                      ? "bg-gray-800/40"
                      : "hover:bg-gray-800/30"
                  )}
                >
                  {/* Ticker */}
                  <td className="py-3 pr-3">
                    <div className="flex items-center gap-1.5">
                      <ChevronRight
                        className={clsx(
                          "w-3.5 h-3.5 text-gray-500 transition-transform flex-shrink-0",
                          isExpanded && "rotate-90"
                        )}
                      />
                      <span className="font-semibold text-gray-100">{h.symbol}</span>
                      <span className={clsx("text-[9px] px-1 py-0.5 rounded font-medium", marketBadgeClass(market))}>
                        {market}
                      </span>
                      {h.name && h.name !== h.symbol && (
                        <span className="text-[10px] text-gray-500 truncate max-w-[100px] hidden lg:inline">
                          {h.name}
                        </span>
                      )}
                    </div>
                  </td>

                  {/* Price */}
                  <td className="py-3 pr-3 text-right font-mono text-gray-300">
                    {h.last_price ? fmtMoney(h.last_price) : "—"}
                  </td>

                  {/* Quantity */}
                  <td className="py-3 pr-3 text-right font-mono text-gray-300">
                    {fmtQty(h.quantity)}
                  </td>

                  {/* Value */}
                  <td className="py-3 pr-3 text-right font-mono font-medium text-gray-100">
                    {h.market_value ? fmtMoney(h.market_value) : "—"}
                  </td>

                  {/* P/L */}
                  <td className="py-3 pr-3 text-right">
                    {h.unrealized_gain !== undefined ? (
                      <span
                        className={clsx(
                          "font-mono font-medium",
                          gainPositive ? "text-green-400" : "text-red-400"
                        )}
                      >
                        {gainPositive ? "+" : ""}
                        {fmtMoney(h.unrealized_gain)}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>

                  {/* Avg Cost */}
                  <td className="py-3 pr-3 text-right font-mono text-gray-400">
                    {h.average_cost_basis ? fmtMoney(h.average_cost_basis) : "—"}
                  </td>

                  {/* Cost Basis */}
                  <td className="py-3 pr-3 text-right font-mono text-gray-400">
                    {h.total_cost_basis ? fmtMoney(h.total_cost_basis) : "—"}
                  </td>

                  {/* Return % */}
                  <td className="py-3 pr-3 text-right">
                    <span
                      className={clsx(
                        "font-mono text-xs font-medium px-1.5 py-0.5 rounded",
                        returnPositive
                          ? "text-green-400 bg-green-400/10"
                          : "text-red-400 bg-red-400/10"
                      )}
                    >
                      {returnPositive ? "+" : ""}
                      {returnPct.toFixed(1)}%
                    </span>
                  </td>

                  {showPeriodPriceReturn && (
                    <td className="py-3 pr-3 text-right">
                      {h.period_price_return_pct != null ? (
                        <span
                          className={clsx(
                            "font-mono text-xs font-medium px-1.5 py-0.5 rounded",
                            h.period_price_return_pct >= 0
                              ? "text-green-400 bg-green-400/10"
                              : "text-red-400 bg-red-400/10"
                          )}
                        >
                          {h.period_price_return_pct >= 0 ? "+" : ""}
                          {h.period_price_return_pct.toFixed(1)}%
                        </span>
                      ) : (
                        <span className="text-gray-600">—</span>
                      )}
                    </td>
                  )}

                  {showPeriodMetrics && (
                    <td className="py-3 pr-3 text-right">
                      {h.period_income != null && h.period_income !== 0 ? (
                        <span className="font-mono font-medium text-green-400">
                          +{fmtMoney(h.period_income)}
                        </span>
                      ) : (
                        <span className="text-gray-600">—</span>
                      )}
                    </td>
                  )}

                  {/* Weight */}
                  <td className="py-3 text-right">
                    {h.weight_pct != null ? (
                      <div className="flex items-center justify-end gap-2">
                        <div className="w-10 bg-gray-800 rounded-full h-1.5 hidden sm:block">
                          <div
                            className="h-1.5 rounded-full bg-blue-500"
                            style={{ width: `${Math.min(h.weight_pct, 100)}%` }}
                          />
                        </div>
                        <span className="text-gray-400 text-xs w-10 text-right">
                          {h.weight_pct.toFixed(1)}%
                        </span>
                      </div>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>

                {/* Expanded detail row */}
                {isExpanded && (
                  <ExpandedDetail
                    key={`${h.symbol}-detail`}
                    symbol={h.symbol}
                    origCcy={origCcy}
                    colSpan={visibleColumns.length}
                  />
                )}
              </Fragment>
            );
          })}
        </tbody>

        {/* Totals Row */}
        {totals && (
          <tfoot>
            <tr className="border-t-2 border-gray-700">
              <td className="py-3 pr-3 font-semibold text-gray-200">
                Totals
                {isToggled && (
                  <span className="ml-1.5 text-[9px] px-1 py-0.5 rounded font-medium bg-blue-500/10 text-blue-400">
                    {currency}
                  </span>
                )}
              </td>
              <td className="py-3 pr-3" />
              <td className="py-3 pr-3" />
              <td
                className={clsx(
                  "py-3 pr-3 text-right font-mono font-bold",
                  isToggled ? "text-blue-300" : "text-gray-100"
                )}
              >
                {formatCurrency(totals.totalValue, false, currency)}
              </td>
              <td className="py-3 pr-3 text-right">
                <span
                  className={clsx(
                    "font-mono font-bold",
                    totals.totalGain >= 0 ? "text-green-400" : "text-red-400"
                  )}
                >
                  {totals.totalGain >= 0 ? "+" : ""}
                  {formatCurrency(totals.totalGain, false, currency)}
                </span>
              </td>
              <td className="py-3 pr-3" />
              <td
                className={clsx(
                  "py-3 pr-3 text-right font-mono font-bold",
                  isToggled ? "text-blue-300" : "text-gray-300"
                )}
              >
                {formatCurrency(totals.totalCost, false, currency)}
              </td>
              <td className="py-3 pr-3 text-right">
                <span
                  className={clsx(
                    "font-mono text-xs font-bold px-1.5 py-0.5 rounded",
                    totals.totalReturnPct >= 0
                      ? "text-green-400 bg-green-400/10"
                      : "text-red-400 bg-red-400/10"
                  )}
                >
                  {totals.totalReturnPct >= 0 ? "+" : ""}
                  {totals.totalReturnPct.toFixed(1)}%
                </span>
              </td>
              {showPeriodPriceReturn && (
                <td className="py-3 pr-3 text-right">
                  <span
                    className={clsx(
                      "font-mono text-xs font-bold px-1.5 py-0.5 rounded",
                      totals.weightedPeriodReturn >= 0
                        ? "text-green-400 bg-green-400/10"
                        : "text-red-400 bg-red-400/10"
                    )}
                  >
                    {totals.weightedPeriodReturn >= 0 ? "+" : ""}
                    {totals.weightedPeriodReturn.toFixed(1)}%
                  </span>
                </td>
              )}
              {showPeriodMetrics && (
                <td className="py-3 pr-3 text-right">
                  <span className="font-mono font-bold text-green-400">
                    {totals.totalPeriodIncome > 0 ? "+" : ""}
                    {formatCurrency(totals.totalPeriodIncome, false, currency)}
                  </span>
                </td>
              )}
              <td className="py-3 text-right text-gray-400 text-xs">100%</td>
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  );
}
