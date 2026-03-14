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

export function usePortfolioSummary(accountIds?: string[]) {
  const params = accountIds?.length ? `?account_ids=${accountIds.join(",")}` : "";
  return useQuery<PortfolioSummary>({
    queryKey: ["portfolio", "summary", accountIds],
    queryFn: () => api.get(`/portfolio/summary${params}`).then((r) => r.data),
    staleTime: 30 * 1000,
    refetchInterval: 60 * 1000, // Refresh every minute
  });
}

export function useAccounts() {
  return useQuery({
    queryKey: ["portfolio", "accounts"],
    queryFn: () => api.get("/portfolio/accounts").then((r) => r.data),
  });
}

export function useNetWorth() {
  return useQuery({
    queryKey: ["portfolio", "net-worth"],
    queryFn: () => api.get("/portfolio/net-worth").then((r) => r.data),
    staleTime: 60 * 1000,
  });
}
