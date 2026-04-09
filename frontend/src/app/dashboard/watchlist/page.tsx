"use client";

import { useRouter } from "next/navigation";
import { Star, Trash2, BarChart2, TrendingUp, TrendingDown } from "lucide-react";
import {
  useWatchlist,
  useRemoveFromWatchlist,
} from "@/lib/hooks/useTrading";
import { formatCurrency, formatDate } from "@/lib/utils/formatters";

function AssetClassBadge({ cls }: { cls: string }) {
  const map: Record<string, string> = {
    CRYPTO: "bg-amber-500/10 text-amber-400 border-amber-500/20",
    EQUITY: "bg-blue-500/10 text-blue-400 border-blue-500/20",
    ETF: "bg-purple-500/10 text-purple-400 border-purple-500/20",
  };
  return (
    <span
      className={`text-xs font-medium px-2 py-0.5 rounded border ${map[cls] ?? "bg-gray-700 text-gray-400 border-gray-600"}`}
    >
      {cls}
    </span>
  );
}

export default function WatchlistPage() {
  const router = useRouter();
  const { data: items = [], isLoading } = useWatchlist();
  const remove = useRemoveFromWatchlist();

  const goAnalyze = (symbol: string, name: string, assetClass: string, exchange?: string | null) => {
    const params = new URLSearchParams({ name, asset_class: assetClass });
    if (exchange) params.set("exchange", exchange);
    router.push(`/dashboard/analysis/${symbol}?${params}`);
  };

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-100 flex items-center gap-2">
            <Star className="w-6 h-6 text-amber-400" fill="currentColor" />
            Watchlist
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            {items.length} asset{items.length !== 1 ? "s" : ""} tracked
          </p>
        </div>
        <button
          onClick={() => router.push("/dashboard/markets")}
          className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-500 text-white rounded-lg transition-colors"
        >
          + Browse Markets
        </button>
      </div>

      {/* Empty state */}
      {!isLoading && items.length === 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-16 text-center">
          <Star className="w-12 h-12 text-gray-700 mx-auto mb-4" />
          <p className="text-gray-400 font-medium mb-2">Your watchlist is empty</p>
          <p className="text-gray-600 text-sm mb-6">
            Go to Markets and star assets you want to track.
          </p>
          <button
            onClick={() => router.push("/dashboard/markets")}
            className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-500 text-white rounded-lg transition-colors"
          >
            Browse Markets
          </button>
        </div>
      )}

      {/* Grid */}
      {isLoading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="bg-gray-900 border border-gray-800 rounded-xl p-4 animate-pulse h-36" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {items.map((item) => {
            const hasPrice = item.price != null;
            return (
              <div
                key={item.id}
                className="bg-gray-900 border border-gray-800 rounded-xl p-4 hover:border-gray-600 transition-colors group flex flex-col gap-3"
              >
                {/* Top row */}
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-2.5">
                    {item.image_url ? (
                      <img src={item.image_url} alt="" className="w-8 h-8 rounded-full" />
                    ) : (
                      <div className="w-8 h-8 rounded-full bg-gray-700 flex items-center justify-center text-xs font-bold text-gray-300">
                        {item.symbol[0]}
                      </div>
                    )}
                    <div>
                      <div className="font-semibold text-gray-100 text-sm">{item.symbol}</div>
                      <div className="text-xs text-gray-500 truncate max-w-[100px]">{item.name}</div>
                    </div>
                  </div>
                  <button
                    onClick={() => remove.mutate(item.symbol)}
                    disabled={remove.isPending}
                    className="p-1 text-gray-700 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-all"
                    title="Remove from watchlist"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>

                {/* Price */}
                <div className="flex items-center justify-between">
                  <span className="font-mono text-lg font-semibold text-gray-100">
                    {hasPrice ? formatCurrency(item.price!, false, "USD") : "—"}
                  </span>
                  <AssetClassBadge cls={item.asset_class} />
                </div>

                {/* Footer */}
                <div className="flex items-center justify-between mt-auto pt-2 border-t border-gray-800">
                  <span className="text-xs text-gray-600">Added {formatDate(item.added_at)}</span>
                  <button
                    onClick={() => goAnalyze(item.symbol, item.name, item.asset_class, item.exchange)}
                    className="flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300 transition-colors"
                  >
                    <BarChart2 className="w-3.5 h-3.5" />
                    Analyze
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
