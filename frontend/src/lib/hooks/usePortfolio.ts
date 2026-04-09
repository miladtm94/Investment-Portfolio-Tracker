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
}

export interface PortfolioSummary {
  total_market_value: number;
  total_cost_basis: number;
  total_unrealized_gain: number;
  total_unrealized_gain_pct: number;
  total_realized_gain_short: number;
  total_realized_gain_long: number;
  dividend_income: number;
  staking_income: number;
  holdings: Holding[];
  as_of: string;
}

export function usePortfolioSummary(accountIds?: string[], currency: string = "AUD") {
  const searchParams = new URLSearchParams();
  if (accountIds?.length) searchParams.set("account_ids", accountIds.join(","));
  if (currency && currency !== "AUD") searchParams.set("currency", currency);
  const qs = searchParams.toString();
  const url = `/portfolio/summary${qs ? `?${qs}` : ""}`;
  return useQuery<PortfolioSummary>({
    queryKey: ["portfolio", "summary", accountIds, currency],
    queryFn: () => api.get(url).then((r) => r.data),
    staleTime: 30 * 1000,
    refetchInterval: 60 * 1000,
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

