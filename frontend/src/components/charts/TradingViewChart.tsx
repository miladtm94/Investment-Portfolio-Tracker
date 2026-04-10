"use client";

import { useEffect, useRef } from "react";

declare global {
  interface Window { TradingView: any; }
}

// ─── Symbol mapping ───────────────────────────────────────────────────────────

const CRYPTO_TV: Record<string, string> = {
  BTC:   "BINANCE:BTCUSDT",
  ETH:   "BINANCE:ETHUSDT",
  SOL:   "BINANCE:SOLUSDT",
  BNB:   "BINANCE:BNBUSDT",
  XRP:   "BINANCE:XRPUSDT",
  ADA:   "BINANCE:ADAUSDT",
  AVAX:  "BINANCE:AVAXUSDT",
  DOT:   "BINANCE:DOTUSDT",
  LINK:  "BINANCE:LINKUSDT",
  DOGE:  "BINANCE:DOGEUSDT",
  UNI:   "BINANCE:UNIUSDT",
  AAVE:  "BINANCE:AAVEUSDT",
  ATOM:  "BINANCE:ATOMUSDT",
  LTC:   "BINANCE:LTCUSDT",
  BCH:   "BINANCE:BCHUSDT",
  MATIC: "BINANCE:MATICUSDT",
  ALGO:  "BINANCE:ALGOUSDT",
  XLM:   "BINANCE:XLMUSDT",
  EIGEN: "BINANCE:EIGENUSDT",
};

const NYSE = new Set([
  "JPM","V","BRK-B","JNJ","WMT","BAC","MA","PG","XOM","HD",
  "CVX","ABT","PFE","LLY","UNH","KO","MRK","DIS","VZ","T",
]);

function toTVSymbol(symbol: string, assetClass: string, exchange?: string | null): string {
  const sym = symbol.toUpperCase();
  if (assetClass === "CRYPTO") return CRYPTO_TV[sym] ?? `BINANCE:${sym}USDT`;
  if (exchange && (exchange.includes("ASX") || exchange === "ASX")) return `ASX:${sym}`;
  if (NYSE.has(sym)) return `NYSE:${sym}`;
  return `NASDAQ:${sym}`;
}

// ─── Component ────────────────────────────────────────────────────────────────

export type TVInterval = "1" | "5" | "15" | "60" | "240" | "D" | "W";

export const INTERVALS: { label: string; value: TVInterval }[] = [
  { label: "15m", value: "15" },
  { label: "1H",  value: "60" },
  { label: "4H",  value: "240" },
  { label: "1D",  value: "D" },
  { label: "1W",  value: "W" },
];

interface Props {
  symbol: string;
  assetClass: string;
  exchange?: string | null;
  interval: TVInterval;
  height?: number;
}

export default function TradingViewChart({ symbol, assetClass, exchange, interval, height = 520 }: Props) {
  // Stable container ID per mount — never changes after creation
  const containerIdRef = useRef<string>("");
  if (!containerIdRef.current) {
    containerIdRef.current = `tv_${Math.random().toString(36).slice(2, 9)}`;
  }
  const containerId = containerIdRef.current;

  useEffect(() => {
    const tvSymbol = toTVSymbol(symbol, assetClass, exchange);

    function init() {
      const el = document.getElementById(containerId);
      if (!el || !window.TradingView) return;
      el.innerHTML = "";
      new window.TradingView.widget({
        autosize:           true,
        symbol:             tvSymbol,
        interval,
        timezone:           "Australia/Sydney",
        theme:              "dark",
        style:              "1",          // candlestick
        locale:             "en",
        backgroundColor:    "rgba(17, 24, 39, 1)",   // gray-900
        gridColor:          "rgba(55, 65, 81, 0.2)",
        withdateranges:     true,
        hide_side_toolbar:  false,
        allow_symbol_change: false,
        save_image:         false,
        calendar:           false,
        studies:            ["RSI@tv-basicstudies", "MACD@tv-basicstudies"],
        container_id:       containerId,
      });
    }

    if (window.TradingView) {
      init();
    } else {
      // Load script once; subsequent mounts reuse the already-loaded window.TradingView
      const existing = document.querySelector('script[src*="tradingview.com/tv.js"]');
      if (existing) {
        existing.addEventListener("load", init);
      } else {
        const script = document.createElement("script");
        script.src = "https://s3.tradingview.com/tv.js";
        script.async = true;
        script.onload = init;
        document.head.appendChild(script);
      }
    }

    return () => {
      const el = document.getElementById(containerId);
      if (el) el.innerHTML = "";
    };
  }, [symbol, assetClass, exchange, interval, containerId]);

  return <div id={containerId} style={{ height }} className="w-full" />;
}
