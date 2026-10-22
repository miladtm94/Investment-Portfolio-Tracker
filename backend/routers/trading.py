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
from datetime import datetime, timezone
from typing import Literal, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, delete, desc
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from shared.models import User, WatchlistItem, AnalysisResult, SignalCheck
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


class SignalRequest(BaseModel):
    symbol: str
    name: Optional[str] = None
    asset_class: str          # EQUITY | CRYPTO | ETF
    interval: Literal["15", "60", "240", "D", "W"] = "D"
    exchange: Optional[str] = None
    currency: str = "USD"
    as_of_date: Optional[str] = None
    evaluation_days: int = Field(default=7, ge=1, le=90)


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

    async def _fetch_user_position() -> str:
        """Fetch the user's current position in this symbol from their portfolio."""
        try:
            from services.portfolio_engine import PortfolioEngine
            from services.market_data_service import MarketDataService as MDS
            mds = MDS()
            engine = PortfolioEngine(db, mds)
            summary = await engine.get_portfolio_summary(
                user_id=current_user.id,
                account_ids=None,
                cost_basis_method=getattr(current_user, "cost_basis_method", "FIFO"),
            )
            await mds.close()
            # Find matching holding — strip .AX suffix for ASX stocks
            sym_clean = sym.replace(".AX", "")
            holding = next(
                (h for h in summary.holdings if h.symbol.upper().replace(".AX", "") == sym_clean),
                None
            )
            if not holding:
                return ""
            qty   = float(holding.quantity)
            avg   = float(holding.average_cost_basis or 0)
            mv    = float(holding.market_value or 0)
            pnl   = float(holding.unrealized_gain or 0)
            pnl_p = float(holding.unrealized_gain_pct or 0)
            weight = (mv / float(summary.total_market_value) * 100) if summary.total_market_value else 0
            lines = [
                f"=== User's Current Position in {sym} ===",
                f"Shares held: {qty:,.4f}",
                f"Average cost basis: ${avg:,.4f}",
                f"Current market value: ${mv:,.2f}",
                f"Unrealised P&L: ${pnl:+,.2f} ({pnl_p:+.2f}%)",
                f"Portfolio weight: {weight:.1f}%",
            ]
            if pnl_p < -10:
                lines.append("NOTE: This is a losing position — factor this into risk assessment and consider stop-loss proximity.")
            elif pnl_p > 50:
                lines.append("NOTE: This position has significant unrealised gains — factor in potential profit-taking and CGT implications.")
            return "\n".join(lines)
        except Exception as exc:
            logger.debug("Could not fetch user position for %s: %s", sym, exc)
            return ""

    # Fetch price + all AI context in parallel
    price_res, tech_ctx, news_ctx, macro_ctx, position_ctx = await asyncio.gather(
        _fetch_price(),
        _fetch_technical_context(sym, as_of=as_of_dt),
        news_service.fetch_asset_news(sym, req.asset_class),
        macro_service.fetch_macro_context(req.asset_class),
        _fetch_user_position(),
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
    if isinstance(position_ctx, Exception):
        position_ctx = ""

    # Build extra context string
    extra_parts: list[str] = []
    if as_of_dt:
        extra_parts.append(f"ANALYSIS DATE: {as_of_dt.strftime('%Y-%m-%d')} (historical — use data up to this date only)")
    if position_ctx:
        extra_parts.append(position_ctx)
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


@router.post("/signal")
async def generate_signal(
    req: SignalRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a deterministic technical signal for the selected chart timeframe.

    This endpoint does not call any LLM provider and is separate from /analyze.
    """
    from datetime import datetime, timezone, timedelta
    from services.signal_engine import SignalEngine

    sym = req.symbol.upper()
    end = datetime.now(timezone.utc)
    if req.as_of_date:
        try:
            end = datetime.strptime(req.as_of_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            end = end + timedelta(days=1)
            if end > datetime.now(timezone.utc):
                end = datetime.now(timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail="as_of_date must be YYYY-MM-DD")

    start = end - _signal_lookback(req.interval)
    future_candles: list[dict] = []
    now = datetime.now(timezone.utc)
    eval_start = end
    due_at = end + timedelta(days=req.evaluation_days)
    can_evaluate = due_at <= now
    eval_end = due_at if can_evaluate else now

    svc = MarketDataService()
    try:
        candles = await svc.get_chart_ohlcv(
            symbol=sym,
            interval=req.interval,
            start_date=start,
            end_date=end,
            asset_class=req.asset_class,
            currency=req.currency,
            exchange=req.exchange,
        )
        if req.as_of_date and can_evaluate:
            future_candles = await svc.get_chart_ohlcv(
                symbol=sym,
                interval=req.interval,
                start_date=eval_start,
                end_date=eval_end,
                asset_class=req.asset_class,
                currency=req.currency,
                exchange=req.exchange,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.warning("Signal OHLCV fetch failed for %s: %s", sym, exc)
        raise HTTPException(status_code=502, detail="Could not fetch chart candles for signal analysis")
    finally:
        await svc.close()

    if not candles or len(candles) < 30:
        raise HTTPException(
            status_code=422,
            detail=f"Not enough candles for {sym} on {req.interval} timeframe. Need at least 30.",
        )

    try:
        result = SignalEngine(candles, req.interval).analyze()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("Signal engine failed for %s", sym)
        raise HTTPException(status_code=500, detail="Signal engine failed")

    result["symbol"] = sym
    result["name"] = req.name or sym
    result["assetClass"] = req.asset_class
    result["_as_of_date"] = req.as_of_date
    result["requestedEvaluationDays"] = req.evaluation_days
    result["dueAt"] = due_at.isoformat()
    result["status"] = "EVALUATED" if req.as_of_date and can_evaluate else "PENDING"
    result["backtest"] = _evaluate_signal_outcome(result, future_candles, eval_start, eval_end) if req.as_of_date and can_evaluate else None

    try:
        record = await _persist_signal_check(
            db=db,
            user_id=current_user.id,
            req=req,
            result=result,
            signal_at=end,
            due_at=due_at,
        )
        result["_signal_id"] = record.id
    except Exception as exc:
        logger.warning("Failed to persist signal check: %s", exc)
    return result


def _signal_lookback(interval: str):
    from datetime import timedelta

    return {
        "15": timedelta(days=30),
        "60": timedelta(days=90),
        "240": timedelta(days=180),
        "D": timedelta(days=420),
        "W": timedelta(days=365 * 4),
    }[interval]


@router.get("/signal-checks")
async def get_signal_checks(
    status: Optional[Literal["PENDING", "EVALUATED"]] = Query(None),
    symbol: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List saved deterministic signal checks for the current user."""
    q = select(SignalCheck).where(SignalCheck.user_id == current_user.id)
    if status:
        q = q.where(SignalCheck.status == status)
    if symbol:
        q = q.where(SignalCheck.symbol == symbol.upper())
    q = q.order_by(desc(SignalCheck.created_at)).limit(limit)
    rows = (await db.execute(q)).scalars().all()
    return {"items": [_signal_check_to_dict(row) for row in rows]}


@router.post("/signal-checks/check-due")
async def check_due_signal_checks(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Evaluate all due pending signal checks for the current user."""
    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(SignalCheck)
            .where(SignalCheck.user_id == current_user.id)
            .where(SignalCheck.status == "PENDING")
            .where(SignalCheck.due_at <= now)
            .order_by(SignalCheck.due_at)
            .limit(50)
        )
    ).scalars().all()

    checked = []
    for row in rows:
        checked.append(await _check_signal_record(row, db))
    return {"checked": len(checked), "items": checked}


@router.post("/signal-checks/{signal_id}/check")
async def check_signal_check(
    signal_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Evaluate one due signal check."""
    row = await db.get(SignalCheck, signal_id)
    if not row or row.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Signal check not found")
    return await _check_signal_record(row, db)


async def _persist_signal_check(
    db: AsyncSession,
    user_id: str,
    req: SignalRequest,
    result: dict,
    signal_at,
    due_at,
) -> SignalCheck:
    from decimal import Decimal

    plan = result.get("tradePlan", {})
    backtest = result.get("backtest")
    record = SignalCheck(
        user_id=user_id,
        symbol=req.symbol.upper(),
        name=req.name or req.symbol.upper(),
        asset_class=req.asset_class,
        exchange=req.exchange,
        currency=req.currency,
        interval=req.interval,
        signal=result.get("signal", "HOLD"),
        score=result.get("score"),
        confidence=result.get("confidence"),
        action=plan.get("action"),
        signal_at=signal_at,
        due_at=due_at,
        evaluation_days=req.evaluation_days,
        status="EVALUATED" if backtest else "PENDING",
        current_price=_decimal_or_none(result.get("currentPrice")),
        entry_price=_decimal_or_none(plan.get("entry")),
        entry_zone_low=_decimal_or_none(plan.get("entryZoneLow")),
        entry_zone_high=_decimal_or_none(plan.get("entryZoneHigh")),
        stop_loss=_decimal_or_none(plan.get("stopLoss")),
        take_profit_1=_decimal_or_none(plan.get("takeProfit1")),
        take_profit_2=_decimal_or_none(plan.get("takeProfit2")),
        take_profit_3=_decimal_or_none(plan.get("takeProfit3")),
        risk_reward=_decimal_or_none(plan.get("riskReward")),
        payload=result,
    )
    if backtest:
        record.outcome = backtest.get("outcome")
        record.outcome_payload = backtest
        record.outcome_correct = _is_successful_outcome(backtest)
        record.outcome_return_pct = _decimal_or_none(backtest.get("returnPct"))
        record.checked_at = datetime.now(timezone.utc)

    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def _check_signal_record(row: SignalCheck, db: AsyncSession) -> dict:
    now = datetime.now(timezone.utc)
    if row.status == "EVALUATED":
        return _signal_check_to_dict(row)
    if row.due_at > now:
        item = _signal_check_to_dict(row)
        item["checkMessage"] = f"Not due until {row.due_at.isoformat()}"
        return item

    svc = MarketDataService()
    try:
        future_candles = await svc.get_chart_ohlcv(
            symbol=row.symbol,
            interval=row.interval,
            start_date=row.signal_at,
            end_date=row.due_at,
            asset_class=row.asset_class,
            currency=row.currency,
            exchange=row.exchange,
        )
    finally:
        await svc.close()

    payload = row.payload or {}
    outcome = _evaluate_signal_outcome(payload, future_candles, row.signal_at, row.due_at)
    row.status = "EVALUATED"
    row.outcome = outcome.get("outcome")
    row.outcome_payload = outcome
    row.outcome_correct = _is_successful_outcome(outcome)
    row.outcome_return_pct = _decimal_or_none(outcome.get("returnPct"))
    row.checked_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return _signal_check_to_dict(row)


def _signal_check_to_dict(row: SignalCheck) -> dict:
    return {
        "id": row.id,
        "symbol": row.symbol,
        "name": row.name,
        "assetClass": row.asset_class,
        "exchange": row.exchange,
        "interval": row.interval,
        "signal": row.signal,
        "score": row.score,
        "confidence": row.confidence,
        "action": row.action,
        "status": row.status,
        "signalAt": row.signal_at.isoformat(),
        "dueAt": row.due_at.isoformat(),
        "evaluationDays": row.evaluation_days,
        "currentPrice": _float_or_none(row.current_price),
        "entryPrice": _float_or_none(row.entry_price),
        "stopLoss": _float_or_none(row.stop_loss),
        "takeProfit1": _float_or_none(row.take_profit_1),
        "takeProfit2": _float_or_none(row.take_profit_2),
        "takeProfit3": _float_or_none(row.take_profit_3),
        "riskReward": _float_or_none(row.risk_reward),
        "outcome": row.outcome,
        "outcomeCorrect": row.outcome_correct,
        "outcomeReturnPct": _float_or_none(row.outcome_return_pct),
        "outcomePayload": row.outcome_payload,
        "checkedAt": row.checked_at.isoformat() if row.checked_at else None,
        "createdAt": row.created_at.isoformat(),
    }


def _is_successful_outcome(outcome: dict | None) -> bool | None:
    if not outcome or not outcome.get("available"):
        return None
    value = outcome.get("outcome")
    if value == "ENTRY_NOT_TRIGGERED":
        return True
    if value and value.startswith("TAKE_PROFIT"):
        return True
    if value == "STOP_LOSS_HIT":
        return False
    return None


def _decimal_or_none(value):
    from decimal import Decimal

    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _float_or_none(value):
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _evaluate_signal_outcome(signal_result: dict, future_candles: list[dict], eval_start, eval_end) -> dict:
    """Evaluate whether the generated execution plan would have triggered and how it performed."""
    plan = signal_result.get("tradePlan", {})
    direction = "long" if signal_result.get("signal") in {"BUY", "STRONG BUY"} else "short" if signal_result.get("signal") in {"SELL", "STRONG SELL"} else "neutral"
    window = {
        "from": eval_start.isoformat(),
        "to": eval_end.isoformat(),
        "days": max((eval_end - eval_start).days, 0),
    }
    if not future_candles:
        return {
            "available": False,
            "evaluationWindow": window,
            "summary": "No future candles were available for this historical evaluation window.",
        }
    if direction == "neutral":
        final_price = _last_close(future_candles)
        start_price = signal_result.get("currentPrice")
        return {
            "available": True,
            "evaluationWindow": window,
            "entryTriggered": False,
            "outcome": "NO_TRADE_HOLD_SIGNAL",
            "finalPrice": final_price,
            "finalMovePct": _pct(final_price, start_price),
            "summary": "Signal was HOLD, so no entry was evaluated. Final move is shown for context.",
        }

    entry = float(plan["entry"])
    zone_low = float(plan["entryZoneLow"])
    zone_high = float(plan["entryZoneHigh"])
    stop = float(plan["stopLoss"])
    targets = [float(plan["takeProfit1"]), float(plan["takeProfit2"]), float(plan["takeProfit3"])]
    action = plan.get("action", "")

    triggered_at = None
    for idx, candle in enumerate(future_candles):
        high = float(candle.get("high") or candle.get("close"))
        low = float(candle.get("low") or candle.get("close"))
        if _entry_triggered(direction, action, high, low, entry, zone_low, zone_high):
            triggered_at = idx
            break

    final_price = _last_close(future_candles)
    if triggered_at is None:
        return {
            "available": True,
            "evaluationWindow": window,
            "entryTriggered": False,
            "outcome": "ENTRY_NOT_TRIGGERED",
            "finalPrice": final_price,
            "finalMovePct": _pct(final_price, signal_result.get("currentPrice")),
            "summary": "The setup did not trigger during the evaluation window, so no trade would have been opened.",
        }

    max_target_hit = 0
    exit_price = final_price
    exit_date = future_candles[-1].get("date")
    outcome = "OPEN_AT_WINDOW_END"

    for candle in future_candles[triggered_at:]:
        high = float(candle.get("high") or candle.get("close"))
        low = float(candle.get("low") or candle.get("close"))
        date = candle.get("date")
        if direction == "long":
            # Conservative candle sequencing: if stop and target are both inside one candle, stop wins.
            if low <= stop:
                outcome = "STOP_LOSS_HIT"
                exit_price = stop
                exit_date = date
                break
            for target_num, target in reversed(list(enumerate(targets, start=1))):
                if high >= target:
                    max_target_hit = max(max_target_hit, target_num)
                    outcome = f"TAKE_PROFIT_{target_num}_HIT"
                    exit_price = target
                    exit_date = date
                    break
            if outcome.startswith("TAKE_PROFIT"):
                break
        else:
            if high >= stop:
                outcome = "STOP_LOSS_HIT"
                exit_price = stop
                exit_date = date
                break
            for target_num, target in reversed(list(enumerate(targets, start=1))):
                if low <= target:
                    max_target_hit = max(max_target_hit, target_num)
                    outcome = f"TAKE_PROFIT_{target_num}_HIT"
                    exit_price = target
                    exit_date = date
                    break
            if outcome.startswith("TAKE_PROFIT"):
                break

    return_pct = _pct(exit_price, entry) if direction == "long" else _pct(entry, exit_price)
    return {
        "available": True,
        "evaluationWindow": window,
        "entryTriggered": True,
        "entryDate": future_candles[triggered_at].get("date"),
        "entryPrice": entry,
        "exitDate": exit_date,
        "exitPrice": exit_price,
        "outcome": outcome,
        "maxTargetHit": max_target_hit,
        "returnPct": return_pct,
        "finalPrice": final_price,
        "finalMovePct": _pct(final_price, signal_result.get("currentPrice")),
        "summary": f"Entry triggered, then outcome was {outcome.replace('_', ' ').lower()} over the evaluation window.",
    }


def _entry_triggered(direction: str, action: str, high: float, low: float, entry: float, zone_low: float, zone_high: float) -> bool:
    if action == "ENTER_NOW":
        return True
    if direction == "long":
        if action == "WAIT_FOR_BREAKOUT":
            return high >= entry
        return low <= zone_high and high >= zone_low
    if action == "WAIT_FOR_BREAKDOWN":
        return low <= entry
    return high >= zone_low and low <= zone_high


def _last_close(candles: list[dict]) -> float | None:
    try:
        return float(candles[-1].get("close"))
    except (TypeError, ValueError, IndexError):
        return None


def _pct(end: float | None, start: float | None) -> float | None:
    if not end or not start:
        return None
    return round((end / start - 1) * 100, 2)


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
