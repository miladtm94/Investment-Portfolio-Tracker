import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

export interface AnalyticsBundle {
  performance: {
    total_return_pct: number;
    annualized_return_pct: number;
    twr_pct: number;
    mwr_pct: number;
    benchmark_return_pct: number;
    alpha: number;
    beta: number;
    start_value: number;
    end_value: number;
    period_days: number;
  };
  risk: {
    volatility_annual_pct: number;
    sharpe_ratio: number;
    sortino_ratio: number;
    calmar_ratio: number;
    max_drawdown_pct: number;
    max_drawdown_duration_days: number;
    var_95_pct: number;
    cvar_95_pct: number;
    beta_vs_benchmark: number;
    correlation_vs_benchmark: number;
  };
  allocation: {
    by_asset_class: Record<string, number>;
    by_sector: Record<string, number>;
    by_geography: Record<string, number>;
    top_holdings: Array<{
      symbol: string;
      name: string;
      asset_class: string;
      weight_pct: number;
      market_value: number;
      unrealized_gain: number;
      unrealized_gain_pct: number;
    }>;
    concentration_score: number;
    diversification_score: number;
  };
  computed_at: string;
  period: string;
  benchmark: string;
}

export function useAnalytics(
  period: string = "1Y",
  benchmark: string = "SPY",
  currency: string = "AUD",
  startDate?: string,
  endDate?: string,
) {
  const params = new URLSearchParams();
  params.set("period", period);
  params.set("benchmark", benchmark);
  if (currency && currency !== "AUD") params.set("currency", currency);
  if (startDate && endDate) {
    params.set("start_date", startDate);
    params.set("end_date", endDate);
  }

  return useQuery<AnalyticsBundle>({
    queryKey: ["analytics", period, benchmark, currency, startDate, endDate],
    queryFn: () =>
      api.get(`/analytics/?${params.toString()}`).then((r) => r.data),
    staleTime: 5 * 60 * 1000,
    enabled: period !== "CUSTOM" || Boolean(startDate && endDate),
  });
}
