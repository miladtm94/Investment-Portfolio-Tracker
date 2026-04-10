"""
Trading router — Markets overview, Watchlist CRUD, and AI asset analysis.

Endpoints:
  GET  /trading/markets          — Live crypto + top equity prices
  GET  /trading/watchlist        — User's watchlist
  POST /trading/watchlist        — Add item
  DELETE /trading/watchlist/{symbol} — Remove item
  POST /trading/analyze          — AI analysis (provider + horizon selectable)
"""
from __future__ import annotations

import logging
from typing import Literal, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from shared.models import User, WatchlistItem, AnalysisResult
from shared.auth import get_current_user
from services.market_data_service import MarketDataService
from services.trading_analysis_service import run_trading_analysis
from services import news_service, macro_service
from shared.cache import cache_get, cache_set

logger = logging.getLogger(__name__)
router = APIRouter()

# ─── Schemas ──────────────────────────────────────────────────────────────────

class WatchlistAddRequest(BaseModel):
    symbol: str
    name: str
    asset_class: str          # EQUITY | CRYPTO | ETF
    exchange: Optional[str] = None
    coingecko_id: Optional[str] = None
    image_url: Optional[str] = None
    notes: Optional[str] = None


class AnalyzeRequest(BaseModel):
    symbol: str
    name: str
    asset_class: str          # EQUITY | CRYPTO | ETF
    price: Optional[float] = None
    exchange: Optional[str] = None
    sector: Optional[str] = None
    coingecko_id: Optional[str] = None
    horizon: Literal["trading", "investing"] = "trading"
    provider: Literal["claude", "openai", "gemini", "ollama", "lmstudio"] = "gemini"
    extra_context: Optional[str] = None
    as_of_date: Optional[str] = None  # ISO date "YYYY-MM-DD" — analyze up to this date


# ─── Markets ──────────────────────────────────────────────────────────────────

CRYPTO_IDS = (
    "bitcoin,ethereum,solana,binancecoin,ripple,cardano,"
    "avalanche-2,polkadot,chainlink,dogecoin,uniswap,aave"
)

TOP_EQUITIES = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "JPM", "V", "BRK-B"]

# Logo URLs (Financial Modeling Prep CDN — no API key required)
# shares_out: approximate shares outstanding (billions) used to compute live market cap
_FMP_LOGO = "https://financialmodelingprep.com/image-stock/{}.png"
EQUITY_META: dict[str, dict] = {
    "AAPL":  {"image": _FMP_LOGO.format("AAPL"),  "shares_out": 15.11e9},
    "MSFT":  {"image": _FMP_LOGO.format("MSFT"),  "shares_out": 7.44e9},
    "NVDA":  {"image": _FMP_LOGO.format("NVDA"),  "shares_out": 24.3e9},
    "TSLA":  {"image": _FMP_LOGO.format("TSLA"),  "shares_out": 3.20e9},
    "AMZN":  {"image": _FMP_LOGO.format("AMZN"),  "shares_out": 10.6e9},
    "GOOGL": {"image": _FMP_LOGO.format("GOOGL"), "shares_out": 12.3e9},
    "META":  {"image": _FMP_LOGO.format("META"),  "shares_out": 2.57e9},
    "JPM":   {"image": _FMP_LOGO.format("JPM"),   "shares_out": 2.82e9},
    "V":     {"image": _FMP_LOGO.format("V"),     "shares_out": 2.02e9},
    "BRK-B": {"image": _FMP_LOGO.format("BRK-B"), "shares_out": 1.35e9},
}


@router.get("/markets")
async def get_markets(
    current_user: User = Depends(get_current_user),
):
    """Return live data for top crypto coins and equities."""
    crypto_task = _fetch_coingecko_markets()
    equity_task = _fetch_equity_markets(TOP_EQUITIES)

    import asyncio
    crypto, equities = await asyncio.gather(crypto_task, equity_task, return_exceptions=True)

    return {
        "crypto": crypto if not isinstance(crypto, Exception) else [],
        "equities": equities if not isinstance(equities, Exception) else [],
    }


async def _fetch_coingecko_markets() -> list[dict]:
    _CACHE_KEY = "trading:markets:crypto"
    _STALE_KEY = "trading:markets:crypto:stale"

    # Try fresh cache first (5-minute TTL)
    cached = await cache_get(_CACHE_KEY)
    if cached is not None:
        return cached

    url = (
        "https://api.coingecko.com/api/v3/coins/markets"
        f"?vs_currency=usd&ids={CRYPTO_IDS}"
        "&order=market_cap_desc&sparkline=true&price_change_percentage=24h,7d"
    )
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, headers={"Accept": "application/json"})
        if resp.status_code == 429:
            logger.warning("CoinGecko rate-limited (429) — serving stale cache")
            stale = await cache_get(_STALE_KEY)
            return stale if stale is not None else []
        resp.raise_for_status()
        raw = resp.json()

    result = [
        {
            "symbol": c["symbol"].upper(),
            "name": c["name"],
            "asset_class": "CRYPTO",
            "coingecko_id": c["id"],
            "image": c.get("image"),
            "price": c.get("current_price"),
            "market_cap": c.get("market_cap"),
            "volume_24h": c.get("total_volume"),
            "change_24h": c.get("price_change_percentage_24h"),
            "change_7d": c.get("price_change_percentage_7d_in_currency"),
            "sparkline": c.get("sparkline_in_7d", {}).get("price", []),
            "rank": c.get("market_cap_rank"),
        }
        for c in raw
    ]
    # Cache: 5-min fresh TTL + 1-hour stale-serve-on-429
    await cache_set(_CACHE_KEY, result, ttl=300)
    await cache_set(_STALE_KEY, result, ttl=3600)
    return result


async def _fetch_equity_markets(symbols: list[str]) -> list[dict]:
    """Fetch rich quote data (price, change %, market cap, volume, sparkline) for all symbols."""
    import asyncio
    async with httpx.AsyncClient(timeout=15.0, headers={"User-Agent": "Mozilla/5.0"}) as client:
        tasks = [_yahoo_rich_quote(client, sym) for sym in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in results if r and not isinstance(r, Exception)]


async def _yahoo_rich_quote(client: httpx.AsyncClient, symbol: str) -> dict | None:
    """
    Single Yahoo Finance v8/chart call (1mo daily) returning:
      price, 24h change %, 7d change %, market cap (price × shares), volume, sparkline.
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    try:
        resp = await client.get(url, params={"interval": "1d", "range": "1mo"})
        resp.raise_for_status()
        data = resp.json()
        result = data["chart"]["result"][0]
    except Exception as e:
        logger.warning("Yahoo rich quote failed for %s: %s", symbol, e)
        return None

    meta   = result.get("meta", {})
    quotes = result.get("indicators", {}).get("quote", [{}])[0]
    closes = [c for c in quotes.get("close", []) if c is not None]

    price = meta.get("regularMarketPrice") or (closes[-1] if closes else None)
    if not price:
        return None

    # 24h change — derived from chartPreviousClose (always present)
    prev_close = meta.get("chartPreviousClose") or (closes[-2] if len(closes) >= 2 else None)
    change_24h = ((price / prev_close) - 1) * 100 if prev_close else None

    # 7d change — compare 7 trading days back
    change_7d = None
    if len(closes) >= 8 and closes[-8]:
        change_7d = (closes[-1] / closes[-8] - 1) * 100

    # Market cap — live price × stored shares outstanding
    shares = EQUITY_META.get(symbol, {}).get("shares_out")
    market_cap = price * shares if shares else None

    volume_24h = meta.get("regularMarketVolume")
    sparkline  = closes[-7:] if len(closes) >= 7 else closes

    # Prefer Yahoo's longName; fall back to symbol
    name = meta.get("longName") or meta.get("shortName") or symbol

    return {
        "symbol":      symbol,
        "name":        name,
        "image":       EQUITY_META.get(symbol, {}).get("image"),
        "asset_class": "EQUITY",
        "exchange":    meta.get("fullExchangeName", "NASDAQ"),
        "price":       price,
        "change_24h":  change_24h,
        "change_7d":   change_7d,
        "market_cap":  market_cap,
        "volume_24h":  volume_24h,
        "sparkline":   sparkline,
    }


# ─── Search ───────────────────────────────────────────────────────────────────

@router.get("/search")
async def search_assets(
    q: str = Query(..., min_length=1, max_length=50),
    current_user: User = Depends(get_current_user),
):
    """
    Search for assets by name or ticker symbol.
    Returns combined results from CoinGecko (crypto) and Yahoo Finance (equities/ETFs).
    """
    import asyncio
    q = q.strip()
    crypto_task = _search_crypto(q)
    equity_task = _search_equity(q)
    crypto, equity = await asyncio.gather(crypto_task, equity_task, return_exceptions=True)
    return {
        "crypto":   crypto   if not isinstance(crypto, Exception)  else [],
        "equities": equity   if not isinstance(equity, Exception)  else [],
    }


async def _search_crypto(q: str) -> list[dict]:
    cache_key = f"trading:search:crypto:{q.lower()}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        async with httpx.AsyncClient(timeout=10.0, headers={"Accept": "application/json"}) as client:
            resp = await client.get(
                "https://api.coingecko.com/api/v3/search",
                params={"query": q},
            )
            if resp.status_code == 429:
                return []
            resp.raise_for_status()
            coins = resp.json().get("coins", [])
    except Exception as exc:
        logger.warning("CoinGecko search failed for %r: %s", q, exc)
        return []

    result = [
        {
            "symbol":       c["symbol"].upper(),
            "name":         c["name"],
            "asset_class":  "CRYPTO",
            "coingecko_id": c["id"],
            "image":        c.get("large") or c.get("thumb"),
            "rank":         c.get("market_cap_rank"),
        }
        for c in coins[:10]
    ]
    await cache_set(cache_key, result, ttl=300)
    return result


async def _search_equity(q: str) -> list[dict]:
    cache_key = f"trading:search:equity:{q.lower()}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        async with httpx.AsyncClient(
            timeout=10.0, headers={"User-Agent": "Mozilla/5.0"}
        ) as client:
            resp = await client.get(
                "https://query1.finance.yahoo.com/v1/finance/search",
                params={"q": q, "quotesCount": 10, "newsCount": 0, "lang": "en-US"},
            )
            resp.raise_for_status()
            quotes = resp.json().get("quotes", [])
    except Exception as exc:
        logger.warning("Yahoo search failed for %r: %s", q, exc)
        return []

    result = []
    for item in quotes:
        qtype = item.get("quoteType", "")
        if qtype not in ("EQUITY", "ETF", "MUTUALFUND"):
            continue
        sym = item.get("symbol", "")
        if not sym:
            continue
        asset_class = "ETF" if qtype == "ETF" else "EQUITY"
        result.append({
            "symbol":      sym,
            "name":        item.get("longname") or item.get("shortname") or sym,
            "asset_class": asset_class,
            "exchange":    item.get("exchange", ""),
            "image":       _FMP_LOGO.format(sym),
        })

    await cache_set(cache_key, result, ttl=300)
    return result[:10]


# ─── Ollama status ────────────────────────────────────────────────────────────

@router.get("/ollama/status")
async def ollama_status(current_user: User = Depends(get_current_user)):
    """Check if local Ollama is available and return installed models."""
    from services.agents._base import get_ollama_status
    return await get_ollama_status()


@router.get("/lmstudio/status")
async def lmstudio_status(current_user: User = Depends(get_current_user)):
    """Check if LM Studio local server is running and return loaded models."""
    from services.agents._base import get_lmstudio_status
    return await get_lmstudio_status()


# ─── Watchlist ────────────────────────────────────────────────────────────────

@router.get("/watchlist")
async def get_watchlist(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(WatchlistItem)
        .where(WatchlistItem.user_id == current_user.id)
        .order_by(WatchlistItem.added_at.desc())
    )
    items = result.scalars().all()

    # Enrich with live prices
    symbols = [i.symbol for i in items]
    prices: dict[str, float] = {}
    if symbols:
        try:
            svc = MarketDataService()
            prices = await svc.get_batch_prices(symbols)
            await svc.close()
        except Exception:
            pass

    return [
        {
            "id": item.id,
            "symbol": item.symbol,
            "name": item.name,
            "asset_class": item.asset_class,
            "exchange": item.exchange,
            "coingecko_id": item.coingecko_id,
            "image_url": item.image_url,
            "notes": item.notes,
            "added_at": item.added_at.isoformat(),
            "price": prices.get(item.symbol),
        }
        for item in items
    ]


@router.post("/watchlist", status_code=201)
async def add_to_watchlist(
    req: WatchlistAddRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Check duplicate
    existing = await db.execute(
        select(WatchlistItem).where(
            WatchlistItem.user_id == current_user.id,
            WatchlistItem.symbol == req.symbol.upper(),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"{req.symbol.upper()} already in watchlist")

    item = WatchlistItem(
        user_id=current_user.id,
        symbol=req.symbol.upper(),
        name=req.name,
        asset_class=req.asset_class,
        exchange=req.exchange,
        coingecko_id=req.coingecko_id,
        image_url=req.image_url,
        notes=req.notes,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return {"id": item.id, "symbol": item.symbol, "added_at": item.added_at.isoformat()}


@router.delete("/watchlist/{symbol}", status_code=204)
async def remove_from_watchlist(
    symbol: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        delete(WatchlistItem).where(
            WatchlistItem.user_id == current_user.id,
            WatchlistItem.symbol == symbol.upper(),
        )
    )
    await db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail=f"{symbol.upper()} not in watchlist")


# ─── AI Analysis ──────────────────────────────────────────────────────────────

@router.post("/analyze")
async def analyze_asset(
    req: AnalyzeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Run AI analysis on an asset.

    - provider: "claude" | "openai" | "gemini" | "ollama"
    - horizon:  "trading" (short/medium) | "investing" (medium/long)
    """
    import asyncio
    from datetime import datetime, timezone

    sym = req.symbol.upper()

    # Parse as_of_date — if provided, analysis uses historical data up to that date
    as_of_dt: Optional[datetime] = None
    if req.as_of_date:
        try:
            as_of_dt = datetime.strptime(req.as_of_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            # Don't allow future dates
            if as_of_dt > datetime.now(timezone.utc):
                as_of_dt = None
        except ValueError:
            pass

    price = req.price

    async def _fetch_price():
        try:
            svc = MarketDataService()
            if as_of_dt:
                # Get price at or near the historical date from OHLCV
                p = await svc.get_price_at_date(sym, as_of_dt)
            else:
                p = await svc.get_price(sym)
            await svc.close()
            return p
        except Exception:
            return None

    # Fetch price + all AI context in parallel
    price_res, tech_ctx, news_ctx, macro_ctx = await asyncio.gather(
        _fetch_price(),
        _fetch_technical_context(sym, as_of=as_of_dt),
        news_service.fetch_asset_news(sym, req.asset_class),
        macro_service.fetch_macro_context(req.asset_class),
        return_exceptions=True,
    )

    if price is None and not isinstance(price_res, Exception):
        price = price_res
    if isinstance(tech_ctx, Exception):
        logger.warning("Technical context failed for %s: %s", sym, tech_ctx)
        tech_ctx = ""
    if isinstance(news_ctx, Exception):
        logger.warning("News context failed for %s: %s", sym, news_ctx)
        news_ctx = ""
    if isinstance(macro_ctx, Exception):
        logger.warning("Macro context failed: %s", macro_ctx)
        macro_ctx = ""

    # Build extra context string
    extra_parts: list[str] = []
    if as_of_dt:
        extra_parts.append(f"ANALYSIS DATE: {as_of_dt.strftime('%Y-%m-%d')} (historical — use data up to this date only)")
    if req.sector:
        extra_parts.append(f"Sector: {req.sector}")
    if req.exchange:
        extra_parts.append(f"Exchange: {req.exchange}")
    if req.extra_context:
        extra_parts.append(req.extra_context)
    if tech_ctx:
        extra_parts.append(tech_ctx)
    if news_ctx:
        extra_parts.append(news_ctx)
    if macro_ctx:
        extra_parts.append(macro_ctx)
    extra = "\n".join(extra_parts)

    try:
        result = await run_trading_analysis(
            symbol=sym,
            name=req.name,
            price=price,
            asset_type=req.asset_class,
            horizon=req.horizon,
            provider=req.provider,
            extra=extra,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    result["_as_of_date"] = req.as_of_date
    result["_entry_price"] = price

    # ── Persist analysis result for feedback loop (Phase 5) ────────────────
    try:
        from decimal import Decimal
        record = AnalysisResult(
            user_id=current_user.id,
            symbol=sym,
            name=req.name,
            asset_class=req.asset_class,
            provider=req.provider,
            horizon=req.horizon,
            rec=result.get("rec", "HOLD"),
            score=result.get("score"),
            confidence=result.get("confidence"),
            target=Decimal(str(result["target"])) if result.get("target") else None,
            stop_loss=Decimal(str(result["stopLoss"])) if result.get("stopLoss") else None,
            entry_price=Decimal(str(price)) if price else None,
            agent_scores=result.get("_agent_scores"),
            payload={k: v for k, v in result.items() if not k.startswith("_")},
        )
        db.add(record)
        await db.commit()
        result["_analysis_id"] = record.id
    except Exception as exc:
        logger.warning("Failed to persist analysis result: %s", exc)

    return result


async def _fetch_technical_context(symbol: str, as_of: Optional[datetime] = None) -> str:
    """
    Fetch 90 days of OHLCV data and compute a full technical indicator suite.
    If as_of is provided, uses historical data ending at that date (for backtesting).
    """
    from datetime import datetime, timezone, timedelta
    from services.technical_engine import TechnicalAnalysisEngine

    end = as_of if as_of else datetime.now(timezone.utc)
    start = end - timedelta(days=110)  # buffer for EMA50/SMA200 warmup

    try:
        svc = MarketDataService()
        data = await svc.get_historical_prices(symbol, start, end)
        await svc.close()
    except Exception as exc:
        logger.warning("OHLCV fetch failed for %s: %s", symbol, exc)
        return ""

    if not data or len(data) < 5:
        return ""

    try:
        engine = TechnicalAnalysisEngine(data)
        return engine.build_prompt_context()
    except Exception as exc:
        logger.warning("TechnicalAnalysisEngine failed for %s: %s", symbol, exc)
        return ""
