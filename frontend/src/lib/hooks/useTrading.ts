import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

// ─── Types ────────────────────────────────────────────────────────────────────

export type Provider = "claude" | "openai" | "gemini";
export type Horizon = "trading" | "investing";
export type AssetClass = "EQUITY" | "CRYPTO" | "ETF";

export interface MarketAsset {
  symbol: string;
  name: string;
  asset_class: AssetClass;
  price: number | null;
  change_24h?: number | null;
  change_7d?: number | null;
  market_cap?: number | null;
  volume_24h?: number | null;
  sparkline?: number[];
  rank?: number | null;
  image?: string | null;
  exchange?: string | null;
  coingecko_id?: string | null;
}

export interface MarketsResponse {
  crypto: MarketAsset[];
  equities: MarketAsset[];
}

export interface WatchlistItem {
  id: string;
  symbol: string;
  name: string;
  asset_class: AssetClass;
  exchange: string | null;
  coingecko_id: string | null;
  image_url: string | null;
  notes: string | null;
  added_at: string;
  price: number | null;
}

export interface WatchlistAddPayload {
  symbol: string;
  name: string;
  asset_class: AssetClass;
  exchange?: string;
  coingecko_id?: string;
  image_url?: string;
  notes?: string;
}

export interface AnalyzeRequest {
  symbol: string;
  name: string;
  asset_class: AssetClass;
  price?: number | null;
  exchange?: string | null;
  sector?: string | null;
  coingecko_id?: string | null;
  horizon: Horizon;
  provider: Provider;
  extra_context?: string;
}

export interface AnalysisResult {
  rec: "STRONG BUY" | "BUY" | "HOLD" | "SELL" | "STRONG SELL";
  score: number;
  horizon: string;
  confidence: "High" | "Medium" | "Low";
  target: number;
  targetLow: number;
  targetHigh: number;
  stopLoss: number;
  entryZone: string;
  summary: string;
  technical: string;
  fundamental: string;
  news: string;
  support: number[];
  resistance: number[];
  catalysts: string[];
  risks: string[];
  allocation: string;
  strategyNote: string;
  _provider: Provider;
  _horizon: Horizon;
}

// ─── Hooks ────────────────────────────────────────────────────────────────────

export function useMarkets() {
  return useQuery<MarketsResponse>({
    queryKey: ["trading", "markets"],
    queryFn: () => api.get("/trading/markets").then((r) => r.data),
    staleTime: 60 * 1000,
    refetchInterval: 60 * 1000,
  });
}

export function useWatchlist() {
  return useQuery<WatchlistItem[]>({
    queryKey: ["trading", "watchlist"],
    queryFn: () => api.get("/trading/watchlist").then((r) => r.data),
    staleTime: 30 * 1000,
  });
}

export function useAddToWatchlist() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: WatchlistAddPayload) =>
      api.post("/trading/watchlist", payload).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["trading", "watchlist"] }),
  });
}

export function useRemoveFromWatchlist() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (symbol: string) =>
      api.delete(`/trading/watchlist/${symbol}`).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["trading", "watchlist"] }),
  });
}

export function useAnalyzeAsset() {
  return useMutation<AnalysisResult, Error, AnalyzeRequest>({
    mutationFn: (req) => api.post("/trading/analyze", req).then((r) => r.data),
  });
}
