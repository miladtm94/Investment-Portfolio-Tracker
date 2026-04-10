"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle, XCircle, Clock, TrendingUp, BarChart2, Target, Zap, ChevronLeft, ChevronRight } from "lucide-react";
import { api } from "@/lib/api/client";
import { formatCurrency } from "@/lib/utils/formatters";

// ─── Types ────────────────────────────────────────────────────────────────────

interface AnalysisItem {
  id: string;
  symbol: string;
  name: string;
  asset_class: string;
  provider: string;
  horizon: string;
  rec: string;
  score: number | null;
  confidence: string | null;
  target: number | null;
  stop_loss: number | null;
  entry_price: number | null;
  agent_scores: { tech: number; news: number; fund: number } | null;
  outcome_price: number | null;
  outcome_at: string | null;
  outcome_pnl_pct: number | null;
  outcome_correct: boolean | null;
  outcome_note: string | null;
  created_at: string;
}

interface Stats {
  total_analyses: number;
  with_outcomes: number;
  win_rate: number | null;
  avg_score: number | null;
  avg_pnl_pct: number | null;
  by_provider: Record<string, { total: number; wins: number; with_outcomes: number; win_rate: number | null }>;
  by_horizon: Record<string, { total: number; wins: number; with_outcomes: number; win_rate: number | null }>;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const REC_COLOR: Record<string, string> = {
  "STRONG BUY": "text-emerald-400",
  "BUY":        "text-emerald-500",
  "HOLD":       "text-amber-400",
  "SELL":       "text-red-400",
  "STRONG SELL":"text-red-500",
};

const PROVIDER_LABEL: Record<string, string> = {
  claude: "Claude", openai: "GPT-4o", gemini: "Gemini", ollama: "Local",
};

function ScorePill({ score, label }: { score: number | null; label: string }) {
  if (score == null) return <span className="text-gray-600 text-xs">{label}: —</span>;
  const col = score >= 65 ? "text-emerald-400" : score >= 40 ? "text-amber-400" : "text-red-400";
  return <span className={`text-xs font-mono ${col}`}>{label}:{score}</span>;
}

function OutcomeBadge({ correct }: { correct: boolean | null }) {
  if (correct === null) return <span className="text-gray-600 text-xs flex items-center gap-1"><Clock className="w-3 h-3" />Pending</span>;
  if (correct) return <span className="text-emerald-400 text-xs flex items-center gap-1"><CheckCircle className="w-3 h-3" />Correct</span>;
  return <span className="text-red-400 text-xs flex items-center gap-1"><XCircle className="w-3 h-3" />Incorrect</span>;
}

// ─── Outcome modal ────────────────────────────────────────────────────────────

function OutcomeModal({
  item,
  onClose,
  onSave,
}: {
  item: AnalysisItem;
  onClose: () => void;
  onSave: (id: string, price: number, correct: boolean, note: string) => void;
}) {
  const [price, setPrice] = useState(item.outcome_price?.toString() ?? "");
  const [correct, setCorrect] = useState<boolean | null>(item.outcome_correct);
  const [note, setNote] = useState(item.outcome_note ?? "");

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 max-w-md w-full space-y-4">
        <h2 className="text-lg font-semibold text-gray-100">Record Outcome — {item.symbol}</h2>
        <p className="text-sm text-gray-500">
          Analysis: <span className={REC_COLOR[item.rec] ?? "text-gray-300"}>{item.rec}</span> ·
          Entry: {item.entry_price ? formatCurrency(item.entry_price, false, "USD") : "—"}
        </p>

        <div className="space-y-3">
          <div>
            <label className="text-xs text-gray-500 uppercase tracking-wider">Outcome price</label>
            <input
              type="number"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              placeholder="e.g. 85000"
              className="mt-1 w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 outline-none focus:border-blue-600"
            />
          </div>
          <div>
            <label className="text-xs text-gray-500 uppercase tracking-wider mb-1 block">Was the call correct?</label>
            <div className="flex gap-2">
              <button
                onClick={() => setCorrect(true)}
                className={`flex-1 py-2 rounded-lg text-sm font-medium border transition-colors ${correct === true ? "bg-emerald-900/50 text-emerald-400 border-emerald-700" : "border-gray-700 text-gray-500 hover:text-gray-300"}`}
              >
                ✓ Yes
              </button>
              <button
                onClick={() => setCorrect(false)}
                className={`flex-1 py-2 rounded-lg text-sm font-medium border transition-colors ${correct === false ? "bg-red-900/50 text-red-400 border-red-700" : "border-gray-700 text-gray-500 hover:text-gray-300"}`}
              >
                ✗ No
              </button>
            </div>
          </div>
          <div>
            <label className="text-xs text-gray-500 uppercase tracking-wider">Note (optional)</label>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={2}
              className="mt-1 w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 outline-none focus:border-blue-600 resize-none"
            />
          </div>
        </div>

        <div className="flex gap-2 pt-2">
          <button onClick={onClose} className="flex-1 py-2 border border-gray-700 rounded-lg text-sm text-gray-400 hover:text-gray-200">
            Cancel
          </button>
          <button
            disabled={!price || correct === null}
            onClick={() => { if (price && correct !== null) onSave(item.id, parseFloat(price), correct, note); }}
            className="flex-1 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg text-sm font-medium text-white disabled:opacity-50"
          >
            Save Outcome
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Stats Bar ────────────────────────────────────────────────────────────────

function StatsBar({ stats }: { stats: Stats }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
      {[
        { label: "Total Analyses", value: stats.total_analyses, icon: <BarChart2 className="w-4 h-4" /> },
        { label: "With Outcomes", value: stats.with_outcomes, icon: <CheckCircle className="w-4 h-4" /> },
        { label: "Win Rate", value: stats.win_rate != null ? `${stats.win_rate}%` : "—", icon: <Target className="w-4 h-4" />, highlight: stats.win_rate != null && stats.win_rate >= 60 },
        { label: "Avg Score", value: stats.avg_score != null ? stats.avg_score : "—", icon: <Zap className="w-4 h-4" /> },
        { label: "Avg P&L", value: stats.avg_pnl_pct != null ? `${stats.avg_pnl_pct > 0 ? "+" : ""}${stats.avg_pnl_pct}%` : "—", icon: <TrendingUp className="w-4 h-4" />, highlight: stats.avg_pnl_pct != null && stats.avg_pnl_pct > 0 },
      ].map(({ label, value, icon, highlight }) => (
        <div key={label} className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <div className="flex items-center gap-2 text-gray-500 text-xs mb-1">
            {icon}{label}
          </div>
          <div className={`text-xl font-bold ${highlight ? "text-emerald-400" : "text-gray-100"}`}>
            {value}
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function AnalysisHistoryPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [page, setPage] = useState(1);
  const [outcomeModal, setOutcomeModal] = useState<AnalysisItem | null>(null);

  const { data: history, isLoading } = useQuery({
    queryKey: ["analysis", "history", page],
    queryFn: () => api.get(`/analysis/history?page=${page}&page_size=15`).then((r) => r.data),
  });

  const { data: stats } = useQuery({
    queryKey: ["analysis", "stats"],
    queryFn: () => api.get("/analysis/stats").then((r) => r.data),
  });

  const recordOutcome = useMutation({
    mutationFn: ({ id, price, correct, note }: { id: string; price: number; correct: boolean; note: string }) =>
      api.patch(`/analysis/${id}/outcome`, { outcome_price: price, outcome_correct: correct, outcome_note: note }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["analysis"] });
      setOutcomeModal(null);
    },
  });

  const totalPages = history ? Math.ceil(history.total / 15) : 1;

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-4">
        <button onClick={() => router.back()} className="text-gray-500 hover:text-gray-300 transition-colors">
          <ChevronLeft className="w-5 h-5" />
        </button>
        <div>
          <h1 className="text-2xl font-bold text-gray-100">Analysis History</h1>
          <p className="text-sm text-gray-500 mt-0.5">Track AI predictions and record outcomes to measure win rate</p>
        </div>
      </div>

      {/* Stats */}
      {stats && <StatsBar stats={stats} />}

      {/* Table */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        {isLoading ? (
          <div className="p-16 text-center text-gray-500 text-sm">Loading history…</div>
        ) : !history?.items?.length ? (
          <div className="p-16 text-center">
            <p className="text-gray-500 text-sm mb-1">No analyses yet.</p>
            <p className="text-gray-600 text-xs">Run AI analysis on any asset in the Markets page to start tracking.</p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-gray-500 text-xs uppercase tracking-wider">
                <th className="px-4 py-3 text-left">Asset</th>
                <th className="px-4 py-3 text-left">Rec</th>
                <th className="px-4 py-3 text-right hidden sm:table-cell">Score</th>
                <th className="px-4 py-3 text-right hidden md:table-cell">Entry</th>
                <th className="px-4 py-3 text-right hidden md:table-cell">Target</th>
                <th className="px-4 py-3 text-left hidden lg:table-cell">Provider</th>
                <th className="px-4 py-3 text-left">Outcome</th>
                <th className="px-4 py-3 text-right hidden lg:table-cell">P&L</th>
                <th className="px-4 py-3 text-left hidden xl:table-cell">Date</th>
                <th className="px-4 py-3 text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              {history.items.map((item: AnalysisItem) => (
                <tr key={item.id} className="border-b border-gray-800/60 hover:bg-gray-800/30 transition-colors">
                  <td className="px-4 py-3">
                    <div>
                      <button
                        onClick={() => {
                          const params = new URLSearchParams({ name: item.name, asset_class: item.asset_class });
                          router.push(`/dashboard/analysis/${item.symbol}?${params}`);
                        }}
                        className="font-semibold text-gray-100 hover:text-blue-400 transition-colors text-left"
                      >
                        {item.symbol}
                      </button>
                      <div className="text-xs text-gray-500 truncate max-w-[120px]">{item.name}</div>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`font-semibold text-xs ${REC_COLOR[item.rec] ?? "text-gray-300"}`}>{item.rec}</span>
                    <div className="text-[10px] text-gray-600 capitalize">{item.horizon}</div>
                  </td>
                  <td className="px-4 py-3 text-right hidden sm:table-cell">
                    {item.score != null ? (
                      <span className={`font-mono text-sm ${item.score >= 65 ? "text-emerald-400" : item.score >= 40 ? "text-amber-400" : "text-red-400"}`}>
                        {item.score}
                      </span>
                    ) : <span className="text-gray-600">—</span>}
                    {item.agent_scores && (
                      <div className="flex gap-1 justify-end mt-0.5">
                        <ScorePill score={item.agent_scores.tech} label="T" />
                        <ScorePill score={item.agent_scores.news} label="N" />
                        <ScorePill score={item.agent_scores.fund} label="F" />
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right hidden md:table-cell font-mono text-xs text-gray-400">
                    {item.entry_price ? formatCurrency(item.entry_price, false, "USD") : "—"}
                  </td>
                  <td className="px-4 py-3 text-right hidden md:table-cell font-mono text-xs text-gray-400">
                    {item.target ? formatCurrency(item.target, false, "USD") : "—"}
                  </td>
                  <td className="px-4 py-3 hidden lg:table-cell">
                    <span className="text-xs text-gray-500 bg-gray-800 px-2 py-0.5 rounded">
                      {PROVIDER_LABEL[item.provider] ?? item.provider}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <OutcomeBadge correct={item.outcome_correct} />
                    {item.outcome_note && (
                      <div className="text-[10px] text-gray-600 truncate max-w-[100px] mt-0.5">{item.outcome_note}</div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right hidden lg:table-cell">
                    {item.outcome_pnl_pct != null ? (
                      <span className={`font-mono text-xs ${item.outcome_pnl_pct >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                        {item.outcome_pnl_pct > 0 ? "+" : ""}{item.outcome_pnl_pct.toFixed(1)}%
                      </span>
                    ) : <span className="text-gray-600 text-xs">—</span>}
                  </td>
                  <td className="px-4 py-3 hidden xl:table-cell">
                    <div className="text-xs text-gray-600">
                      {new Date(item.created_at).toLocaleDateString("en-AU", { day: "2-digit", month: "short" })}
                    </div>
                    <div className="text-[10px] text-gray-700">
                      {new Date(item.created_at).toLocaleTimeString("en-AU", { hour: "2-digit", minute: "2-digit" })}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => setOutcomeModal(item)}
                      className="text-xs text-gray-500 hover:text-blue-400 border border-gray-700 hover:border-blue-600 px-2 py-1 rounded transition-colors"
                    >
                      {item.outcome_correct === null ? "Record" : "Edit"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="p-1.5 rounded border border-gray-700 text-gray-400 hover:text-gray-200 disabled:opacity-40"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <span className="text-sm text-gray-500">
            Page {page} of {totalPages} · {history?.total ?? 0} analyses
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="p-1.5 rounded border border-gray-700 text-gray-400 hover:text-gray-200 disabled:opacity-40"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Outcome modal */}
      {outcomeModal && (
        <OutcomeModal
          item={outcomeModal}
          onClose={() => setOutcomeModal(null)}
          onSave={(id, price, correct, note) =>
            recordOutcome.mutate({ id, price, correct, note })
          }
        />
      )}
    </div>
  );
}
