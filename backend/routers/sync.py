"""Sync router — broker and exchange account synchronization."""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from shared.models import Account, ApiCredential, User
from shared.auth import get_current_user
from shared.cache import cache_delete_pattern, cache_invalidate_user
from services.sync_service import SyncService
from services.dividend_service import DividendService

logger = logging.getLogger(__name__)

router = APIRouter()


class ConnectExchangeRequest(BaseModel):
    account_id: str
    provider: str  # KRAKEN|COINBASE|BINANCE
    api_key: str
    api_secret: str


class ConnectBrokerRequest(BaseModel):
    account_id: str
    provider: str  # PLAID|SNAPTRADE|IBKR
    access_token: str
    query_id: Optional[str] = None


class SyncResponse(BaseModel):
    imported: int
    provider: str
    account_id: str
    error: Optional[str] = None


@router.post("/connect/exchange", response_model=dict, status_code=201)
async def connect_exchange(
    body: ConnectExchangeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Store encrypted API credentials for a crypto exchange."""
    # Validate account ownership
    result = await db.execute(
        select(Account).where(Account.id == body.account_id, Account.user_id == current_user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Account not found")

    # Upsert: update existing credentials or create new ones
    existing = await db.execute(
        select(ApiCredential).where(
            ApiCredential.user_id == current_user.id,
            ApiCredential.provider == body.provider.upper(),
            ApiCredential.credential_type == "API_KEY",
        )
    )
    cred = existing.scalar_one_or_none()

    if cred:
        cred.account_id = body.account_id
        cred.encrypted_api_key = body.api_key.encode()
        cred.encrypted_api_secret = body.api_secret.encode()
        cred.is_active = True
    else:
        cred = ApiCredential(
            user_id=current_user.id,
            account_id=body.account_id,
            provider=body.provider.upper(),
            credential_type="API_KEY",
            encrypted_api_key=body.api_key.encode(),
            encrypted_api_secret=body.api_secret.encode(),
            encryption_key_id="default",
        )
        db.add(cred)

    await db.commit()

    return {"message": "Credentials stored. Initiating sync.", "account_id": body.account_id}


@router.post("/connect/broker", response_model=dict, status_code=201)
async def connect_broker(
    body: ConnectBrokerRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Store broker API credentials such as IBKR Flex Web Service tokens."""
    result = await db.execute(
        select(Account).where(Account.id == body.account_id, Account.user_id == current_user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Account not found")

    provider = body.provider.upper()
    credential_type = "FLEX_QUERY" if provider in {"IBKR", "INTERACTIVE_BROKERS"} else "ACCESS_TOKEN"
    if credential_type == "FLEX_QUERY" and not body.query_id:
        raise HTTPException(status_code=422, detail="IBKR Flex Query ID is required")

    existing = await db.execute(
        select(ApiCredential).where(
            ApiCredential.user_id == current_user.id,
            ApiCredential.provider == provider,
            ApiCredential.credential_type == credential_type,
        )
    )
    cred = existing.scalar_one_or_none()

    if cred:
        cred.account_id = body.account_id
        cred.encrypted_access_token = body.access_token.encode()
        cred.encrypted_api_key = (body.query_id or "").encode()
        cred.is_active = True
    else:
        cred = ApiCredential(
            user_id=current_user.id,
            account_id=body.account_id,
            provider=provider,
            credential_type=credential_type,
            encrypted_access_token=body.access_token.encode(),
            encrypted_api_key=(body.query_id or "").encode(),
            encryption_key_id="default",
        )
        db.add(cred)

    await db.commit()

    return {"message": "Broker credentials stored. Initiating sync.", "account_id": body.account_id}


@router.post("/accounts/{account_id}/trigger", response_model=SyncResponse)
async def trigger_sync(
    account_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger a sync for an account."""
    svc = SyncService(db)
    result = await svc.sync_account(account_id, current_user.id)
    await svc.close()

    return SyncResponse(
        imported=result.get("imported", 0),
        provider=result.get("provider", "unknown"),
        account_id=account_id,
        error=result.get("error"),
    )


@router.get("/accounts/{account_id}/status")
async def get_sync_status(
    account_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Account).where(Account.id == account_id, Account.user_id == current_user.id)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    return {
        "account_id": account_id,
        "sync_status": account.sync_status,
        "last_synced_at": account.last_synced_at.isoformat() if account.last_synced_at else None,
    }


@router.post("/refresh-all")
async def refresh_all(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Full dashboard refresh:
    1. Flush cached FX rates and market prices
    2. Sync all API-connected accounts (Kraken, etc.)
    3. Invalidate portfolio/analytics caches
    """
    steps: list[dict] = []

    # 1. Flush only spot price caches (short-lived anyway, 60s TTL)
    #    Keep historical price and FX caches intact to avoid rate-limit issues
    spot_cleared = await cache_delete_pattern("market:price:*:spot")
    # Flush today's FX rates (1h TTL) so they refresh, keep historical rates
    from datetime import datetime, timezone
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fx_cleared = await cache_delete_pattern(f"fx:*:{today_str}")
    steps.append({"step": "cache_flush", "spot_keys": spot_cleared, "fx_keys": fx_cleared})

    # 2. Find all API-connected accounts and sync them
    cred_result = await db.execute(
        select(ApiCredential).where(
            ApiCredential.user_id == current_user.id,
            ApiCredential.is_active == True,
            ApiCredential.account_id.isnot(None),
        )
    )
    credentials = cred_result.scalars().all()

    sync_results: list[dict] = []
    for cred in credentials:
        if not cred.account_id:
            continue
        try:
            svc = SyncService(db)
            result = await svc.sync_account(cred.account_id, current_user.id)
            await svc.close()
            sync_results.append({
                "account_id": cred.account_id,
                "provider": cred.provider,
                "imported": result.get("imported", 0),
                "error": result.get("error"),
            })
        except Exception as e:
            logger.warning(f"Sync failed for {cred.provider} account {cred.account_id}: {e}")
            sync_results.append({
                "account_id": cred.account_id,
                "provider": cred.provider,
                "imported": 0,
                "error": str(e),
            })
    steps.append({"step": "sync_accounts", "results": sync_results})

    # 3. Fetch US equity dividends via Polygon
    dividend_svc = DividendService(db)
    try:
        dividend_result = await dividend_svc.sync_us_dividends(current_user)
    finally:
        await dividend_svc.close()
    steps.append({"step": "dividends", "result": dividend_result})

    # 4. Invalidate portfolio/analytics caches so fresh prices are used
    await cache_invalidate_user(current_user.id)
    steps.append({"step": "cache_invalidate"})

    dividend_inserted = dividend_result.get("inserted", 0) if isinstance(dividend_result, dict) else 0
    total_imported = sum(r["imported"] for r in sync_results) + dividend_inserted
    errors = [r for r in sync_results if r.get("error")]
    if isinstance(dividend_result, dict) and dividend_result.get("errors"):
        errors.extend(dividend_result.get("errors"))

    return {
        "status": "completed",
        "accounts_synced": len(sync_results),
        "total_imported": total_imported,
        "errors": errors,
        "steps": steps,
    }
