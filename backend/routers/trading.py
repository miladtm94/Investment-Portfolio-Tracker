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
from shared.models import User, WatchlistItem
from shared.auth import get_current_user
from services.market_data_service import MarketDataService
from services.trading_analysis_service import run_trading_analysis

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
    provider: Literal["claude", "openai", "gemini"] = "claude"
    extra_context: Optional[str] = None


# ─── Markets ──────────────────────────────────────────────────────────────────

CRYPTO_IDS = (
    "bitcoin,ethereum,solana,binancecoin,ripple,cardano,"
    "avalanche-2,polkadot,chainlink,dogecoin,uniswap,aave"
)

TOP_EQUITIES = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL", "META", "JPM", "V", "BRK-B"]


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
    url = (
        "https://api.coingecko.com/api/v3/coins/markets"
        f"?vs_currency=usd&ids={CRYPTO_IDS}"
        "&order=market_cap_desc&sparkline=true&price_change_percentage=24h,7d"
    )
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, headers={"Accept": "application/json"})
        resp.raise_for_status()
        raw = resp.json()

    return [
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


async def _fetch_equity_markets(symbols: list[str]) -> list[dict]:
    svc = MarketDataService()
    prices = await svc.get_batch_prices(symbols)
    await svc.close()
    return [
        {
            "symbol": sym,
            "name": sym,
            "asset_class": "EQUITY",
            "price": prices.get(sym),
            "exchange": "NASDAQ",
        }
        for sym in symbols
        if prices.get(sym)
    ]


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
):
    """
    Run AI analysis on an asset.

    - provider: "claude" | "openai" | "gemini"
    - horizon:  "trading" (short/medium) | "investing" (medium/long)
    """
    # If no price provided, try to fetch live price
    price = req.price
    if price is None:
        try:
            svc = MarketDataService()
            price = await svc.get_price(req.symbol.upper())
            await svc.close()
        except Exception:
            pass

    # Build extra context string
    extra_parts: list[str] = []
    if req.sector:
        extra_parts.append(f"Sector: {req.sector}")
    if req.exchange:
        extra_parts.append(f"Exchange: {req.exchange}")
    if req.extra_context:
        extra_parts.append(req.extra_context)
    extra = ". ".join(extra_parts)

    try:
        result = await run_trading_analysis(
            symbol=req.symbol.upper(),
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

    return result
