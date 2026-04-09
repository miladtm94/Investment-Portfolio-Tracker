"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { TrendingUp, TrendingDown, Star, Search, RefreshCw } from "lucide-react";
import {
  useMarkets,
  useAddToWatchlist,
  useWatchlist,
  type MarketAsset,
} from "@/lib/hooks/useTrading";
import { formatCurrency, formatPercent } from "@/lib/utils/formatters";

function Sparkline({ data, positive }: { data: number[]; positive: boolean }) {
  if (!data?.length) return null;
  const w = 80;
  const h = 28;
  const mn = Math.min(...data);
  const mx = Math.max(...data);
  const rng = mx - mn || 1;
  const pts = data
    .map(
      (v, i) =>
        `${((i / (data.length - 1)) * w).toFixed(1)},${(h - ((v - mn) / rng) * (h - 4) - 2).toFixed(1)}`
    )
    .join(" ");
  const col = positive ? "#10b981" : "#ef4444";
  return (
    <svg width={w} height={h} className="overflow-visible">
      <polyline
        points={pts}
        fill="none"
        stroke={col}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ChangeCell({ value }: { value: number | null | undefined }) {
  if (value == null) return <span className="text-gray-500">—</span>;
  const pos = value >= 0;
  return (
    <span className={pos ? "text-emerald-400" : "text-red-400"}>
      {pos ? "▲" : "▼"} {Math.abs(value).toFixed(2)}%
    </span>
  );
}

function AssetRow({
  asset,
  inWatchlist,
  onWatch,
  onAnalyze,
}: {
  asset: MarketAsset;
  inWatchlist: boolean;
  onWatch: () => void;
  onAnalyze: () => void;
}) {
  const pos = (asset.change_24h ?? 0) >= 0;
  return (
    <tr
      className="border-b border-gray-800 hover:bg-gray-800/50 cursor-pointer transition-colors"
      onClick={onAnalyze}
    >
      <td className="px-4 py-3">
        <div className="flex items-center gap-3">
          {asset.image ? (
            <img src={asset.image} alt="" className="w-7 h-7 rounded-full" />
          ) : (
            <div className="w-7 h-7 rounded-full bg-gray-700 flex items-center justify-center text-xs font-bold text-gray-300">
              {asset.symbol[0]}
            </div>
          )}
          <div>
            <div className="font-semibold text-gray-100 text-sm">{asset.symbol}</div>
            <div className="text-xs text-gray-500 truncate max-w-[140px]">{asset.name}</div>
          </div>
        </div>
      </td>
      <td className="px-4 py-3 text-right font-mono text-sm text-gray-100">
        {asset.price != null ? formatCurrency(asset.price, false, "USD") : "—"}
      </td>
      <td className="px-4 py-3 text-right text-sm">
        <ChangeCell value={asset.change_24h} />
      </td>
      <td className="px-4 py-3 text-right text-sm hidden md:table-cell">
        <ChangeCell value={asset.change_7d} />
      </td>
      <td className="px-4 py-3 text-right text-sm text-gray-400 hidden lg:table-cell">
        {asset.market_cap ? formatCurrency(asset.market_cap, true, "USD") : "—"}
      </td>
      <td className="px-4 py-3 hidden xl:table-cell">
        <Sparkline data={asset.sparkline ?? []} positive={pos} />
      </td>
      <td className="px-4 py-3 text-right">
        <button
          onClick={(e) => {
            e.stopPropagation();
            onWatch();
          }}
          title={inWatchlist ? "In watchlist" : "Add to watchlist"}
          className={`p-1.5 rounded transition-colors ${
            inWatchlist
              ? "text-amber-400 hover:text-amber-300"
              : "text-gray-600 hover:text-amber-400"
          }`}
        >
          <Star className="w-4 h-4" fill={inWatchlist ? "currentColor" : "none"} />
        </button>
      </td>
    </tr>
  );
}

export default function MarketsPage() {
  const router = useRouter();
  const { data, isLoading, refetch, isFetching } = useMarkets();
  const { data: watchlist = [] } = useWatchlist();
  const addToWatchlist = useAddToWatchlist();
  const [search, setSearch] = useState("");
  const [tab, setTab] = useState<"crypto" | "equities">("crypto");

  const watchSymbols = new Set(watchlist.map((w) => w.symbol));

  const allAssets = tab === "crypto" ? (data?.crypto ?? []) : (data?.equities ?? []);
  const filtered = allAssets.filter(
    (a) =>
      a.symbol.toLowerCase().includes(search.toLowerCase()) ||
      a.name.toLowerCase().includes(search.toLowerCase())
  );

  const handleWatch = (asset: MarketAsset) => {
    if (watchSymbols.has(asset.symbol)) return;
    addToWatchlist.mutate({
      symbol: asset.symbol,
      name: asset.name,
      asset_class: asset.asset_class,
      exchange: asset.exchange ?? undefined,
      coingecko_id: asset.coingecko_id ?? undefined,
      image_url: asset.image ?? undefined,
    });
  };

  const handleAnalyze = (asset: MarketAsset) => {
    const params = new URLSearchParams({
      name: asset.name,
      asset_class: asset.asset_class,
      ...(asset.exchange ? { exchange: asset.exchange } : {}),
      ...(asset.coingecko_id ? { coingecko_id: asset.coingecko_id } : {}),
    });
    router.push(`/dashboard/analysis/${asset.symbol}?${params}`);
  };

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">Markets</h1>
          <p className="text-sm text-gray-500 mt-1">Live crypto & equity overview</p>
        </div>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="flex items-center gap-2 px-3 py-2 text-sm text-gray-400 hover:text-gray-200 border border-gray-700 rounded-lg transition-colors"
        >
          <RefreshCw className={`w-4 h-4 ${isFetching ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {/* Tabs + Search */}
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex bg-gray-800 rounded-lg p-1 gap-1">
          {(["crypto", "equities"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-4 py-1.5 rounded text-sm font-medium transition-colors capitalize ${
                tab === t
                  ? "bg-blue-600 text-white"
                  : "text-gray-400 hover:text-gray-200"
              }`}
            >
              {t === "crypto" ? "Crypto" : "Equities"}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2 flex-1 max-w-xs bg-gray-800 border border-gray-700 rounded-lg px-3 py-2">
          <Search className="w-4 h-4 text-gray-500 flex-shrink-0" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search symbol or name…"
            className="bg-transparent text-sm text-gray-200 placeholder-gray-600 outline-none w-full"
          />
        </div>
      </div>

      {/* Table */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        {isLoading ? (
          <div className="p-16 text-center text-gray-500 text-sm">Loading market data…</div>
        ) : filtered.length === 0 ? (
          <div className="p-16 text-center text-gray-500 text-sm">No assets found.</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-gray-500 text-xs uppercase tracking-wider">
                <th className="px-4 py-3 text-left">Asset</th>
                <th className="px-4 py-3 text-right">Price</th>
                <th className="px-4 py-3 text-right">24h</th>
                <th className="px-4 py-3 text-right hidden md:table-cell">7d</th>
                <th className="px-4 py-3 text-right hidden lg:table-cell">Market Cap</th>
                <th className="px-4 py-3 hidden xl:table-cell">7d Chart</th>
                <th className="px-4 py-3 text-right">Watch</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((asset) => (
                <AssetRow
                  key={asset.symbol}
                  asset={asset}
                  inWatchlist={watchSymbols.has(asset.symbol)}
                  onWatch={() => handleWatch(asset)}
                  onAnalyze={() => handleAnalyze(asset)}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>
      <p className="text-xs text-gray-600">Click any row to open AI analysis. Star to add to watchlist.</p>
    </div>
  );
}
