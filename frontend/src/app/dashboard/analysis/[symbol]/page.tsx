"use client";

import { useState } from "react";
import { useParams, useSearchParams, useRouter } from "next/navigation";
import {
  ArrowLeft, TrendingUp, TrendingDown, BarChart2, Newspaper,
  ShieldAlert, Star, LayoutTemplate, Target, Brain, Globe,
  Activity, Clock, CheckCircle2, XCircle, Calendar, ChevronRight,
  ArrowUpRight, ArrowDownRight, Minus,
} from "lucide-react";
import {
  useAnalyzeAsset, useAddToWatchlist, useWatchlist,
  useRemoveFromWatchlist, useOllamaStatus, useLMStudioStatus,
  type Provider, type Horizon, type AnalysisResult, type AssetClass,
} from "@/lib/hooks/useTrading";
import { formatCurrency } from "@/lib/utils/formatters";
import TradingViewChart, { INTERVALS, type TVInterval } from "@/components/charts/TradingViewChart";
import Link from "next/link";
import clsx from "clsx";

// ─── Helpers ─────────────────────────────────────────────────────────────────

const REC_CONFIG: Record<string, { bg: string; text: string; border: string; icon: React.ReactNode }> = {
  "STRONG BUY": { bg: "bg-emerald-950",    text: "text-emerald-300", border: "border-emerald-600", icon: <ArrowUpRight className="w-5 h-5" /> },
  "BUY":        { bg: "bg-emerald-950/50", text: "text-emerald-400", border: "border-emerald-800", icon: <ArrowUpRight className="w-5 h-5" /> },
  "HOLD":       { bg: "bg-amber-950/50",   text: "text-amber-400",   border: "border-amber-700",   icon: <Minus className="w-5 h-5" /> },
  "SELL":       { bg: "bg-red-950/50",     text: "text-red-400",     border: "border-red-800",     icon: <ArrowDownRight className="w-5 h-5" /> },
  "STRONG SELL":{ bg: "bg-red-950",        text: "text-red-300",     border: "border-red-600",     icon: <ArrowDownRight className="w-5 h-5" /> },
};

function scoreColor(s: number) {
  if (s >= 70) return "#10b981";
  if (s >= 45) return "#f59e0b";
  return "#ef4444";
}

function ScoreRing({ score }: { score: number }) {
  const size = 80;
  const r = (size - 10) / 2;
  const circ = 2 * Math.PI * r;
  const fill = (score / 100) * circ;
  const col = scoreColor(score);
  return (
    <div className="relative flex-shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="#1f2937" strokeWidth="6" />
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={col} strokeWidth="6"
          strokeDasharray={`${fill} ${circ - fill}`} strokeLinecap="round"
          style={{ transition: "stroke-dasharray 1.2s ease" }} />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="font-mono text-lg font-bold" style={{ color: col }}>{score}</span>
        <span className="text-[9px] text-gray-500 uppercase tracking-widest">score</span>
      </div>
    </div>
  );
}

function AgentScoreBar({ label, score, color }: { label: string; score?: number; color: string }) {
  if (score == null) return null;
  return (
    <div className="flex items-center gap-3">
      <span className="text-xs text-gray-500 w-14 flex-shrink-0">{label}</span>
      <div className="flex-1 bg-gray-800 rounded-full h-1.5 overflow-hidden">
        <div className={`h-full rounded-full transition-all duration-700 ${color}`} style={{ width: `${score}%` }} />
      </div>
      <span className="text-xs font-mono text-gray-400 w-7 text-right">{score}</span>
    </div>
  );
}

function SentimentBadge({ sentiment }: { sentiment?: string }) {
  if (!sentiment) return null;
  const map: Record<string, string> = {
    BULLISH: "text-emerald-400 bg-emerald-400/10 border-emerald-500/20",
    BEARISH: "text-red-400 bg-red-400/10 border-red-500/20",
    MIXED:   "text-amber-400 bg-amber-400/10 border-amber-500/20",
    NEUTRAL: "text-gray-400 bg-gray-400/10 border-gray-500/20",
  };
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded border ${map[sentiment] ?? map.NEUTRAL}`}>
      {sentiment}
    </span>
  );
}

function Panel({ title, icon, children, accent }: {
  title: string; icon: React.ReactNode; children: React.ReactNode; accent?: string;
}) {
  return (
    <div className={`bg-gray-900 border rounded-xl overflow-hidden ${accent ?? "border-gray-800"}`}>
      <div className={`flex items-center gap-2.5 px-5 py-3.5 border-b ${accent ? accent.replace("border-", "border-b-") : "border-b-gray-800"}`}>
        <span className="text-blue-400">{icon}</span>
        <h3 className="text-xs font-semibold text-gray-300 uppercase tracking-widest">{title}</h3>
      </div>
      <div className="p-5">{children}</div>
    </div>
  );
}

function Bullet({ items, color }: { items: string[]; color: string }) {
  return (
    <ul className="space-y-2">
      {items.map((item, i) => (
        <li key={i} className="flex items-start gap-2.5 text-sm text-gray-300 leading-relaxed">
          <span className={`mt-1.5 w-1.5 h-1.5 rounded-full flex-shrink-0 ${color}`} />
          {item}
        </li>
      ))}
    </ul>
  );
}

function PriceTag({ label, value, sub, accent }: { label: string; value?: number | null; sub?: string; accent?: string }) {
  return (
    <div className={`rounded-lg p-3 border ${accent ?? "bg-gray-800/40 border-gray-700/50"}`}>
      <div className="text-xs text-gray-500 mb-1">{label}</div>
      <div className="font-mono text-sm font-semibold text-gray-100">
        {value != null ? formatCurrency(value, false, "USD") : "—"}
      </div>
      {sub && <div className="text-[10px] text-gray-600 mt-0.5">{sub}</div>}
    </div>
  );
}

// ─── Main ─────────────────────────────────────────────────────────────────────

export default function AnalysisPage() {
  const params = useParams();
  const sp = useSearchParams();
  const router = useRouter();

  const symbol      = (params.symbol as string).toUpperCase();
  const name        = sp.get("name") ?? symbol;
  const assetClass  = (sp.get("asset_class") ?? "EQUITY") as AssetClass;
  const exchange    = sp.get("exchange") ?? undefined;
  const coingeckoId = sp.get("coingecko_id") ?? undefined;

  const [horizon, setHorizon]   = useState<Horizon>("trading");
  const [provider, setProvider] = useState<Provider>("gemini");
  const [interval, setInterval] = useState<TVInterval>("D");
  const [result, setResult]     = useState<AnalysisResult | null>(null);
  const [asOfDate, setAsOfDate] = useState<string>("");   // "" = now, "YYYY-MM-DD" = historical

  const analyze      = useAnalyzeAsset();
  const { data: ollamaStatus }   = useOllamaStatus();
  const { data: lmStudioStatus } = useLMStudioStatus();
  const { data: watchlist = [] } = useWatchlist();
  const addWatch     = useAddToWatchlist();
  const removeWatch  = useRemoveFromWatchlist();
  const inWatchlist  = watchlist.some((w) => w.symbol === symbol);

  const today = new Date().toISOString().split("T")[0];
  const isHistorical = !!asOfDate && asOfDate !== today;

  const handleAnalyze = () => {
    analyze.mutate(
      {
        symbol, name, asset_class: assetClass, exchange, coingecko_id: coingeckoId,
        horizon, provider,
        as_of_date: asOfDate || null,
      },
      { onSuccess: (data) => setResult(data) }
    );
  };

  const toggleWatch = () => {
    if (inWatchlist) removeWatch.mutate(symbol);
    else addWatch.mutate({ symbol, name, asset_class: assetClass, exchange, coingecko_id: coingeckoId });
  };

  // Derived display
  const rec = result?.rec ?? "HOLD";
  const recCfg = REC_CONFIG[rec] ?? REC_CONFIG["HOLD"];
  const riskReward = result
    ? ((result.target - (result.stopLoss ?? 0)) / ((result.stopLoss ?? 0) - (result.targetLow ?? result.target)))
    : null;

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-5">

      {/* Back */}
      <button onClick={() => router.back()}
        className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-300 transition-colors">
        <ArrowLeft className="w-4 h-4" /> Back
      </button>

      {/* ── Asset header ── */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">{name}</h1>
          <div className="flex items-center gap-2 mt-1 flex-wrap">
            <span className="font-mono text-sm text-gray-400 bg-gray-800 px-2 py-0.5 rounded">{symbol}</span>
            {exchange && <span className="text-xs text-gray-500">{exchange}</span>}
            <span className="text-xs text-gray-600 bg-gray-800/60 px-2 py-0.5 rounded">{assetClass}</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Link href="/dashboard/analysis/history"
            className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-300 border border-gray-700 hover:border-gray-600 px-3 py-1.5 rounded-lg transition-colors">
            <Clock className="w-3.5 h-3.5" /> Analysis History
          </Link>
          <button onClick={toggleWatch}
            className={clsx("flex items-center gap-2 px-4 py-2 rounded-lg border text-sm font-medium transition-colors",
              inWatchlist
                ? "bg-amber-500/10 text-amber-400 border-amber-500/20 hover:bg-amber-500/20"
                : "bg-gray-800 text-gray-400 border-gray-700 hover:border-amber-500/40 hover:text-amber-400"
            )}>
            <Star className="w-4 h-4" fill={inWatchlist ? "currentColor" : "none"} />
            {inWatchlist ? "In Watchlist" : "Add to Watchlist"}
          </button>
        </div>
      </div>

      {/* ── TradingView Chart ── */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-gray-800">
          <div className="flex items-center gap-2 text-xs text-gray-500">
            <LayoutTemplate className="w-3.5 h-3.5" />
            <span>TradingView · Live Candlestick Chart</span>
          </div>
          <div className="flex items-center gap-1">
            {INTERVALS.map(({ label, value }) => (
              <button key={value} onClick={() => setInterval(value)}
                className={clsx("px-2.5 py-1 rounded text-xs font-medium transition-colors",
                  interval === value ? "bg-blue-600 text-white" : "text-gray-500 hover:text-gray-300 hover:bg-gray-800"
                )}>
                {label}
              </button>
            ))}
          </div>
        </div>
        <TradingViewChart symbol={symbol} assetClass={assetClass} exchange={exchange} interval={interval} height={500} />
      </div>

      {/* ── Analysis Controls ── */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
        <div className="flex items-center gap-2 mb-5">
          <Brain className="w-4 h-4 text-amber-400" />
          <h2 className="text-sm font-semibold text-gray-200 uppercase tracking-widest">AI Analysis Engine</h2>
          <span className="text-xs text-gray-600">· multi-agent · grounded in live market data</span>
          {ollamaStatus?.available && (
            <span className="text-[10px] px-1.5 py-0.5 rounded border bg-violet-900/30 text-violet-400 border-violet-700">
              Local Ollama ready
            </span>
          )}
        </div>

        <div className="flex flex-wrap gap-5 items-end">

          {/* Strategy */}
          <div className="flex flex-col gap-1.5">
            <label className="text-xs text-gray-500 uppercase tracking-wider">Strategy</label>
            <div className="flex bg-gray-800 rounded-lg p-1 gap-1">
              {(["trading", "investing"] as Horizon[]).map((h) => (
                <button key={h} onClick={() => setHorizon(h)}
                  className={clsx("px-4 py-1.5 rounded text-sm font-medium transition-colors",
                    horizon === h ? "bg-blue-600 text-white" : "text-gray-400 hover:text-gray-200"
                  )}>
                  {h === "trading" ? "⚡ Trading" : "📈 Investing"}
                </button>
              ))}
            </div>
          </div>

          {/* Analysis Date */}
          <div className="flex flex-col gap-1.5">
            <label className="text-xs text-gray-500 uppercase tracking-wider flex items-center gap-1.5">
              <Calendar className="w-3 h-3" />
              Analysis Date
            </label>
            <div className="flex items-center gap-2">
              <input
                type="date"
                value={asOfDate}
                max={today}
                onChange={(e) => setAsOfDate(e.target.value)}
                className="bg-gray-800 border border-gray-700 text-sm text-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500/30"
              />
              {asOfDate && (
                <button onClick={() => setAsOfDate("")}
                  className="text-xs text-gray-500 hover:text-gray-300 border border-gray-700 rounded px-2 py-1.5">
                  Now
                </button>
              )}
            </div>
            {isHistorical && (
              <p className="text-[11px] text-amber-500">
                Historical mode — data up to {asOfDate} only
              </p>
            )}
          </div>

          {/* Provider */}
          <div className="flex flex-col gap-1.5">
            <label className="text-xs text-gray-500 uppercase tracking-wider">AI Provider</label>
            <div className="flex bg-gray-800 rounded-lg p-1 gap-1 flex-wrap">
              {(["gemini", "claude", "openai"] as Provider[]).map((p) => (
                <button key={p} onClick={() => setProvider(p)}
                  className={clsx("px-3 py-1.5 rounded text-sm font-medium transition-colors",
                    provider === p ? "bg-blue-600 text-white" : "text-gray-400 hover:text-gray-200"
                  )}>
                  {p === "claude" ? "Claude" : p === "openai" ? "GPT-4o" : "Gemini ✦"}
                </button>
              ))}
              <button onClick={() => setProvider("ollama")} disabled={!ollamaStatus?.available}
                title={ollamaStatus?.available
                  ? `Ollama · ${ollamaStatus.models.join(", ")}`
                  : "Ollama not running — start with: ollama serve"}
                className={clsx("px-3 py-1.5 rounded text-sm font-medium transition-colors flex items-center gap-1.5",
                  provider === "ollama"
                    ? "bg-violet-600 text-white"
                    : ollamaStatus?.available
                    ? "text-violet-400 hover:text-violet-200 hover:bg-violet-900/30"
                    : "text-gray-700 cursor-not-allowed"
                )}>
                <span className={clsx("w-1.5 h-1.5 rounded-full", ollamaStatus?.available ? "bg-violet-400" : "bg-gray-700")} />
                Ollama
              </button>
              <button onClick={() => setProvider("lmstudio")} disabled={!lmStudioStatus?.available}
                title={lmStudioStatus?.available
                  ? `LM Studio · ${lmStudioStatus.active_model ?? lmStudioStatus.models[0]}`
                  : "LM Studio server not running — enable in LM Studio → Local Server tab"}
                className={clsx("px-3 py-1.5 rounded text-sm font-medium transition-colors flex items-center gap-1.5",
                  provider === "lmstudio"
                    ? "bg-teal-600 text-white"
                    : lmStudioStatus?.available
                    ? "text-teal-400 hover:text-teal-200 hover:bg-teal-900/30"
                    : "text-gray-700 cursor-not-allowed"
                )}>
                <span className={clsx("w-1.5 h-1.5 rounded-full", lmStudioStatus?.available ? "bg-teal-400" : "bg-gray-700")} />
                LM Studio
              </button>
            </div>
          </div>

          {/* Run button */}
          <button onClick={handleAnalyze} disabled={analyze.isPending}
            className="px-7 py-2.5 bg-gradient-to-r from-amber-500 to-amber-600 hover:from-amber-400 hover:to-amber-500
              text-black font-bold rounded-lg text-sm transition-all disabled:opacity-60 disabled:cursor-not-allowed
              flex items-center gap-2">
            {analyze.isPending ? (
              <>
                <span className="w-4 h-4 border-2 border-black/30 border-t-black rounded-full animate-spin" />
                Analyzing…
              </>
            ) : (
              <>{result ? "↻ Re-Analyze" : "✦ Run Analysis"}</>
            )}
          </button>
        </div>

        {analyze.isError && (
          <div className="mt-4 flex items-start gap-2 text-sm text-red-400 bg-red-400/5 border border-red-400/20 rounded-lg px-4 py-3">
            <ShieldAlert className="w-4 h-4 flex-shrink-0 mt-0.5" />
            {(analyze.error as Error)?.message ?? "Analysis failed — please try again."}
          </div>
        )}
      </div>

      {/* ── Loading State ── */}
      {analyze.isPending && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-12 text-center">
          <div className="relative w-16 h-16 mx-auto mb-6">
            <div className="absolute inset-0 border-4 border-gray-800 rounded-full" />
            <div className="absolute inset-0 border-4 border-t-amber-400 border-r-transparent border-b-transparent border-l-transparent rounded-full animate-spin" />
            <Brain className="w-6 h-6 text-amber-400/60 absolute inset-0 m-auto" />
          </div>
          <p className="text-gray-200 font-semibold text-lg mb-2">Running multi-agent analysis…</p>
          <div className="text-gray-500 text-sm space-y-1">
            <p>Technical Agent · News Agent · Fundamental Agent running in parallel</p>
            <p className="text-gray-600">Synthesis Agent compiling final recommendation</p>
            {isHistorical && <p className="text-amber-600">Historical mode — data up to {asOfDate}</p>}
          </div>
        </div>
      )}

      {/* ── Empty State ── */}
      {!result && !analyze.isPending && !analyze.isError && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-12 text-center">
          <Brain className="w-14 h-14 text-gray-800 mx-auto mb-4" />
          <p className="text-gray-400 font-medium mb-2">No analysis yet</p>
          <p className="text-gray-600 text-sm max-w-md mx-auto">
            Select a strategy, optionally pick a historical date, then click{" "}
            <strong className="text-gray-400">Run Analysis</strong>.
            The multi-agent pipeline will analyze chart data, news, and fundamentals.
          </p>
        </div>
      )}

      {/* ══════════════════════════════════════════════════════════════
          RESULTS
      ══════════════════════════════════════════════════════════════ */}
      {result && !analyze.isPending && (
        <div className="space-y-4 animate-in fade-in slide-in-from-bottom-4 duration-300">

          {/* ── Historical banner ── */}
          {result._as_of_date && (
            <div className="flex items-center gap-3 px-4 py-3 bg-amber-500/5 border border-amber-500/20 rounded-xl">
              <Calendar className="w-4 h-4 text-amber-400 flex-shrink-0" />
              <div className="flex-1 text-sm">
                <span className="text-amber-300 font-medium">Historical Analysis</span>
                <span className="text-amber-500/70 ml-2">
                  Based on data available up to <strong className="text-amber-400">{result._as_of_date}</strong>.
                  Entry price at analysis date: <strong className="font-mono text-amber-400">
                    {result._entry_price ? formatCurrency(result._entry_price, false, "USD") : "—"}
                  </strong>
                </span>
              </div>
              {result._analysis_id && (
                <Link href="/dashboard/analysis/history"
                  className="text-xs text-amber-400 hover:text-amber-300 border border-amber-500/30 rounded-lg px-3 py-1.5 flex items-center gap-1 flex-shrink-0 hover:bg-amber-500/10 transition-colors">
                  Record outcome <ChevronRight className="w-3 h-3" />
                </Link>
              )}
            </div>
          )}

          {/* ── Row 1: Executive Summary ── */}
          <div className={clsx("rounded-xl border p-6", recCfg.bg, recCfg.border)}>
            <div className="flex items-start gap-6 flex-wrap">

              {/* Score */}
              <ScoreRing score={result.score} />

              {/* Rec + badges */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-3 flex-wrap mb-3">
                  <span className={clsx("flex items-center gap-1.5 px-4 py-1.5 rounded-full text-base font-bold border tracking-widest", recCfg.bg, recCfg.text, recCfg.border)}>
                    {recCfg.icon} {rec}
                  </span>
                  <span className="text-sm text-gray-400">
                    Confidence: <span className={clsx("font-semibold", result.confidence === "High" ? "text-emerald-400" : result.confidence === "Low" ? "text-red-400" : "text-amber-400")}>
                      {result.confidence}
                    </span>
                  </span>
                  <span className="text-xs px-2 py-0.5 rounded border bg-gray-800/60 text-gray-400 border-gray-700">
                    {horizon === "trading" ? "⚡ Trading" : "📈 Investing"} · {result.horizon}
                  </span>
                  <span className={clsx("text-xs font-medium px-2 py-0.5 rounded border",
                    provider === "claude"  ? "bg-amber-500/10 text-amber-400 border-amber-500/20" :
                    provider === "openai" ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" :
                    provider === "ollama" ? "bg-violet-500/10 text-violet-400 border-violet-500/20" :
                    "bg-blue-500/10 text-blue-400 border-blue-500/20"
                  )}>
                    {provider === "claude" ? "Claude" : provider === "openai" ? "GPT-4o" : provider === "ollama" ? "Local · Ollama" : "Gemini"}
                  </span>
                </div>
                <p className="text-gray-200 text-sm leading-relaxed">{result.summary}</p>
              </div>

              {/* Agent scores */}
              {result._agent_scores && (
                <div className="flex-shrink-0 w-48 space-y-2 pt-1">
                  <p className="text-[10px] text-gray-600 uppercase tracking-widest mb-2">Agent Scores</p>
                  <AgentScoreBar label="Technical" score={result._agent_scores.tech} color="bg-blue-500" />
                  <AgentScoreBar label="News" score={result._agent_scores.news} color="bg-purple-500" />
                  <AgentScoreBar label="Fundamental" score={result._agent_scores.fund} color="bg-teal-500" />
                </div>
              )}
            </div>
          </div>

          {/* ── Row 2: Price Map ── */}
          <Panel title="Price Map & Trade Plan" icon={<Target className="w-4 h-4" />}>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-5">
              <PriceTag label="Entry Zone" value={undefined} sub={result.entryZone}
                accent="bg-blue-950/30 border-blue-800/40" />
              <PriceTag label="Target Low" value={result.targetLow}
                accent="bg-emerald-950/20 border-emerald-900/30" />
              <PriceTag label="Target" value={result.target}
                accent="bg-emerald-950/40 border-emerald-700/40" />
              <PriceTag label="Target High" value={result.targetHigh}
                accent="bg-emerald-950/60 border-emerald-600/50" />
              <PriceTag label="Stop Loss" value={result.stopLoss}
                accent="bg-red-950/30 border-red-800/40" />
              <div className="rounded-lg p-3 border bg-gray-800/40 border-gray-700/50">
                <div className="text-xs text-gray-500 mb-1">R/R Ratio</div>
                <div className={clsx("font-mono text-sm font-semibold",
                  riskReward && riskReward > 2 ? "text-emerald-400" : riskReward && riskReward < 1 ? "text-red-400" : "text-amber-400"
                )}>
                  {riskReward && isFinite(riskReward) ? `${riskReward.toFixed(1)}:1` : "—"}
                </div>
                <div className="text-[10px] text-gray-600 mt-0.5">Risk / Reward</div>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <div className="text-xs text-gray-500 mb-2">Suggested Allocation</div>
                <p className="text-sm text-gray-300">{result.allocation}</p>
              </div>
              {result.strategyNote && (
                <div>
                  <div className="text-xs text-gray-500 mb-2">Strategy Note</div>
                  <p className="text-sm text-gray-400 leading-relaxed">{result.strategyNote}</p>
                </div>
              )}
            </div>
          </Panel>

          {/* ── Row 3: Key Levels ── */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Panel title="Support Levels" icon={<TrendingUp className="w-4 h-4 text-emerald-400" />}>
              <div className="flex flex-wrap gap-2">
                {(result.support ?? []).map((l, i) => (
                  <span key={i} className="font-mono text-xs px-3 py-1.5 rounded-lg border bg-emerald-950/20 border-emerald-800/40 text-emerald-400">
                    {formatCurrency(l, false, "USD")}
                  </span>
                ))}
                {(result.support ?? []).length === 0 && <span className="text-gray-600 text-sm">No levels identified</span>}
              </div>
            </Panel>
            <Panel title="Resistance Levels" icon={<TrendingDown className="w-4 h-4 text-red-400" />}>
              <div className="flex flex-wrap gap-2">
                {(result.resistance ?? []).map((l, i) => (
                  <span key={i} className="font-mono text-xs px-3 py-1.5 rounded-lg border bg-red-950/20 border-red-800/40 text-red-400">
                    {formatCurrency(l, false, "USD")}
                  </span>
                ))}
                {(result.resistance ?? []).length === 0 && <span className="text-gray-600 text-sm">No levels identified</span>}
              </div>
            </Panel>
          </div>

          {/* ── Row 4: Technical + Fundamental ── */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Panel title="Technical Analysis" icon={<BarChart2 className="w-4 h-4" />}>
              <p className="text-sm text-gray-300 leading-relaxed whitespace-pre-line">{result.technical}</p>
            </Panel>
            <Panel title="Fundamental Analysis" icon={<Activity className="w-4 h-4" />}>
              <p className="text-sm text-gray-300 leading-relaxed whitespace-pre-line">{result.fundamental}</p>
            </Panel>
          </div>

          {/* ── Row 5: News & Macro ── */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Panel title="News & Market Sentiment" icon={<Newspaper className="w-4 h-4" />}>
              <div className="flex items-center gap-2 mb-3">
                <span className="text-xs text-gray-500">Overall Sentiment:</span>
                <SentimentBadge sentiment={result.newsSentiment} />
              </div>
              <p className="text-sm text-gray-300 leading-relaxed whitespace-pre-line">{result.news}</p>
            </Panel>
            <Panel title="Macro Context" icon={<Globe className="w-4 h-4" />}>
              <p className="text-sm text-gray-300 leading-relaxed whitespace-pre-line">
                {result.macroContext ?? "No macro context available for this analysis."}
              </p>
            </Panel>
          </div>

          {/* ── Row 6: Catalysts + Risks ── */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Panel title="Key Catalysts" icon={<CheckCircle2 className="w-4 h-4 text-emerald-400" />} accent="border-emerald-900/40">
              <Bullet items={result.catalysts ?? []} color="bg-emerald-500" />
            </Panel>
            <Panel title="Key Risks" icon={<XCircle className="w-4 h-4 text-red-400" />} accent="border-red-900/40">
              <Bullet items={result.risks ?? []} color="bg-red-500" />
            </Panel>
          </div>

          {/* ── Row 7: Outcome tracking ── */}
          {result._analysis_id && (
            <div className="flex items-center justify-between gap-4 px-5 py-4 bg-gray-900 border border-gray-800 rounded-xl">
              <div className="flex items-center gap-3">
                <Clock className="w-4 h-4 text-gray-500" />
                <div>
                  <p className="text-sm text-gray-300 font-medium">Track this prediction's outcome</p>
                  <p className="text-xs text-gray-600">
                    Once the analysis timeframe expires, record whether the call was correct to build your win-rate stats.
                  </p>
                </div>
              </div>
              <Link href="/dashboard/analysis/history"
                className="flex items-center gap-2 px-4 py-2 rounded-lg border border-gray-700 hover:border-gray-600 bg-gray-800/50 hover:bg-gray-800 text-sm text-gray-300 hover:text-gray-100 transition-colors flex-shrink-0">
                View History <ChevronRight className="w-4 h-4" />
              </Link>
            </div>
          )}

        </div>
      )}
    </div>
  );
}
