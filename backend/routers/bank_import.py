"""
Bank & Payment Platform Import Router.

POST /api/bank-import/upload  — upload a CSV/Excel statement and get
                                normalised + FX-enriched transactions back.
POST /api/bank-import/confirm — persist confirmed transactions to the DB.
GET  /api/bank-import/institutions — list supported institutions.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from shared.database import get_db
from shared.models import Account, Transaction
from services.bank_import_service import (
    BankImportResult,
    BankImportService,
    Institution,
    NormalisedBankTransaction,
    import_bank_file,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/bank-import", tags=["bank-import"])


# ─── Response schemas ─────────────────────────────────────────────────────────

class NormalisedTxResponse(BaseModel):
    date: str
    description: str
    amount: float
    currency: str
    amount_aud: Optional[float]
    fx_rate_to_aud: Optional[float]
    balance: Optional[float]
    reference: Optional[str]
    raw_type: Optional[str]
    import_hash: str

    @classmethod
    def from_norm(cls, t: NormalisedBankTransaction) -> "NormalisedTxResponse":
        return cls(
            date=t.date.date().isoformat(),
            description=t.description,
            amount=float(t.amount),
            currency=t.currency,
            amount_aud=float(t.amount_aud) if t.amount_aud is not None else None,
            fx_rate_to_aud=float(t.fx_rate_to_aud) if t.fx_rate_to_aud is not None else None,
            balance=float(t.balance) if t.balance is not None else None,
            reference=t.reference,
            raw_type=t.raw_type,
            import_hash=t.import_hash,
        )


class ImportPreviewResponse(BaseModel):
    institution: str
    total_rows: int
    imported: int
    duplicates: int
    errors: int
    transactions: list[NormalisedTxResponse]
    error_details: list[str]


class ConfirmRequest(BaseModel):
    account_id: str
    institution: str
    import_hashes: list[str]   # Which transactions to persist (user may deselect some)
    transactions: list[NormalisedTxResponse]


class ConfirmResponse(BaseModel):
    saved: int
    skipped_duplicates: int


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/institutions")
async def list_institutions():
    """Return the list of supported bank/payment institutions."""
    return {
        "institutions": [
            {"id": "cba",      "name": "Commonwealth Bank (CBA)",  "country": "AU", "type": "bank"},
            {"id": "anz",      "name": "ANZ",                      "country": "AU", "type": "bank"},
            {"id": "westpac",  "name": "Westpac",                  "country": "AU", "type": "bank"},
            {"id": "nab",      "name": "NAB",                      "country": "AU", "type": "bank"},
            {"id": "bendigo",  "name": "Bendigo Bank",             "country": "AU", "type": "bank"},
            {"id": "paypal",   "name": "PayPal",                   "country": "INTL", "type": "payment"},
            {"id": "wise",     "name": "Wise (TransferWise)",       "country": "INTL", "type": "payment"},
            {"id": "airtm",    "name": "AirTM",                    "country": "INTL", "type": "payment"},
        ]
    }


@router.post("/upload", response_model=ImportPreviewResponse)
async def upload_statement(
    file: UploadFile = File(...),
    institution: Optional[str] = Form(None),
    account_id: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a bank/payment CSV or Excel statement.

    Returns a preview of parsed + FX-enriched transactions without persisting
    anything.  The client should show these to the user and call /confirm to
    save the selected rows.

    Args:
        file: The CSV or Excel file.
        institution: Optional institution hint (e.g. "cba", "paypal").
        account_id: Optional account UUID to check against existing imports.
    """
    if file.content_type not in (
        "text/csv",
        "application/csv",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/plain",
        "application/octet-stream",
    ):
        # Be permissive — browsers report content types inconsistently
        logger.debug(f"Bank import content-type: {file.content_type}")

    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(file_bytes) > 10 * 1024 * 1024:  # 10 MB safety limit
        raise HTTPException(status_code=400, detail="File too large (max 10 MB)")

    # Fetch existing hashes for this account to detect duplicates
    existing_hashes: set[str] = set()
    if account_id:
        from sqlalchemy import select, text
        result = await db.execute(
            select(Transaction.import_hash).where(
                Transaction.account_id == account_id,
                Transaction.import_hash.isnot(None),
            )
        )
        existing_hashes = {row[0] for row in result.fetchall() if row[0]}

    result: BankImportResult = await import_bank_file(
        file_bytes=file_bytes,
        filename=file.filename or "upload.csv",
        institution_hint=institution,
        existing_hashes=existing_hashes,
    )

    return ImportPreviewResponse(
        institution=result.institution.value,
        total_rows=result.total_rows,
        imported=result.imported,
        duplicates=result.duplicates,
        errors=result.errors,
        transactions=[NormalisedTxResponse.from_norm(t) for t in result.transactions],
        error_details=result.error_details,
    )


@router.post("/confirm", response_model=ConfirmResponse)
async def confirm_import(
    body: ConfirmRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Persist the user-confirmed bank transactions to the Transaction table.

    The client sends back the import_hashes the user approved.  We save
    those rows as DEPOSIT (inflow) or WITHDRAWAL (outflow) transactions
    linked to the given account.
    """
    # Validate account exists
    from sqlalchemy import select
    account_result = await db.execute(
        select(Account).where(Account.id == body.account_id)
    )
    account = account_result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    approved_set = set(body.import_hashes)

    # Check for existing hashes to avoid duplicates on double-confirm
    existing_result = await db.execute(
        select(Transaction.import_hash).where(
            Transaction.account_id == body.account_id,
            Transaction.import_hash.isnot(None),
        )
    )
    already_saved = {row[0] for row in existing_result.fetchall() if row[0]}

    saved = 0
    skipped = 0

    for tx_data in body.transactions:
        if tx_data.import_hash not in approved_set:
            continue
        if tx_data.import_hash in already_saved:
            skipped += 1
            continue

        amount = Decimal(str(tx_data.amount))
        tx_type = "DEPOSIT" if amount >= 0 else "WITHDRAWAL"

        tx = Transaction(
            account_id=body.account_id,
            transaction_type=tx_type,
            transaction_date=tx_data.date,   # stored as str ISO; model coerces
            symbol=None,
            asset_id=None,
            quantity=None,
            price_per_unit=None,
            net_amount=abs(amount),
            currency=tx_data.currency,
            fx_rate_to_aud=Decimal(str(tx_data.fx_rate_to_aud)) if tx_data.fx_rate_to_aud else None,
            net_amount_aud=Decimal(str(tx_data.amount_aud)) if tx_data.amount_aud else None,
            price_per_unit_aud=None,
            notes=tx_data.description,
            institution=body.institution,
            import_hash=tx_data.import_hash,
        )
        db.add(tx)
        saved += 1

    await db.commit()
    return ConfirmResponse(saved=saved, skipped_duplicates=skipped)
