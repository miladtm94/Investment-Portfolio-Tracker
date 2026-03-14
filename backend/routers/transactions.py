"""Transactions router — CRUD, import, history."""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc

from database import get_db
from shared.models import Account, Asset, Transaction, User
from shared.auth import get_current_user
from shared.cache import cache_invalidate_user
from services.transaction_import import TransactionImporter

router = APIRouter()


class TransactionCreate(BaseModel):
    account_id: str
    asset_symbol: str
    transaction_type: str
    quantity: Optional[float] = None
    price_per_unit: Optional[float] = None
    fees: float = 0.0
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
    net_amount: Optional[float]
    currency: str
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
            net_amount=float(txn.net_amount) if txn.net_amount else None,
            currency=txn.currency,
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
    if not acct_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Account not found")

    # Resolve or create asset
    asset_result = await db.execute(select(Asset).where(Asset.symbol == body.asset_symbol.upper()))
    asset = asset_result.scalar_one_or_none()
    if not asset:
        asset = Asset(symbol=body.asset_symbol.upper(), name=body.asset_symbol.upper(), asset_class="EQUITY", currency="USD")
        db.add(asset)
        await db.flush()

    qty = Decimal(str(body.quantity)) if body.quantity else None
    price = Decimal(str(body.price_per_unit)) if body.price_per_unit else None
    fees = Decimal(str(body.fees))

    net = None
    if qty and price:
        net = qty * price - fees if body.transaction_type == "SELL" else -(qty * price + fees)

    txn = Transaction(
        account_id=body.account_id,
        user_id=current_user.id,
        asset_id=asset.id,
        transaction_type=body.transaction_type.upper(),
        quantity=qty,
        price_per_unit=price,
        fees=fees,
        net_amount=net,
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
        symbol=asset.symbol, transaction_type=txn.transaction_type,
        quantity=float(txn.quantity) if txn.quantity else None,
        price_per_unit=float(txn.price_per_unit) if txn.price_per_unit else None,
        fees=float(txn.fees), net_amount=float(txn.net_amount) if txn.net_amount else None,
        currency=txn.currency, transacted_at=txn.transacted_at,
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
    await db.delete(txn)
    await db.commit()
    await cache_invalidate_user(current_user.id)


@router.post("/import", response_model=ImportResultResponse)
async def import_transactions(
    file: UploadFile = File(...),
    account_id: str = Form(...),
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
    importer = TransactionImporter(db)
    result = await importer.import_file(
        file_content=content,
        file_name=file.filename or "upload.csv",
        account_id=account_id,
        user_id=current_user.id,
    )

    if result.imported > 0:
        await cache_invalidate_user(current_user.id)

    return ImportResultResponse(
        total_rows=result.total_rows,
        imported=result.imported,
        duplicates=result.duplicates,
        errors=result.errors,
        error_details=result.error_details[:20],
        transaction_ids=result.transactions,
        broker_detected=result.broker_detected,
    )
