import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

export interface Holding {
  asset_id: string;
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
  currency: string;
  original_currency?: string;
  exchange?: string | null;
  period_income?: number | null;
  period_price_return_pct?: number | null;
}

export interface PortfolioSummary {
  total_market_value: number;
  total_cost_basis: number;
  total_unrealized_gain: number;
  total_unrealized_gain_pct: number;
  total_realized_gain_short: number;
  total_realized_gain_long: number;
  total_realized_gain: number;
  total_income: number;
  total_pnl: number;
  total_pnl_pct: number;
  dividend_income: number;
  staking_income: number;
  holdings: Holding[];
  as_of: string;
  period?: string | null;
  period_start?: string | null;
  period_end?: string | null;
  period_market_value_change?: number | null;
  period_realized_gain_short?: number | null;
  period_realized_gain_long?: number | null;
  period_realized_gain?: number | null;
  period_income?: number | null;
  period_pnl?: number | null;
  period_pnl_pct?: number | null;
}

export function usePortfolioSummary(
  accountIds?: string[],
  currency: string = "AUD",
  period?: string,
  startDate?: string,
  endDate?: string,
) {
  const searchParams = new URLSearchParams();
  accountIds?.forEach((id) => searchParams.append("account_ids", id));
  if (currency && currency !== "AUD") searchParams.set("currency", currency);
  if (period) searchParams.set("period", period);
  if (startDate && endDate) {
    searchParams.set("start_date", startDate);
    searchParams.set("end_date", endDate);
  }
  const qs = searchParams.toString();
  const url = `/portfolio/summary${qs ? `?${qs}` : ""}`;
  return useQuery<PortfolioSummary>({
    queryKey: ["portfolio", "summary", accountIds, currency, period, startDate, endDate],
    queryFn: () => api.get(url).then((r) => r.data),
    placeholderData: (previousData) => previousData,
    staleTime: 30 * 1000,
    refetchInterval: 60 * 1000,
    enabled: period !== "CUSTOM" || Boolean(startDate && endDate),
  });
}

export function useAccounts() {
  return useQuery({
    queryKey: ["portfolio", "accounts"],
    queryFn: () => api.get("/portfolio/accounts").then((r) => r.data),
  });
}

export function useNetWorth(currency: string = "AUD") {
  const qs = currency && currency !== "AUD" ? `?currency=${currency}` : "";
  return useQuery({
    queryKey: ["portfolio", "net-worth", currency],
    queryFn: () => api.get(`/portfolio/net-worth${qs}`).then((r) => r.data),
    staleTime: 60 * 1000,
  });
}

export interface HoldingTransaction {
  id: string;
  account_id: string;
  asset_id: string | null;
  symbol: string | null;
  transaction_type: string;
  quantity: number | null;
  price_per_unit: number | null;
  fees: number;
  gross_amount: number | null;
  tax_withheld: number | null;
  dividend_per_share: number | null;
  net_amount: number | null;
  currency: string;
  fx_rate_to_aud: number | null;
  net_amount_aud: number | null;
  price_per_unit_aud: number | null;
  ex_date: string | null;
  franking_pct: number | null;
  franking_credit: number | null;
  transacted_at: string;
  source: string;
  notes: string | null;
  created_at: string;
}

export function useHoldingTransactions(symbol: string | null) {
  return useQuery<HoldingTransaction[]>({
    queryKey: ["transactions", "holding", symbol],
    queryFn: () =>
      api.get(`/transactions/?asset_symbol=${symbol}&limit=200`).then((r) => r.data),
    enabled: !!symbol,
    staleTime: 60 * 1000,
  });
}
