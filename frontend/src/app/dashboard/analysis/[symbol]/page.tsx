"use client";

import { useState } from "react";
import { useParams, useSearchParams, useRouter } from "next/navigation";
import {
  ArrowLeft, Zap, TrendingUp, BarChart2, Newspaper,
  ShieldAlert, Star, ChevronDown,
} from "lucide-react";
import {
  useAnalyzeAsset,
  useAddToWatchlist,
  useWatchlist,
  useRemoveFromWatchlist,
  type Provider,
  type Horizon,
  type AnalysisResult,
  type AssetClass,
} from "@/lib/hooks/useTrading";
import { formatCurrency } from "@/lib/utils/formatters";

// ─── Sub-components ───────────────────────────────────────────────────────────

const REC_STYLES: Record<string, { bg: string; text: string; border: string }> = {
  "STRONG BUY": { bg: "bg-emerald-950", text: "text-emerald-400", border: "border-emerald-700" },
  BUY:          { bg: "bg-emerald-950/60", text: "text-emerald-500", border: "border-emerald-800" },
  HOLD:         { bg: "bg-amber-950/60",   text: "text-amber-400",   border: "border-amber-700"   },
  SELL:         { bg: "bg-red-950/60",     text: "text-red-400",     border: "border-red-800"     },
  "STRONG SELL":{ bg: "bg-red-950",       text: "text-red-400",     border: "border-red-700"     },
};

function RecBadge({ rec }: { rec: string }) {
  const s = REC_STYLES[rec] ?? REC_STYLES["HOLD"];
  return (
    <span className={`px-4 py-1.5 rounded-full text-sm font-bold border tracking-wider ${s.bg} ${s.text} ${s.border}`}>
      {rec}
    </span>
  );
}

function ScoreRing({ score }: { score: number }) {
  const size = 72;
  const r = (size - 8) / 2;
  const circ = 2 * Math.PI * r;
  const fill = (score / 100) * circ;
  const col = score >= 70 ? "#10b981" : score >= 45 ? "#f59e0b" : "#ef4444";
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#1f2937" strokeWidth="5" />
        <circle
          cx={size / 2} cy={size / 2} r={r} fill="none"
          stroke={col} strokeWidth="5"
          strokeDasharray={`${fill} ${circ - fill}`}
          strokeLinecap="round"
          style={{ transition: "stroke-dasharray 1s ease" }}
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center font-mono text-base font-semibold" style={{ color: col }}>
        {score}
      </div>
    </div>
  );
}

function Section({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-blue-400">{icon}</span>
        <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">{title}</h3>
      </div>
      {children}
    </div>
  );
}

function TagList({ items, color }: { items: string[]; color: string }) {
  return (
    <ul className="space-y-1.5">
      {items.map((item, i) => (
        <li key={i} className="flex items-start gap-2 text-sm text-gray-300">
          <span className={`mt-1 w-1.5 h-1.5 rounded-full flex-shrink-0 ${color}`} />
          {item}
        </li>
      ))}
    </ul>
  );
}

function LevelPills({ levels, color }: { levels: number[]; color: string }) {
  return (
    <div className="flex flex-wrap gap-2">
      {levels.map((l, i) => (
        <span key={i} className={`font-mono text-xs px-2.5 py-1 rounded border ${color}`}>
          {formatCurrency(l, false, "USD")}
        </span>
      ))}
    </div>
  );
}

function ProviderBadge({ provider }: { provider: Provider }) {
  const map: Record<Provider, string> = {
    claude: "bg-amber-500/10 text-amber-400 border-amber-500/20",
    openai: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
    gemini: "bg-blue-500/10 text-blue-400 border-blue-500/20",
  };
  const label: Record<Provider, string> = { claude: "Claude", openai: "GPT-4o", gemini: "Gemini" };
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded border ${map[provider]}`}>
      {label[provider]}
    </span>
  );
}

function HorizonBadge({ horizon }: { horizon: Horizon }) {
  return horizon === "trading" ? (
    <span className="text-xs font-medium px-2 py-0.5 rounded border bg-purple-500/10 text-purple-400 border-purple-500/20">
      Trading · Short/Mid Term
    </span>
  ) : (
    <span className="text-xs font-medium px-2 py-0.5 rounded border bg-teal-500/10 text-teal-400 border-teal-500/20">
      Investing · Mid/Long Term
    </span>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function AnalysisPage() {
  const params = useParams();
  const sp = useSearchParams();
  const router = useRouter();

  const symbol = (params.symbol as string).toUpperCase();
  const name = sp.get("name") ?? symbol;
  const assetClass = (sp.get("asset_class") ?? "EQUITY") as AssetClass;
  const exchange = sp.get("exchange") ?? undefined;
  const coingeckoId = sp.get("coingecko_id") ?? undefined;

  const [horizon, setHorizon] = useState<Horizon>("trading");
  const [provider, setProvider] = useState<Provider>("claude");
  const [result, setResult] = useState<AnalysisResult | null>(null);

  const analyze = useAnalyzeAsset();
  const { data: watchlist = [] } = useWatchlist();
  const addWatch = useAddToWatchlist();
  const removeWatch = useRemoveFromWatchlist();
  const inWatchlist = watchlist.some((w) => w.symbol === symbol);

  const handleAnalyze = () => {
    analyze.mutate(
      { symbol, name, asset_class: assetClass, exchange, coingecko_id: coingeckoId, horizon, provider },
      { onSuccess: (data) => setResult(data) }
    );
  };

  const toggleWatch = () => {
    if (inWatchlist) {
      removeWatch.mutate(symbol);
    } else {
      addWatch.mutate({ symbol, name, asset_class: assetClass, exchange, coingecko_id: coingeckoId });
    }
  };

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      {/* Back */}
      <button
        onClick={() => router.back()}
        className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-300 transition-colors"
      >
        <ArrowLeft className="w-4 h-4" /> Back
      </button>

      {/* Asset header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">{name}</h1>
          <div className="flex items-center gap-2 mt-1">
            <span className="font-mono text-sm text-gray-400 bg-gray-800 px-2 py-0.5 rounded">{symbol}</span>
            {exchange && <span className="text-xs text-gray-600">{exchange}</span>}
          </div>
        </div>
        <button
          onClick={toggleWatch}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg border text-sm font-medium transition-colors ${
            inWatchlist
              ? "bg-amber-500/10 text-amber-400 border-amber-500/20 hover:bg-amber-500/20"
              : "bg-gray-800 text-gray-400 border-gray-700 hover:border-amber-500/40 hover:text-amber-400"
          }`}
        >
          <Star className="w-4 h-4" fill={inWatchlist ? "currentColor" : "none"} />
          {inWatchlist ? "In Watchlist" : "Add to Watchlist"}
        </button>
      </div>

      {/* Controls */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
        <div className="flex items-center gap-2 mb-4">
          <Zap className="w-4 h-4 text-amber-400" />
          <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">AI Analysis</h2>
          <span className="text-xs text-gray-600 ml-1">— Powered by Claude · GPT-4o · Gemini</span>
        </div>

        <div className="flex flex-wrap gap-4 items-end">
          {/* Horizon */}
          <div className="flex flex-col gap-1.5">
            <label className="text-xs text-gray-500 uppercase tracking-wider">Strategy</label>
            <div className="flex bg-gray-800 rounded-lg p-1 gap-1">
              {(["trading", "investing"] as Horizon[]).map((h) => (
                <button
                  key={h}
                  onClick={() => setHorizon(h)}
                  className={`px-4 py-1.5 rounded text-sm font-medium transition-colors capitalize ${
                    horizon === h ? "bg-blue-600 text-white" : "text-gray-400 hover:text-gray-200"
                  }`}
                >
                  {h === "trading" ? "⚡ Trading" : "📈 Investing"}
                </button>
              ))}
            </div>
          </div>

          {/* Provider */}
          <div className="flex flex-col gap-1.5">
            <label className="text-xs text-gray-500 uppercase tracking-wider">AI Provider</label>
            <div className="flex bg-gray-800 rounded-lg p-1 gap-1">
              {(["claude", "openai", "gemini"] as Provider[]).map((p) => (
                <button
                  key={p}
                  onClick={() => setProvider(p)}
                  className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${
                    provider === p ? "bg-blue-600 text-white" : "text-gray-400 hover:text-gray-200"
                  }`}
                >
                  {p === "claude" ? "Claude" : p === "openai" ? "GPT-4o" : "Gemini ✦ Free"}
                </button>
              ))}
            </div>
          </div>

          {/* Run button */}
          <button
            onClick={handleAnalyze}
            disabled={analyze.isPending}
            className="px-6 py-2.5 bg-gradient-to-r from-amber-500 to-amber-600 hover:from-amber-400 hover:to-amber-500 text-black font-bold rounded-lg text-sm transition-all disabled:opacity-60 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {analyze.isPending ? (
              <>
                <span className="w-4 h-4 border-2 border-black/30 border-t-black rounded-full animate-spin" />
                Analyzing…
              </>
            ) : (
              <>{result ? "↻ Re-analyze" : "✦ Analyze Now"}</>
            )}
          </button>
        </div>

        {analyze.isError && (
          <p className="mt-3 text-sm text-red-400">
            {(analyze.error as Error)?.message ?? "Analysis failed — please try again."}
          </p>
        )}
      </div>

      {/* Loading */}
      {analyze.isPending && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-16 text-center">
          <div className="w-10 h-10 border-3 border-gray-700 border-t-amber-400 rounded-full animate-spin mx-auto mb-4" style={{ borderWidth: 3 }} />
          <p className="text-gray-300 font-medium mb-1">Running deep analysis…</p>
          <p className="text-gray-600 text-sm">Searching news · Analyzing {horizon === "trading" ? "technicals & momentum" : "fundamentals & valuation"}</p>
        </div>
      )}

      {/* Results */}
      {result && !analyze.isPending && (
        <div className="space-y-4 animate-in fade-in slide-in-from-bottom-4 duration-300">
          {/* Top card: score + rec + summary */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
            <div className="flex items-start gap-6 flex-wrap">
              <ScoreRing score={result.score} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-3 flex-wrap mb-3">
                  <RecBadge rec={result.rec} />
                  <span className="text-sm text-gray-500">Confidence: <span className="text-gray-300 font-medium">{result.confidence}</span></span>
                  <span className="text-sm text-gray-500">Horizon: <span className="text-gray-300 font-medium">{result.horizon}</span></span>
                  <ProviderBadge provider={result._provider} />
                  <HorizonBadge horizon={result._horizon} />
                </div>
                <p className="text-gray-300 text-sm leading-relaxed">{result.summary}</p>
              </div>
            </div>

            {/* Price levels */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-6 pt-5 border-t border-gray-800">
              {[
                { label: "Target Low", value: result.targetLow },
                { label: "Target", value: result.target },
                { label: "Target High", value: result.targetHigh },
                { label: "Stop Loss", value: result.stopLoss },
              ].map(({ label, value }) => (
                <div key={label}>
                  <div className="text-xs text-gray-600 mb-1">{label}</div>
                  <div className="font-mono text-sm font-semibold text-gray-200">
                    {formatCurrency(value, false, "USD")}
                  </div>
                </div>
              ))}
            </div>

            <div className="mt-4 grid grid-cols-2 gap-4">
              <div>
                <div className="text-xs text-gray-600 mb-1">Entry Zone</div>
                <div className="text-sm text-gray-300">{result.entryZone}</div>
              </div>
              <div>
                <div className="text-xs text-gray-600 mb-1">Suggested Allocation</div>
                <div className="text-sm text-gray-300">{result.allocation}</div>
              </div>
            </div>

            {result.strategyNote && (
              <div className="mt-4 p-3 bg-blue-950/30 border border-blue-900/40 rounded-lg">
                <p className="text-xs text-blue-300 leading-relaxed">{result.strategyNote}</p>
              </div>
            )}
          </div>

          {/* Support / Resistance */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Section icon={<TrendingUp className="w-4 h-4" />} title="Support Levels">
              <LevelPills levels={result.support} color="bg-emerald-500 border-emerald-700/60 text-emerald-400" />
            </Section>
            <Section icon={<TrendingUp className="w-4 h-4 rotate-180" />} title="Resistance Levels">
              <LevelPills levels={result.resistance} color="bg-red-900/40 border-red-700/60 text-red-400" />
            </Section>
          </div>

          {/* Technical + Fundamental */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Section icon={<BarChart2 className="w-4 h-4" />} title="Technical Analysis">
              <p className="text-sm text-gray-400 leading-relaxed">{result.technical}</p>
            </Section>
            <Section icon={<TrendingUp className="w-4 h-4" />} title="Fundamental Analysis">
              <p className="text-sm text-gray-400 leading-relaxed">{result.fundamental}</p>
            </Section>
          </div>

          {/* News */}
          <Section icon={<Newspaper className="w-4 h-4" />} title="News & Sentiment">
            <p className="text-sm text-gray-400 leading-relaxed">{result.news}</p>
          </Section>

          {/* Catalysts + Risks */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Section icon={<Zap className="w-4 h-4 text-emerald-400" />} title="Key Catalysts">
              <TagList items={result.catalysts} color="bg-emerald-500" />
            </Section>
            <Section icon={<ShieldAlert className="w-4 h-4 text-red-400" />} title="Key Risks">
              <TagList items={result.risks} color="bg-red-500" />
            </Section>
          </div>
        </div>
      )}

      {/* Prompt when no analysis yet */}
      {!result && !analyze.isPending && !analyze.isError && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-16 text-center">
          <Zap className="w-12 h-12 text-gray-700 mx-auto mb-4" />
          <p className="text-gray-400 font-medium mb-2">No analysis yet</p>
          <p className="text-gray-600 text-sm">
            Select a strategy and provider above, then click <strong className="text-gray-500">Analyze Now</strong>.
          </p>
        </div>
      )}
    </div>
  );
}
