"""
Market Data Service.

Fetches real-time and historical prices from multiple providers with
Redis caching and automatic fallback chain.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from config import get_settings
from shared.cache import cache_get, cache_set

logger = logging.getLogger(__name__)
settings = get_settings()


class MarketDataService:
    """
    Multi-provider market data service with caching.

    Price priority chain:
      Equities: Polygon → Yahoo Finance → Alpha Vantage
      Crypto:   CoinGecko → CoinMarketCap
    """

    CRYPTO_SYMBOLS = {"BTC", "ETH", "SOL", "USDT", "USDC", "BNB", "XRP", "ADA", "MATIC", "LINK", "DOT", "AVAX"}

    def __init__(self):
        self._http = httpx.AsyncClient(timeout=15.0, limits=httpx.Limits(max_connections=100))

    async def get_price(self, symbol: str) -> Optional[float]:
        """Get current price for a single symbol."""
        cache_key = f"market:price:{symbol}:spot"
        cached = await cache_get(cache_key)
        if cached is not None:
            return cached

        price = None
        if self._is_crypto(symbol):
            price = await self._get_crypto_price(symbol)
        else:
            price = await self._get_equity_price(symbol)

        if price is not None:
            await cache_set(cache_key, price, ttl=60)  # 60s TTL for spot prices

        return price

    async def get_batch_prices(self, symbols: list[str]) -> dict[str, float]:
        """Get current prices for multiple symbols efficiently."""
        if not symbols:
            return {}

        # Check cache first
        result: dict[str, float] = {}
        uncached: list[str] = []

        for sym in symbols:
            cached = await cache_get(f"market:price:{sym}:spot")
            if cached is not None:
                result[sym] = cached
            else:
                uncached.append(sym)

        if not uncached:
            return result

        # Separate equity vs crypto
        crypto_syms = [s for s in uncached if self._is_crypto(s)]
        equity_syms = [s for s in uncached if not self._is_crypto(s)]

        if crypto_syms:
            crypto_prices = await self._get_batch_crypto_prices(crypto_syms)
            result.update(crypto_prices)
            for sym, price in crypto_prices.items():
                await cache_set(f"market:price:{sym}:spot", price, ttl=60)

        if equity_syms:
            equity_prices = await self._get_batch_equity_prices(equity_syms)
            result.update(equity_prices)
            for sym, price in equity_prices.items():
                await cache_set(f"market:price:{sym}:spot", price, ttl=60)

        return result

    async def get_historical_prices(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[dict]:
        """
        Get daily OHLCV prices for a symbol over a date range.
        Returns list of {date, open, high, low, close, volume}.
        """
        cache_key = f"market:history:{symbol}:{start_date.date()}:{end_date.date()}"
        cached = await cache_get(cache_key)
        if cached is not None:
            return cached

        if self._is_crypto(symbol):
            prices = await self._get_crypto_history(symbol, start_date, end_date)
        else:
            prices = await self._get_equity_history(symbol, start_date, end_date)

        if prices:
            # Cache historical data for longer
            await cache_set(cache_key, prices, ttl=3600 * 6)

        return prices

    async def get_price_at_date(self, symbol: str, date: datetime) -> Optional[float]:
        """Get the closing price for a symbol on a specific date."""
        cache_key = f"market:price:{symbol}:{date.date()}:close"
        cached = await cache_get(cache_key)
        if cached is not None:
            return cached

        prices = await self.get_historical_prices(symbol, date, date + timedelta(days=1))
        if prices:
            price = prices[-1]["close"]
            await cache_set(cache_key, price, ttl=86400)  # Cache historical prices 24h
            return price
        return None

    # ─── Equity Providers ────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4))
    async def _get_equity_price(self, symbol: str) -> Optional[float]:
        """Polygon → Yahoo Finance fallback."""
        try:
            return await self._polygon_spot(symbol)
        except Exception as e:
            logger.warning(f"Polygon failed for {symbol}: {e}")

        try:
            return await self._yahoo_spot(symbol)
        except Exception as e:
            logger.warning(f"Yahoo failed for {symbol}: {e}")

        return None

    async def _get_batch_equity_prices(self, symbols: list[str]) -> dict[str, float]:
        """Fetch multiple equity prices."""
        results = {}
        for sym in symbols:
            price = await self._get_equity_price(sym)
            if price is not None:
                results[sym] = price
        return results

    async def _polygon_spot(self, symbol: str) -> Optional[float]:
        """Fetch last trade price from Polygon.io."""
        api_key = settings.polygon_api_key.get_secret_value()
        if not api_key:
            return None

        url = f"https://api.polygon.io/v2/last/trade/{symbol}"
        resp = await self._http.get(url, params={"apiKey": api_key})
        resp.raise_for_status()
        data = resp.json()
        return float(data["results"]["p"])  # price

    async def _yahoo_spot(self, symbol: str) -> Optional[float]:
        """Fetch price from Yahoo Finance (unofficial API)."""
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = await self._http.get(url, headers=headers, params={"interval": "1d", "range": "1d"})
        resp.raise_for_status()
        data = resp.json()
        meta = data["chart"]["result"][0]["meta"]
        return float(meta.get("regularMarketPrice", meta.get("previousClose", 0)))

    async def _get_equity_history(self, symbol: str, start: datetime, end: datetime) -> list[dict]:
        """Fetch OHLCV from Polygon or Yahoo."""
        try:
            return await self._polygon_history(symbol, start, end)
        except Exception:
            pass
        try:
            return await self._yahoo_history(symbol, start, end)
        except Exception:
            return []

    async def _polygon_history(self, symbol: str, start: datetime, end: datetime) -> list[dict]:
        api_key = settings.polygon_api_key.get_secret_value()
        if not api_key:
            return []

        url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/day/{start.strftime('%Y-%m-%d')}/{end.strftime('%Y-%m-%d')}"
        resp = await self._http.get(url, params={"apiKey": api_key, "adjusted": "true"})
        resp.raise_for_status()
        data = resp.json()

        return [
            {
                "date": datetime.fromtimestamp(r["t"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d"),
                "open": r["o"], "high": r["h"], "low": r["l"],
                "close": r["c"], "volume": r["v"],
            }
            for r in data.get("results", [])
        ]

    async def _yahoo_history(self, symbol: str, start: datetime, end: datetime) -> list[dict]:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        headers = {"User-Agent": "Mozilla/5.0"}
        params = {
            "interval": "1d",
            "period1": int(start.timestamp()),
            "period2": int(end.timestamp()),
        }
        resp = await self._http.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()
        result = data["chart"]["result"][0]
        timestamps = result["timestamp"]
        quotes = result["indicators"]["quote"][0]

        return [
            {
                "date": datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d"),
                "open": quotes["open"][i], "high": quotes["high"][i],
                "low": quotes["low"][i], "close": quotes["close"][i],
                "volume": quotes["volume"][i],
            }
            for i, ts in enumerate(timestamps)
            if quotes["close"][i] is not None
        ]

    # ─── Crypto Providers ────────────────────────────────────────────────

    async def _get_crypto_price(self, symbol: str) -> Optional[float]:
        """CoinGecko spot price."""
        prices = await self._get_batch_crypto_prices([symbol])
        return prices.get(symbol)

    async def _get_batch_crypto_prices(self, symbols: list[str]) -> dict[str, float]:
        """Batch CoinGecko price fetch."""
        try:
            return await self._coingecko_batch(symbols)
        except Exception as e:
            logger.warning(f"CoinGecko batch failed: {e}")
            return {}

    async def _coingecko_batch(self, symbols: list[str]) -> dict[str, float]:
        """CoinGecko simple/price endpoint for multiple coins."""
        # Map symbols to CoinGecko IDs
        id_map = self._symbol_to_coingecko_id(symbols)
        coin_ids = list(id_map.values())
        if not coin_ids:
            return {}

        params: dict = {"ids": ",".join(coin_ids), "vs_currencies": "usd"}
        api_key = settings.coingecko_api_key.get_secret_value()
        if api_key:
            params["x_cg_pro_api_key"] = api_key

        resp = await self._http.get("https://api.coingecko.com/api/v3/simple/price", params=params)
        resp.raise_for_status()
        data = resp.json()

        result = {}
        for sym, cg_id in id_map.items():
            if cg_id in data and "usd" in data[cg_id]:
                result[sym] = data[cg_id]["usd"]
        return result

    async def _get_crypto_history(self, symbol: str, start: datetime, end: datetime) -> list[dict]:
        """CoinGecko historical prices."""
        cg_id = self._symbol_to_coingecko_id([symbol]).get(symbol)
        if not cg_id:
            return []

        params = {
            "vs_currency": "usd",
            "from": int(start.timestamp()),
            "to": int(end.timestamp()),
        }
        resp = await self._http.get(f"https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart/range", params=params)
        resp.raise_for_status()
        data = resp.json()

        return [
            {
                "date": datetime.fromtimestamp(p[0] / 1000, tz=timezone.utc).strftime("%Y-%m-%d"),
                "close": p[1], "open": p[1], "high": p[1], "low": p[1], "volume": 0,
            }
            for p in data.get("prices", [])
        ]

    # ─── Utilities ───────────────────────────────────────────────────────

    def _is_crypto(self, symbol: str) -> bool:
        return symbol.upper() in self.CRYPTO_SYMBOLS

    @staticmethod
    def _symbol_to_coingecko_id(symbols: list[str]) -> dict[str, str]:
        MAPPING = {
            "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
            "USDT": "tether", "USDC": "usd-coin", "BNB": "binancecoin",
            "XRP": "ripple", "ADA": "cardano", "MATIC": "matic-network",
            "LINK": "chainlink", "DOT": "polkadot", "AVAX": "avalanche-2",
            "DOGE": "dogecoin", "UNI": "uniswap", "AAVE": "aave",
            "ATOM": "cosmos", "LTC": "litecoin", "BCH": "bitcoin-cash",
            "ALGO": "algorand", "XLM": "stellar",
        }
        return {sym: MAPPING[sym.upper()] for sym in symbols if sym.upper() in MAPPING}

    async def close(self):
        await self._http.aclose()
