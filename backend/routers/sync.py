"""Sync router — broker and exchange account synchronization."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from shared.models import Account, ApiCredential, User
from shared.auth import get_current_user
from services.sync_service import SyncService

router = APIRouter()


class ConnectExchangeRequest(BaseModel):
    account_id: str
    provider: str  # KRAKEN|COINBASE|BINANCE
    api_key: str
    api_secret: str


class ConnectBrokerRequest(BaseModel):
    account_id: str
    provider: str  # PLAID|SNAPTRADE
    access_token: str


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

    # In production: encrypt with KMS before storing
    # Here we store as bytes for demonstration
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
