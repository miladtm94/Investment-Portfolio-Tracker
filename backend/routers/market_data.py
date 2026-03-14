"""Market data router — prices, historical data, assets."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from shared.models import Asset, User
from shared.auth import get_current_user
from services.market_data_service import MarketDataService

router = APIRouter()


class PriceResponse(BaseModel):
    symbol: str
    price: Optional[float]
    currency: str = "USD"


@router.get("/prices")
async def get_prices(
    symbols: list[str] = Query(..., description="List of ticker symbols"),
    current_user: User = Depends(get_current_user),
):
    """Get current prices for multiple symbols."""
    svc = MarketDataService()
    prices = await svc.get_batch_prices(symbols)
    await svc.close()
    return {"prices": prices}


@router.get("/prices/{symbol}")
async def get_price(
    symbol: str,
    current_user: User = Depends(get_current_user),
):
    """Get current price for a single symbol."""
    svc = MarketDataService()
    price = await svc.get_price(symbol.upper())
    await svc.close()
    return {"symbol": symbol.upper(), "price": price, "currency": "USD"}


@router.get("/prices/{symbol}/history")
async def get_price_history(
    symbol: str,
    start: datetime = Query(..., description="Start date"),
    end: Optional[datetime] = Query(None, description="End date (default: today)"),
    current_user: User = Depends(get_current_user),
):
    """Get historical daily OHLCV prices."""
    if end is None:
        from datetime import timezone
        end = datetime.now(timezone.utc)

    svc = MarketDataService()
    history = await svc.get_historical_prices(symbol.upper(), start, end)
    await svc.close()

    return {"symbol": symbol.upper(), "data": history}


@router.get("/assets/search")
async def search_assets(
    q: str = Query(..., min_length=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Search for assets by symbol or name."""
    result = await db.execute(
        select(Asset).where(
            Asset.is_active == True,
        ).filter(
            (Asset.symbol.ilike(f"%{q}%")) | (Asset.name.ilike(f"%{q}%"))
        ).limit(20)
    )
    assets = result.scalars().all()
    return [
        {
            "id": a.id,
            "symbol": a.symbol,
            "name": a.name,
            "asset_class": a.asset_class,
            "exchange": a.exchange,
        }
        for a in assets
    ]
