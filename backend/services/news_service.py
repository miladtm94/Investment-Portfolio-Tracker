"""
News Service — Phase 2 of AI Analysis Enhancement Plan.

Fetches recent news headlines for an asset and returns a formatted prompt string
with keyword-based sentiment labels.

Sources (in priority order):
  PRIMARY   → Yahoo Finance news search (free, no key, works for crypto + equities)
  SECONDARY → Alpha Vantage NEWS_SENTIMENT (requires ALPHA_VANTAGE_API_KEY, equities)

Results cached in Redis for 30 minutes.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from config import get_settings
from shared.cache import cache_get, cache_set

logger = logging.getLogger(__name__)
settings = get_settings()

# ─── Sentiment keyword sets ────────────────────────────────────────────────────

_BULLISH_WORDS = {
    "rally", "surge", "rise", "gain", "bull", "record", "high", "exceed", "beat",
    "strong", "upgrade", "soar", "jump", "profit", "positive", "support", "recovery",
    "boost", "inflow", "adoption", "approval", "partnership", "launch", "breakthrough",
    "outperform", "accumulation", "halving", "etf", "institutional", "buy", "long",
    "breakout", "all-time", "ath", "growth", "expand", "interest", "optimism",
}
_BEARISH_WORDS = {
    "drop", "fall", "crash", "bear", "decline", "sell", "downgrade", "loss", "weak",
    "below", "miss", "negative", "plunge", "slump", "cut", "fear", "risk", "warning",
    "concern", "trouble", "outflow", "hack", "breach", "ban", "restrict", "liquidation",
    "insolvency", "fraud", "investigation", "lawsuit", "default", "inflation",
    "overvalued", "bubble", "selloff", "capitulation", "recession", "rate hike",
    "caution", "pressure", "uncertainty", "volatile",
}


def _keyword_sentiment(title: str) -> str:
    text = title.lower()
    bull = sum(1 for w in _BULLISH_WORDS if w in text)
    bear = sum(1 for w in _BEARISH_WORDS if w in text)
    if bull > bear:
        return "BULLISH"
    elif bear > bull:
        return "BEARISH"
    return "NEUTRAL"


def _time_ago(unix_ts: float) -> str:
    age_h = (datetime.now(timezone.utc).timestamp() - unix_ts) / 3600
    if age_h < 1:
        return f"{int(age_h * 60)}m ago"
    elif age_h < 24:
        return f"{int(age_h)}h ago"
    else:
        return f"{int(age_h / 24)}d ago"


# ─── Data model ───────────────────────────────────────────────────────────────

@dataclass
class NewsItem:
    title: str
    source: str
    published_ago: str
    sentiment: str    # "BULLISH" | "BEARISH" | "NEUTRAL"


# ─── Providers ────────────────────────────────────────────────────────────────

async def _fetch_yahoo_news(query: str, limit: int) -> list[NewsItem]:
    """
    Yahoo Finance news search — free, no API key required.
    Works for both crypto (query='bitcoin') and equities (query='AAPL').
    """
    try:
        async with httpx.AsyncClient(
            timeout=10.0, headers={"User-Agent": "Mozilla/5.0"}
        ) as client:
            resp = await client.get(
                "https://query1.finance.yahoo.com/v1/finance/search",
                params={"q": query, "quotesCount": 0, "newsCount": limit, "lang": "en-US"},
            )
            if resp.status_code == 429:
                logger.warning("Yahoo Finance news rate-limited for %s", query)
                return []
            resp.raise_for_status()
            items = resp.json().get("news", [])
    except Exception as exc:
        logger.warning("Yahoo Finance news failed for %s: %s", query, exc)
        return []

    result = []
    for item in items[:limit]:
        ts = item.get("providerPublishTime", 0)
        result.append(NewsItem(
            title=item.get("title", ""),
            source=item.get("publisher", "Unknown"),
            published_ago=_time_ago(ts) if ts else "recently",
            sentiment=_keyword_sentiment(item.get("title", "")),
        ))
    return result


async def _fetch_alphavantage(symbol: str, limit: int) -> list[NewsItem]:
    """
    Alpha Vantage NEWS_SENTIMENT — better sentiment scores when key is available.
    Used as a supplement for equities.
    """
    api_key = settings.alpha_vantage_api_key.get_secret_value()
    if not api_key or api_key.startswith("your-") or len(api_key) < 8:
        return []

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://www.alphavantage.co/query",
                params={
                    "function": "NEWS_SENTIMENT",
                    "tickers": symbol,
                    "apikey": api_key,
                    "limit": limit,
                    "sort": "LATEST",
                },
            )
            resp.raise_for_status()
            feed = resp.json().get("feed", [])
    except Exception as exc:
        logger.warning("Alpha Vantage news failed for %s: %s", symbol, exc)
        return []

    items = []
    for item in feed[:limit]:
        label = item.get("overall_sentiment_label", "Neutral").upper()
        if "BULL" in label or "POSITIVE" in label:
            sentiment = "BULLISH"
        elif "BEAR" in label or "NEGATIVE" in label:
            sentiment = "BEARISH"
        else:
            sentiment = _keyword_sentiment(item.get("title", ""))

        tp = item.get("time_published", "")
        try:
            dt = datetime.strptime(tp, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
            ago = _time_ago(dt.timestamp())
        except Exception:
            ago = "recently"

        items.append(NewsItem(
            title=item.get("title", ""),
            source=item.get("source", "Unknown"),
            published_ago=ago,
            sentiment=sentiment,
        ))
    return items


# ─── Formatter ────────────────────────────────────────────────────────────────

def _format_news(items: list[NewsItem], symbol: str) -> str:
    if not items:
        return ""

    bull = sum(1 for i in items if i.sentiment == "BULLISH")
    bear = sum(1 for i in items if i.sentiment == "BEARISH")
    neut = sum(1 for i in items if i.sentiment == "NEUTRAL")
    total = len(items)

    if bull > bear + 1:
        overall = "BULLISH"
    elif bear > bull + 1:
        overall = "BEARISH"
    else:
        overall = "MIXED / NEUTRAL"

    lines = [f"\n=== Recent News & Sentiment — {symbol} ==="]
    for item in items:
        lines.append(f"  [{item.sentiment}] \"{item.title}\" — {item.source}, {item.published_ago}")
    lines.append(
        f"  Overall news sentiment: {overall} "
        f"({bull} bullish · {neut} neutral · {bear} bearish of {total} articles)"
    )
    return "\n".join(lines)


# ─── Query mapping ────────────────────────────────────────────────────────────

_CRYPTO_QUERIES: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binance coin",
    "XRP": "ripple",
    "ADA": "cardano",
    "AVAX": "avalanche crypto",
    "DOT": "polkadot",
    "LINK": "chainlink",
    "DOGE": "dogecoin",
}


def _news_query(symbol: str, asset_class: str) -> str:
    """Map ticker symbol to a human-readable news search query."""
    if asset_class.upper() == "CRYPTO":
        return _CRYPTO_QUERIES.get(symbol.upper(), f"{symbol} cryptocurrency")
    return symbol  # Yahoo Finance handles equity tickers natively


# ─── Public interface ─────────────────────────────────────────────────────────

async def fetch_asset_news(symbol: str, asset_class: str, limit: int = 7) -> str:
    """
    Fetch recent news for an asset and return a formatted prompt context string.
    Results cached in Redis for 30 minutes.
    """
    cache_key = f"trading:news:{symbol}:{asset_class}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    query = _news_query(symbol, asset_class)

    # Yahoo Finance works for all asset classes — try first
    items = await _fetch_yahoo_news(query, limit)

    # For equities with Alpha Vantage key — use it for better sentiment scoring
    if not items and asset_class.upper() != "CRYPTO":
        items = await _fetch_alphavantage(symbol, limit)

    result = _format_news(items, symbol)
    # Cache even if empty (prevents hammering on failures)
    await cache_set(cache_key, result, ttl=1800)  # 30 minutes
    return result
