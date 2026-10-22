import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, apiSlow } from "@/lib/api/client";

// ─── Types ────────────────────────────────────────────────────────────────────

export type Provider = "claude" | "openai" | "gemini" | "ollama" | "lmstudio";
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

export interface SearchResult {
  symbol: string;
  name: string;
  asset_class: AssetClass;
  image?: string | null;
  exchange?: string | null;
  coingecko_id?: string | null;
  rank?: number | null;
}

export interface SearchResponse {
  crypto: SearchResult[];
  equities: SearchResult[];
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
  as_of_date?: string | null;  // ISO date — analyze data up to this date (for backtesting)
}

export interface AgentScores {
  tech?: number;
  news?: number;
  fund?: number;
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
  newsSentiment?: "BULLISH" | "BEARISH" | "MIXED" | "NEUTRAL";
  macroContext?: string;
  support: number[];
  resistance: number[];
  catalysts: string[];
  risks: string[];
  allocation: string;
  strategyNote: string;
  _provider: Provider;
  _horizon: Horizon;
  _agent_scores?: AgentScores;
  _analysis_id?: string;
  _as_of_date?: string | null;
  _entry_price?: number | null;
}

export interface SignalRequest {
  symbol: string;
  name?: string;
  asset_class: AssetClass;
  interval: "15" | "60" | "240" | "D" | "W";
  exchange?: string | null;
  currency?: string;
  as_of_date?: string | null;
  evaluation_days?: number;
}

export interface SignalEvidence {
  label: string;
  verdict: "Bullish" | "Bearish" | "Neutral";
  score: number;
  explanation: string;
}

export interface SignalResult {
  symbol: string;
  name: string;
  assetClass: AssetClass;
  signal: "STRONG BUY" | "BUY" | "HOLD" | "SELL" | "STRONG SELL";
  score: number;
  rawScore: number;
  confidence: "High" | "Medium" | "Low";
  timeframe: string;
  scoreMeaning: string;
  currentPrice: number;
  generatedAt: string;
  candleCount: number;
  lastCandleTime: string;
  analysisWindow: {
    from: string;
    to: string;
    timeframe: string;
  };
  tradePlan: {
    action: "ENTER_NOW" | "WAIT_FOR_PULLBACK" | "WAIT_FOR_BREAKOUT" | "WAIT_FOR_REBOUND" | "WAIT_FOR_BREAKDOWN";
    setup: string;
    entryCondition: string;
    isActionableNow: boolean;
    currentPrice: number;
    entry: number;
    entryZoneLow: number;
    entryZoneHigh: number;
    stopLoss: number;
    takeProfit1: number;
    takeProfit2: number;
    takeProfit3: number;
    riskReward: number | null;
    positionNote: string;
    invalidation: string;
  };
  indicators: Record<string, number | null>;
  levels: {
    support: number[];
    resistance: number[];
  };
  evidence: SignalEvidence[];
  patterns: {
    candlestick: Array<Record<string, unknown>>;
    chart: Array<Record<string, unknown>>;
  };
  explanation: string;
  warnings: string[];
  requestedEvaluationDays: number;
  dueAt: string;
  status: "PENDING" | "EVALUATED";
  backtest: {
    available: boolean;
    evaluationWindow: { from: string; to: string; days: number };
    entryTriggered?: boolean;
    entryDate?: string;
    entryPrice?: number;
    exitDate?: string;
    exitPrice?: number;
    outcome?: string;
    maxTargetHit?: number;
    returnPct?: number | null;
    finalPrice?: number | null;
    finalMovePct?: number | null;
    summary: string;
  } | null;
  _signal_id?: string;
  _as_of_date?: string | null;
}

export interface SignalCheckItem {
  id: string;
  symbol: string;
  name: string;
  assetClass: AssetClass;
  exchange: string | null;
  interval: string;
  signal: SignalResult["signal"];
  score: number | null;
  confidence: "High" | "Medium" | "Low" | null;
  action: string | null;
  status: "PENDING" | "EVALUATED";
  signalAt: string;
  dueAt: string;
  evaluationDays: number;
  currentPrice: number | null;
  entryPrice: number | null;
  stopLoss: number | null;
  takeProfit1: number | null;
  takeProfit2: number | null;
  takeProfit3: number | null;
  riskReward: number | null;
  outcome: string | null;
  outcomeCorrect: boolean | null;
  outcomeReturnPct: number | null;
  outcomePayload: SignalResult["backtest"];
  checkedAt: string | null;
  createdAt: string;
  checkMessage?: string;
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

export function useAssetSearch(q: string) {
  return useQuery<SearchResponse>({
    queryKey: ["trading", "search", q],
    queryFn: () => api.get("/trading/search", { params: { q } }).then((r) => r.data),
    enabled: q.trim().length >= 1,
    staleTime: 5 * 60 * 1000,
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
    // Use slow instance — multi-agent pipeline can take 60-120s
    mutationFn: (req) => apiSlow.post("/trading/analyze", req).then((r) => r.data),
  });
}

export function useGenerateSignal() {
  return useMutation<SignalResult, Error, SignalRequest>({
    mutationFn: (req) => api.post("/trading/signal", req).then((r) => r.data),
  });
}

export function useSignalChecks(status?: "PENDING" | "EVALUATED") {
  return useQuery<{ items: SignalCheckItem[] }>({
    queryKey: ["trading", "signal-checks", status ?? "all"],
    queryFn: () =>
      api.get("/trading/signal-checks", { params: status ? { status } : undefined }).then((r) => r.data),
    staleTime: 30 * 1000,
  });
}

export function useCheckDueSignals() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post("/trading/signal-checks/check-due").then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["trading", "signal-checks"] }),
  });
}

export function useCheckSignal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post(`/trading/signal-checks/${id}/check`).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["trading", "signal-checks"] }),
  });
}

export interface OllamaStatus {
  available: boolean;
  models: string[];
  host: string;
}

export function useOllamaStatus() {
  return useQuery<OllamaStatus>({
    queryKey: ["ollama", "status"],
    queryFn: () => api.get("/trading/ollama/status").then((r) => r.data),
    staleTime: 30 * 1000,
    retry: false,
  });
}

export interface LMStudioStatus {
  available: boolean;
  models: string[];
  active_model: string | null;
  host: string;
}

export function useLMStudioStatus() {
  return useQuery<LMStudioStatus>({
    queryKey: ["lmstudio", "status"],
    queryFn: () => api.get("/trading/lmstudio/status").then((r) => r.data),
    staleTime: 15 * 1000,
    retry: false,
  });
}
