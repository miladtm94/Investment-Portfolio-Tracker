"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { TrendingUp, TrendingDown, Star, Search, RefreshCw, X, Plus } from "lucide-react";
import {
  useMarkets,
  useAddToWatchlist,
  useWatchlist,
  useAssetSearch,
  type MarketAsset,
  type SearchResult,
} from "@/lib/hooks/useTrading";
import { formatCurrency } from "@/lib/utils/formatters";

// ─── Helpers ──────────────────────────────────────────────────────────────────

function Sparkline({ data, positive }: { data: number[]; positive: boolean }) {
  if (!data?.length) return null;
  const w = 80, h = 28;
  const mn = Math.min(...data), mx = Math.max(...data);
  const rng = mx - mn || 1;
  const pts = data
    .map((v, i) => `${((i / (data.length - 1)) * w).toFixed(1)},${(h - ((v - mn) / rng) * (h - 4) - 2).toFixed(1)}`)
    .join(" ");
  const col = positive ? "#10b981" : "#ef4444";
  return (
    <svg width={w} height={h} className="overflow-visible">
      <polyline points={pts} fill="none" stroke={col} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
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

// ─── Asset row ────────────────────────────────────────────────────────────────

function AssetRow({
  asset,
  inWatchlist,
  onWatch,
  onAnalyze,
  onRemove,
  isCustom,
}: {
  asset: MarketAsset;
  inWatchlist: boolean;
  onWatch: () => void;
  onAnalyze: () => void;
  onRemove?: () => void;
  isCustom?: boolean;
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
            <img src={asset.image} alt="" className="w-7 h-7 rounded-full object-cover" onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />
          ) : (
            <div className="w-7 h-7 rounded-full bg-gray-700 flex items-center justify-center text-xs font-bold text-gray-300">
              {asset.symbol[0]}
            </div>
          )}
          <div>
            <div className="font-semibold text-gray-100 text-sm">{asset.symbol}</div>
            <div className="text-xs text-gray-500 truncate max-w-[140px]">{asset.name}</div>
          </div>
          {isCustom && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-900/50 text-blue-400 border border-blue-800 ml-1">added</span>
          )}
        </div>
      </td>
      <td className="px-4 py-3 text-right font-mono text-sm text-gray-100">
        {asset.price != null ? formatCurrency(asset.price, false, "USD") : "—"}
      </td>
      <td className="px-4 py-3 text-right text-sm"><ChangeCell value={asset.change_24h} /></td>
      <td className="px-4 py-3 text-right text-sm hidden md:table-cell"><ChangeCell value={asset.change_7d} /></td>
      <td className="px-4 py-3 text-right text-sm text-gray-400 hidden lg:table-cell">
        {asset.market_cap ? formatCurrency(asset.market_cap, true, "USD") : "—"}
      </td>
      <td className="px-4 py-3 hidden xl:table-cell">
        <Sparkline data={asset.sparkline ?? []} positive={pos} />
      </td>
      <td className="px-4 py-3 text-right">
        <div className="flex items-center justify-end gap-1">
          <button
            onClick={(e) => { e.stopPropagation(); onWatch(); }}
            title={inWatchlist ? "In watchlist" : "Add to watchlist"}
            className={`p-1.5 rounded transition-colors ${inWatchlist ? "text-amber-400 hover:text-amber-300" : "text-gray-600 hover:text-amber-400"}`}
          >
            <Star className="w-4 h-4" fill={inWatchlist ? "currentColor" : "none"} />
          </button>
          {isCustom && onRemove && (
            <button
              onClick={(e) => { e.stopPropagation(); onRemove(); }}
              title="Remove from list"
              className="p-1.5 rounded text-gray-600 hover:text-red-400 transition-colors"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}

// ─── Search result row ────────────────────────────────────────────────────────

function SearchResultItem({
  result,
  onAdd,
  onAnalyze,
  alreadyAdded,
}: {
  result: SearchResult;
  onAdd: () => void;
  onAnalyze: () => void;
  alreadyAdded: boolean;
}) {
  return (
    <div className="flex items-center gap-3 px-3 py-2.5 hover:bg-gray-700/60 cursor-pointer rounded-lg transition-colors group">
      <div
        className="flex items-center gap-3 flex-1 min-w-0"
        onClick={onAnalyze}
      >
        {result.image ? (
          <img src={result.image} alt="" className="w-7 h-7 rounded-full object-cover flex-shrink-0" onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />
        ) : (
          <div className="w-7 h-7 rounded-full bg-gray-700 flex items-center justify-center text-xs font-bold text-gray-300 flex-shrink-0">
            {result.symbol[0]}
          </div>
        )}
        <div className="min-w-0">
          <div className="font-semibold text-gray-100 text-sm">{result.symbol}</div>
          <div className="text-xs text-gray-500 truncate">{result.name}</div>
        </div>
        <span className={`text-[10px] px-1.5 py-0.5 rounded border flex-shrink-0 ${
          result.asset_class === "CRYPTO"
            ? "bg-orange-900/40 text-orange-400 border-orange-800"
            : result.asset_class === "ETF"
            ? "bg-purple-900/40 text-purple-400 border-purple-800"
            : "bg-blue-900/40 text-blue-400 border-blue-800"
        }`}>
          {result.asset_class}
        </span>
      </div>
      <button
        onClick={(e) => { e.stopPropagation(); onAdd(); }}
        disabled={alreadyAdded}
        title={alreadyAdded ? "Already in list" : "Add to markets list"}
        className={`p-1.5 rounded transition-colors flex-shrink-0 ${
          alreadyAdded
            ? "text-gray-600 cursor-default"
            : "text-gray-500 hover:text-emerald-400 hover:bg-emerald-900/30"
        }`}
      >
        <Plus className="w-4 h-4" />
      </button>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function MarketsPage() {
  const router = useRouter();
  const { data, isLoading, refetch, isFetching } = useMarkets();
  const { data: watchlist = [] } = useWatchlist();
  const addToWatchlist = useAddToWatchlist();

  const [tab, setTab] = useState<"crypto" | "equities">("crypto");
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [showDropdown, setShowDropdown] = useState(false);
  const [customAssets, setCustomAssets] = useState<MarketAsset[]>([]);
  const searchRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Debounce the search query 400ms
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => setDebouncedQuery(query), 400);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [query]);

  const { data: searchData, isFetching: isSearching } = useAssetSearch(debouncedQuery);

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const watchSymbols = new Set(watchlist.map((w) => w.symbol));

  // Combine server data + custom-added assets
  const serverAssets = tab === "crypto" ? (data?.crypto ?? []) : (data?.equities ?? []);
  const customForTab = customAssets.filter((a) =>
    tab === "crypto" ? a.asset_class === "CRYPTO" : a.asset_class !== "CRYPTO"
  );
  const serverSymbols = new Set(serverAssets.map((a) => a.symbol));
  const uniqueCustom = customForTab.filter((a) => !serverSymbols.has(a.symbol));
  const allAssets = [...serverAssets, ...uniqueCustom];

  const searchResults =
    debouncedQuery.trim().length > 0
      ? [...(searchData?.crypto ?? []), ...(searchData?.equities ?? [])]
      : [];

  const allSymbols = new Set(allAssets.map((a) => a.symbol));

  const handleWatch = useCallback((asset: MarketAsset) => {
    if (watchSymbols.has(asset.symbol)) return;
    addToWatchlist.mutate({
      symbol: asset.symbol,
      name: asset.name,
      asset_class: asset.asset_class,
      exchange: asset.exchange ?? undefined,
      coingecko_id: asset.coingecko_id ?? undefined,
      image_url: asset.image ?? undefined,
    });
  }, [watchSymbols, addToWatchlist]);

  const handleAnalyze = useCallback((asset: { symbol: string; name: string; asset_class: string; exchange?: string | null; coingecko_id?: string | null }) => {
    const params = new URLSearchParams({
      name: asset.name,
      asset_class: asset.asset_class,
      ...(asset.exchange ? { exchange: asset.exchange } : {}),
      ...(asset.coingecko_id ? { coingecko_id: asset.coingecko_id } : {}),
    });
    router.push(`/dashboard/analysis/${asset.symbol}?${params}`);
  }, [router]);

  const handleAddFromSearch = useCallback((result: SearchResult) => {
    if (allSymbols.has(result.symbol)) return;
    const asset: MarketAsset = {
      symbol: result.symbol,
      name: result.name,
      asset_class: result.asset_class,
      image: result.image ?? null,
      exchange: result.exchange ?? null,
      coingecko_id: result.coingecko_id ?? null,
      price: null,
      change_24h: null,
      change_7d: null,
    };
    setCustomAssets((prev) => [asset, ...prev]);
    setQuery("");
    setDebouncedQuery("");
    setShowDropdown(false);
    // Switch to the right tab
    setTab(result.asset_class === "CRYPTO" ? "crypto" : "equities");
  }, [allSymbols]);

  const handleRemoveCustom = useCallback((symbol: string) => {
    setCustomAssets((prev) => prev.filter((a) => a.symbol !== symbol));
  }, []);

  const customSymbols = new Set(customAssets.map((a) => a.symbol));

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
                tab === t ? "bg-blue-600 text-white" : "text-gray-400 hover:text-gray-200"
              }`}
            >
              {t === "crypto" ? "Crypto" : "Equities"}
            </button>
          ))}
        </div>

        {/* Live search */}
        <div ref={searchRef} className="relative flex-1 max-w-sm">
          <div className="flex items-center gap-2 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 focus-within:border-blue-600 transition-colors">
            <Search className="w-4 h-4 text-gray-500 flex-shrink-0" />
            <input
              value={query}
              onChange={(e) => { setQuery(e.target.value); setShowDropdown(true); }}
              onFocus={() => query && setShowDropdown(true)}
              placeholder="Search any crypto or ticker…"
              className="bg-transparent text-sm text-gray-200 placeholder-gray-600 outline-none w-full"
            />
            {query && (
              <button onClick={() => { setQuery(""); setDebouncedQuery(""); setShowDropdown(false); }}>
                <X className="w-3.5 h-3.5 text-gray-500 hover:text-gray-300" />
              </button>
            )}
            {isSearching && (
              <div className="w-3.5 h-3.5 rounded-full border-2 border-blue-500 border-t-transparent animate-spin flex-shrink-0" />
            )}
          </div>

          {/* Dropdown */}
          {showDropdown && debouncedQuery.trim().length > 0 && (
            <div className="absolute top-full mt-1 left-0 right-0 z-50 bg-gray-800 border border-gray-700 rounded-xl shadow-2xl overflow-hidden">
              {searchResults.length === 0 && !isSearching ? (
                <div className="px-4 py-6 text-center text-sm text-gray-500">
                  No results for &ldquo;{debouncedQuery}&rdquo;
                </div>
              ) : (
                <div className="p-2 max-h-80 overflow-y-auto">
                  {searchData?.crypto && searchData.crypto.length > 0 && (
                    <>
                      <div className="px-2 py-1 text-[10px] uppercase tracking-wider text-gray-500 font-medium">Crypto</div>
                      {searchData.crypto.map((r) => (
                        <SearchResultItem
                          key={r.symbol}
                          result={r}
                          alreadyAdded={allSymbols.has(r.symbol)}
                          onAdd={() => handleAddFromSearch(r)}
                          onAnalyze={() => { setShowDropdown(false); handleAnalyze(r); }}
                        />
                      ))}
                    </>
                  )}
                  {searchData?.equities && searchData.equities.length > 0 && (
                    <>
                      <div className="px-2 py-1 text-[10px] uppercase tracking-wider text-gray-500 font-medium mt-1">Equities & ETFs</div>
                      {searchData.equities.map((r) => (
                        <SearchResultItem
                          key={r.symbol}
                          result={r}
                          alreadyAdded={allSymbols.has(r.symbol)}
                          onAdd={() => handleAddFromSearch(r)}
                          onAnalyze={() => { setShowDropdown(false); handleAnalyze(r); }}
                        />
                      ))}
                    </>
                  )}
                </div>
              )}
              <div className="px-3 py-2 border-t border-gray-700 text-[11px] text-gray-600">
                Click row to analyze · <Plus className="inline w-3 h-3" /> to add to list
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Table */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        {isLoading ? (
          <div className="p-16 text-center text-gray-500 text-sm">Loading market data…</div>
        ) : allAssets.length === 0 ? (
          <div className="p-16 text-center">
            <p className="text-gray-500 text-sm mb-2">No assets loaded.</p>
            <p className="text-gray-600 text-xs">Use the search bar above to find and add any crypto or stock.</p>
          </div>
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
              {allAssets.map((asset) => (
                <AssetRow
                  key={asset.symbol}
                  asset={asset}
                  inWatchlist={watchSymbols.has(asset.symbol)}
                  onWatch={() => handleWatch(asset)}
                  onAnalyze={() => handleAnalyze(asset)}
                  isCustom={customSymbols.has(asset.symbol)}
                  onRemove={customSymbols.has(asset.symbol) ? () => handleRemoveCustom(asset.symbol) : undefined}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>
      <p className="text-xs text-gray-600">Click any row to open AI analysis · Star to add to watchlist · Search to add any asset</p>
    </div>
  );
}
