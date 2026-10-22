"""Transactions router — CRUD, import, history."""
import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional

logger = logging.getLogger(__name__)

API_TRANSACTION_SOURCES = {"KRAKEN_API", "COINBASE", "BINANCE", "IBKR_API", "PLAID"}

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc

from database import get_db
from shared.models import Account, ApiCredential, Asset, Transaction, User
from shared.assets import get_or_create_asset
from shared.auth import get_current_user
from shared.cache import cache_invalidate_user
from services.transaction_import import TransactionImporter
from services.fx_service import enrich_transaction_with_aud

router = APIRouter()


class TransactionCreate(BaseModel):
    account_id: str
    asset_symbol: Optional[str] = None
    transaction_type: str
    quantity: Optional[float] = None
    price_per_unit: Optional[float] = None
    fees: float = 0.0
    net_amount: Optional[float] = None
    currency: str = "USD"
    transacted_at: datetime
    notes: Optional[str] = None


class TransactionResponse(BaseModel):
    id: str
    account_id: str
    asset_id: Optional[str]
    symbol: Optional[str]
    transaction_type: str
    quantity: Optional[float]
    price_per_unit: Optional[float]
    fees: float
    gross_amount: Optional[float] = None
    tax_withheld: Optional[float] = None
    dividend_per_share: Optional[float] = None
    net_amount: Optional[float]
    currency: str
    fx_rate_to_aud: Optional[float] = None
    net_amount_aud: Optional[float] = None
    price_per_unit_aud: Optional[float] = None
    ex_date: Optional[datetime] = None
    franking_pct: Optional[float] = None
    franking_credit: Optional[float] = None
    transacted_at: datetime
    source: str
    notes: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class ImportResultResponse(BaseModel):
    total_rows: int
    imported: int
    duplicates: int
    errors: int
    error_details: list[str]
    transaction_ids: list[str]
    broker_detected: str = "Unknown"


@router.get("/", response_model=list[TransactionResponse])
async def list_transactions(
    account_id: Optional[str] = Query(None),
    asset_symbol: Optional[str] = Query(None),
    transaction_type: Optional[str] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    limit: int = Query(100, le=1000),
    offset: int = Query(0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(Transaction, Asset)
        .join(Asset, Transaction.asset_id == Asset.id, isouter=True)
        .where(Transaction.user_id == current_user.id)
        .order_by(desc(Transaction.transacted_at))
        .limit(limit)
        .offset(offset)
    )

    if account_id:
        query = query.where(Transaction.account_id == account_id)
    if transaction_type:
        query = query.where(Transaction.transaction_type == transaction_type.upper())
    if start_date:
        query = query.where(Transaction.transacted_at >= start_date)
    if end_date:
        query = query.where(Transaction.transacted_at <= end_date)
    if asset_symbol:
        query = query.where(Asset.symbol == asset_symbol.upper())

    result = await db.execute(query)
    rows = result.all()

    return [
        TransactionResponse(
            id=txn.id,
            account_id=txn.account_id,
            asset_id=txn.asset_id,
            symbol=asset.symbol if asset else None,
            transaction_type=txn.transaction_type,
            quantity=float(txn.quantity) if txn.quantity else None,
            price_per_unit=float(txn.price_per_unit) if txn.price_per_unit else None,
            fees=float(txn.fees or 0),
            gross_amount=float(txn.gross_amount) if txn.gross_amount else None,
            tax_withheld=float(txn.tax_withheld) if txn.tax_withheld else None,
            dividend_per_share=float(txn.dividend_per_share) if txn.dividend_per_share else None,
            net_amount=float(txn.net_amount) if txn.net_amount else None,
            currency=txn.currency,
            fx_rate_to_aud=float(txn.fx_rate_to_aud) if txn.fx_rate_to_aud else None,
            net_amount_aud=float(txn.net_amount_aud) if txn.net_amount_aud else None,
            price_per_unit_aud=float(txn.price_per_unit_aud) if txn.price_per_unit_aud else None,
            ex_date=txn.ex_date,
            franking_pct=float(txn.franking_pct) if txn.franking_pct else None,
            franking_credit=float(txn.franking_credit) if txn.franking_credit else None,
            transacted_at=txn.transacted_at,
            source=txn.source,
            notes=txn.notes,
            created_at=txn.created_at,
        )
        for txn, asset in rows
    ]


@router.post("/", response_model=TransactionResponse, status_code=201)
async def create_transaction(
    body: TransactionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Validate account ownership
    acct_result = await db.execute(
        select(Account).where(Account.id == body.account_id, Account.user_id == current_user.id)
    )
    account = acct_result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    api_result = await db.execute(
        select(ApiCredential.id).where(
            ApiCredential.account_id == body.account_id,
            ApiCredential.user_id == current_user.id,
            ApiCredential.is_active == True,
        )
    )
    if api_result.scalar_one_or_none():
        raise HTTPException(
            status_code=403,
            detail="Manual transactions are disabled for API-connected accounts. Sync the account from its provider instead.",
        )

    txn_type = body.transaction_type.upper()
    symbol = body.asset_symbol.strip().upper() if body.asset_symbol else None
    asset_required_types = {
        "BUY", "SELL", "DIVIDEND", "DISTRIBUTION", "STAKE_REWARD",
        "TRANSFER_IN", "TRANSFER_OUT", "AIRDROP", "MINING_REWARD", "SPLIT", "SWAP",
    }
    if txn_type in asset_required_types and not symbol:
        raise HTTPException(status_code=422, detail=f"Asset symbol is required for {txn_type} transactions")

    asset = None
    if symbol:
        asset_class = "CRYPTO" if account.account_type == "CRYPTO_EXCHANGE" else "EQUITY"
        asset = await get_or_create_asset(db, symbol, body.currency, asset_class)

    qty = Decimal(str(body.quantity)) if body.quantity else None
    price = Decimal(str(body.price_per_unit)) if body.price_per_unit else None
    fees = Decimal(str(body.fees))
    manual_net = Decimal(str(body.net_amount)) if body.net_amount is not None else None

    net = manual_net
    if net is None and qty and price:
        if txn_type == "SELL":
            net = qty * price - fees
        elif txn_type in {"DIVIDEND", "DISTRIBUTION", "INTEREST"}:
            net = qty * price - fees
        elif txn_type in {"BUY", "TRANSFER_IN", "STAKE_REWARD", "AIRDROP", "MINING_REWARD"}:
            net = -(qty * price + fees)
    if net is None and txn_type == "FEE" and fees:
        net = -fees

    fx_data = await enrich_transaction_with_aud(
        body.currency.upper(),
        qty,
        price,
        net,
        body.transacted_at,
    )

    txn = Transaction(
        account_id=body.account_id,
        user_id=current_user.id,
        asset_id=asset.id if asset else None,
        transaction_type=txn_type,
        quantity=qty,
        price_per_unit=price,
        dividend_per_share=price if txn_type in {"DIVIDEND", "DISTRIBUTION"} else None,
        fees=fees,
        net_amount=net,
        fx_rate_to_aud=fx_data["fx_rate_to_aud"],
        net_amount_aud=fx_data["net_amount_aud"],
        price_per_unit_aud=fx_data["price_per_unit_aud"],
        currency=body.currency.upper(),
        transacted_at=body.transacted_at,
        source="MANUAL",
        notes=body.notes,
    )
    db.add(txn)
    await db.commit()
    await db.refresh(txn)
    await cache_invalidate_user(current_user.id)

    return TransactionResponse(
        id=txn.id, account_id=txn.account_id, asset_id=txn.asset_id,
        symbol=asset.symbol if asset else None, transaction_type=txn.transaction_type,
        quantity=float(txn.quantity) if txn.quantity else None,
        price_per_unit=float(txn.price_per_unit) if txn.price_per_unit else None,
        fees=float(txn.fees or 0), net_amount=float(txn.net_amount) if txn.net_amount else None,
        currency=txn.currency,
        fx_rate_to_aud=float(txn.fx_rate_to_aud) if txn.fx_rate_to_aud else None,
        net_amount_aud=float(txn.net_amount_aud) if txn.net_amount_aud else None,
        price_per_unit_aud=float(txn.price_per_unit_aud) if txn.price_per_unit_aud else None,
        transacted_at=txn.transacted_at,
        source=txn.source, notes=txn.notes, created_at=txn.created_at,
    )


@router.delete("/{transaction_id}", status_code=204)
async def delete_transaction(
    transaction_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Transaction).where(Transaction.id == transaction_id, Transaction.user_id == current_user.id)
    )
    txn = result.scalar_one_or_none()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if txn.source in API_TRANSACTION_SOURCES:
        raise HTTPException(
            status_code=403,
            detail="API-synced transactions are read-only. Delete or correct them at the provider, then re-sync.",
        )

    api_result = await db.execute(
        select(ApiCredential.id).where(
            ApiCredential.account_id == txn.account_id,
            ApiCredential.user_id == current_user.id,
            ApiCredential.is_active == True,
        )
    )
    if api_result.scalar_one_or_none():
        raise HTTPException(
            status_code=403,
            detail="Transactions in API-connected accounts are read-only. Sync the account from its provider instead.",
        )

    await db.delete(txn)
    await db.commit()
    await cache_invalidate_user(current_user.id)


@router.post("/import", response_model=ImportResultResponse)
async def import_transactions(
    file: UploadFile = File(...),
    account_id: str = Form(...),
    broker_hint: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Import transactions from CSV, Excel, or JSON file.
    Auto-detects schema and deduplicates against existing records.
    """
    # Validate account
    acct_result = await db.execute(
        select(Account).where(Account.id == account_id, Account.user_id == current_user.id)
    )
    if not acct_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Account not found")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    filename = file.filename or "upload.csv"
    ext = filename.lower().split(".")[-1]
    if ext not in ("csv", "txt", "xlsx", "xls", "json"):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '.{ext}'. Please upload a CSV, Excel, or JSON file."
        )

    importer = TransactionImporter(db)
    try:
        result = await importer.import_file(
            file_content=content,
            file_name=filename,
            account_id=account_id,
            user_id=current_user.id,
            broker_hint=broker_hint,
        )
    except Exception as exc:
        logger.error("Import failed for account %s: %s", account_id, exc)
        raise HTTPException(status_code=500, detail=f"Import error: {exc}")

    if result.imported > 0:
        await cache_invalidate_user(current_user.id)

    # If nothing was imported and there are errors, surface them clearly
    if result.imported == 0 and result.duplicates == 0 and result.errors > 0:
        raise HTTPException(
            status_code=422,
            detail=f"No transactions imported. Errors: {'; '.join(result.error_details[:5])}"
        )

    return ImportResultResponse(
        total_rows=result.total_rows,
        imported=result.imported,
        duplicates=result.duplicates,
        errors=result.errors,
        error_details=result.error_details[:20],
        transaction_ids=result.transactions,
        broker_detected=result.broker_detected,
    )
