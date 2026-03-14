"""
Bank & Payment Platform Transaction Import Service.

Parses CSV/Excel exports from Australian banks and payment platforms,
normalises them into the platform's Transaction schema, and enriches
each row with AUD amounts via the FX service.

Supported sources:
  - Commonwealth Bank (CBA)
  - ANZ
  - Westpac
  - NAB
  - Bendigo Bank
  - PayPal
  - Wise (TransferWise)
  - AirTM
"""
from __future__ import annotations

import csv
import hashlib
import io
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Optional

import pandas as pd

from services.fx_service import FXService, enrich_transaction_with_aud

logger = logging.getLogger(__name__)


# ─── Institution identifiers ──────────────────────────────────────────────────

class Institution(str, Enum):
    CBA = "cba"
    ANZ = "anz"
    WESTPAC = "westpac"
    NAB = "nab"
    BENDIGO = "bendigo"
    PAYPAL = "paypal"
    WISE = "wise"
    AIRTM = "airtm"
    UNKNOWN = "unknown"


# ─── Normalised row ───────────────────────────────────────────────────────────

@dataclass
class NormalisedBankTransaction:
    """Platform-neutral representation of a single bank/payment transaction."""
    institution: Institution
    date: datetime
    description: str
    amount: Decimal          # Positive = credit/inflow; negative = debit/outflow
    currency: str            # ISO 4217 (AUD for most banks; can vary for PayPal/Wise/AirTM)
    balance: Optional[Decimal] = None
    reference: Optional[str] = None
    raw_type: Optional[str] = None  # Original type/category from source
    import_hash: str = ""

    # Populated by FX enrichment
    amount_aud: Optional[Decimal] = None
    fx_rate_to_aud: Optional[Decimal] = None

    def compute_hash(self) -> str:
        """SHA-256 deduplication key."""
        payload = f"{self.institution}|{self.date.isoformat()}|{self.description}|{self.amount}|{self.currency}"
        return hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class BankImportResult:
    institution: Institution
    total_rows: int
    imported: int
    duplicates: int
    errors: int
    transactions: list[NormalisedBankTransaction] = field(default_factory=list)
    error_details: list[str] = field(default_factory=list)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _parse_decimal(value: str | float | None, default: Decimal = Decimal("0")) -> Optional[Decimal]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        cleaned = re.sub(r"[^\d.,()\-]", "", str(value)).replace(",", "")
        # Handle parentheses as negative (accounting format)
        if cleaned.startswith("(") and cleaned.endswith(")"):
            cleaned = "-" + cleaned[1:-1]
        return Decimal(cleaned) if cleaned else None
    except (InvalidOperation, ValueError):
        return None


def _parse_date(value: str, formats: list[str]) -> Optional[datetime]:
    for fmt in formats:
        try:
            return datetime.strptime(str(value).strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _detect_institution(df: pd.DataFrame) -> Institution:
    """Heuristic detection from column headers."""
    cols_lower = {c.strip().lower() for c in df.columns}

    if {"date", "description", "debit", "credit", "balance"} <= cols_lower:
        # CBA and ANZ share a similar schema; distinguish by secondary signals
        col_names = [c.strip().lower() for c in df.columns]
        if col_names[1] in ("description",):
            return Institution.CBA
        if col_names[1] in ("details",):
            return Institution.ANZ
        return Institution.CBA  # Default to CBA for this pattern

    if {"date", "description", "credits", "debits", "balance"} <= cols_lower:
        return Institution.WESTPAC

    if {"date", "time", "transaction details", "credit", "debit", "balance"} <= cols_lower:
        return Institution.NAB

    if {"date", "amount", "currency", "description", "transferwise id"} <= cols_lower:
        return Institution.WISE
    if {"date", "amount", "currency", "description", "transfer wise id"} <= cols_lower:
        return Institution.WISE

    if {"date", "name", "type", "status", "currency", "amount", "receipt id", "balance"} <= cols_lower:
        return Institution.PAYPAL
    # PayPal sometimes uses "Transaction ID" instead of "Receipt ID"
    if {"date", "name", "type", "status", "currency", "amount"} <= cols_lower:
        return Institution.PAYPAL

    if {"operation id", "date", "type", "amount", "currency", "status", "description"} <= cols_lower:
        return Institution.AIRTM

    if {"date", "narration", "credit", "debit", "balance"} <= cols_lower:
        return Institution.BENDIGO
    if {"transaction date", "narration", "credit amount", "debit amount", "balance"} <= cols_lower:
        return Institution.BENDIGO

    return Institution.UNKNOWN


# ─── Institution parsers ──────────────────────────────────────────────────────

_AU_DATE_FORMATS = ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y", "%d/%m/%y"]


def _parse_cba(df: pd.DataFrame) -> list[NormalisedBankTransaction]:
    """
    Commonwealth Bank CSV format:
    Date, Description, Debit, Credit, Balance
    """
    rows = []
    for _, row in df.iterrows():
        dt = _parse_date(row.get("Date", ""), _AU_DATE_FORMATS)
        if dt is None:
            continue
        description = str(row.get("Description", "")).strip()
        debit = _parse_decimal(row.get("Debit"))
        credit = _parse_decimal(row.get("Credit"))
        balance = _parse_decimal(row.get("Balance"))

        if debit and debit > 0:
            amount = -debit
        elif credit and credit > 0:
            amount = credit
        else:
            amount = Decimal("0")

        t = NormalisedBankTransaction(
            institution=Institution.CBA,
            date=dt,
            description=description,
            amount=amount,
            currency="AUD",
            balance=balance,
        )
        t.import_hash = t.compute_hash()
        rows.append(t)
    return rows


def _parse_anz(df: pd.DataFrame) -> list[NormalisedBankTransaction]:
    """
    ANZ CSV format:
    Date, Details, Debit, Credit, Balance
    """
    rows = []
    for _, row in df.iterrows():
        dt = _parse_date(row.get("Date", ""), _AU_DATE_FORMATS)
        if dt is None:
            continue
        description = str(row.get("Details", "")).strip()
        debit = _parse_decimal(row.get("Debit"))
        credit = _parse_decimal(row.get("Credit"))
        balance = _parse_decimal(row.get("Balance"))

        if debit and debit > 0:
            amount = -debit
        elif credit and credit > 0:
            amount = credit
        else:
            amount = Decimal("0")

        t = NormalisedBankTransaction(
            institution=Institution.ANZ,
            date=dt,
            description=description,
            amount=amount,
            currency="AUD",
            balance=balance,
        )
        t.import_hash = t.compute_hash()
        rows.append(t)
    return rows


def _parse_westpac(df: pd.DataFrame) -> list[NormalisedBankTransaction]:
    """
    Westpac CSV format:
    Date, Description, Credits, Debits, Balance
    """
    rows = []
    for _, row in df.iterrows():
        dt = _parse_date(row.get("Date", ""), _AU_DATE_FORMATS)
        if dt is None:
            continue
        description = str(row.get("Description", "")).strip()
        debit = _parse_decimal(row.get("Debits"))
        credit = _parse_decimal(row.get("Credits"))
        balance = _parse_decimal(row.get("Balance"))

        if debit and debit > 0:
            amount = -debit
        elif credit and credit > 0:
            amount = credit
        else:
            amount = Decimal("0")

        t = NormalisedBankTransaction(
            institution=Institution.WESTPAC,
            date=dt,
            description=description,
            amount=amount,
            currency="AUD",
            balance=balance,
        )
        t.import_hash = t.compute_hash()
        rows.append(t)
    return rows


def _parse_nab(df: pd.DataFrame) -> list[NormalisedBankTransaction]:
    """
    NAB CSV format:
    Date, Time, Transaction Details, Credit, Debit, Balance
    """
    rows = []
    for _, row in df.iterrows():
        date_str = str(row.get("Date", "")).strip()
        time_str = str(row.get("Time", "")).strip()
        combined = f"{date_str} {time_str}".strip() if time_str else date_str

        dt = _parse_date(combined, ["%d-%m-%Y %H:%M:%S", "%d-%m-%Y", *_AU_DATE_FORMATS])
        if dt is None:
            dt = _parse_date(date_str, _AU_DATE_FORMATS)
        if dt is None:
            continue

        description = str(row.get("Transaction Details", "")).strip()
        credit = _parse_decimal(row.get("Credit"))
        debit = _parse_decimal(row.get("Debit"))
        balance = _parse_decimal(row.get("Balance"))

        if credit and credit > 0:
            amount = credit
        elif debit and debit > 0:
            amount = -debit
        else:
            amount = Decimal("0")

        t = NormalisedBankTransaction(
            institution=Institution.NAB,
            date=dt,
            description=description,
            amount=amount,
            currency="AUD",
            balance=balance,
        )
        t.import_hash = t.compute_hash()
        rows.append(t)
    return rows


def _parse_bendigo(df: pd.DataFrame) -> list[NormalisedBankTransaction]:
    """
    Bendigo Bank CSV format:
    Transaction Date, Narration, Credit Amount, Debit Amount, Balance
    (or: Date, Narration, Credit, Debit, Balance)
    """
    rows = []
    # Normalise column names
    df.columns = [c.strip() for c in df.columns]
    date_col = next((c for c in df.columns if "date" in c.lower()), None)
    desc_col = next((c for c in df.columns if "narration" in c.lower() or "description" in c.lower()), None)
    credit_col = next((c for c in df.columns if "credit" in c.lower()), None)
    debit_col = next((c for c in df.columns if "debit" in c.lower()), None)
    balance_col = next((c for c in df.columns if "balance" in c.lower()), None)

    for _, row in df.iterrows():
        dt = _parse_date(row.get(date_col, ""), _AU_DATE_FORMATS) if date_col else None
        if dt is None:
            continue
        description = str(row.get(desc_col, "")).strip() if desc_col else ""
        credit = _parse_decimal(row.get(credit_col)) if credit_col else None
        debit = _parse_decimal(row.get(debit_col)) if debit_col else None
        balance = _parse_decimal(row.get(balance_col)) if balance_col else None

        if credit and credit > 0:
            amount = credit
        elif debit and debit > 0:
            amount = -debit
        else:
            amount = Decimal("0")

        t = NormalisedBankTransaction(
            institution=Institution.BENDIGO,
            date=dt,
            description=description,
            amount=amount,
            currency="AUD",
            balance=balance,
        )
        t.import_hash = t.compute_hash()
        rows.append(t)
    return rows


_PAYPAL_DATE_FORMATS = [
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%Y-%m-%d",
    "%d %b %Y",
    "%b %d, %Y",
]


def _parse_paypal(df: pd.DataFrame) -> list[NormalisedBankTransaction]:
    """
    PayPal CSV format:
    Date, Name, Type, Status, Currency, Amount, Receipt ID, Balance
    (Note: PayPal uses locale-specific formats; Amount uses commas as thousands separator)
    """
    rows = []
    for _, row in df.iterrows():
        # PayPal sometimes includes time in Date column
        date_raw = str(row.get("Date", "")).strip()
        dt = _parse_date(date_raw, _PAYPAL_DATE_FORMATS)
        if dt is None:
            continue

        # Skip pending/reversed/cancelled
        status = str(row.get("Status", "")).strip().lower()
        if status not in ("completed", "cleared", "success", "succeeded", ""):
            continue

        description = str(row.get("Name", "")).strip() or str(row.get("Type", "")).strip()
        currency = str(row.get("Currency", "AUD")).strip().upper()
        amount = _parse_decimal(row.get("Amount"))
        if amount is None:
            continue

        balance = _parse_decimal(row.get("Balance"))
        reference = str(row.get("Receipt ID", "") or row.get("Transaction ID", "")).strip()
        raw_type = str(row.get("Type", "")).strip()

        t = NormalisedBankTransaction(
            institution=Institution.PAYPAL,
            date=dt,
            description=description,
            amount=amount,
            currency=currency,
            balance=balance,
            reference=reference,
            raw_type=raw_type,
        )
        t.import_hash = t.compute_hash()
        rows.append(t)
    return rows


_WISE_DATE_FORMATS = [
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
]


def _parse_wise(df: pd.DataFrame) -> list[NormalisedBankTransaction]:
    """
    Wise (TransferWise) CSV format:
    TransferWise ID, Date, Amount, Currency, Description, Payment Reference, Running Balance, Exchange From, Exchange To, Exchange Rate, Payer Name, Payee Name, Payee Account Number, Merchant, Card Last Four Digits, Card Holder Full Name, Attachment, Note, Total fees, Exchange To Amount
    """
    rows = []
    df.columns = [c.strip() for c in df.columns]

    for _, row in df.iterrows():
        dt = _parse_date(str(row.get("Date", "")).strip(), _WISE_DATE_FORMATS)
        if dt is None:
            continue

        amount = _parse_decimal(row.get("Amount"))
        if amount is None:
            continue

        currency = str(row.get("Currency", "AUD")).strip().upper()
        description = str(row.get("Description", "")).strip()
        reference = str(row.get("Payment Reference", "") or row.get("TransferWise ID", "")).strip()
        balance = _parse_decimal(row.get("Running Balance"))

        t = NormalisedBankTransaction(
            institution=Institution.WISE,
            date=dt,
            description=description,
            amount=amount,
            currency=currency,
            balance=balance,
            reference=reference,
        )
        t.import_hash = t.compute_hash()
        rows.append(t)
    return rows


_AIRTM_DATE_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
    "%Y-%m-%d",
]


def _parse_airtm(df: pd.DataFrame) -> list[NormalisedBankTransaction]:
    """
    AirTM CSV format:
    Operation ID, Date, Type, Amount, Currency, Status, Description
    """
    rows = []
    df.columns = [c.strip() for c in df.columns]

    for _, row in df.iterrows():
        # Skip non-completed operations
        status = str(row.get("Status", "")).strip().lower()
        if status not in ("completed", "success", "approved", ""):
            continue

        dt = _parse_date(str(row.get("Date", "")).strip(), _AIRTM_DATE_FORMATS)
        if dt is None:
            continue

        amount = _parse_decimal(row.get("Amount"))
        if amount is None:
            continue

        currency = str(row.get("Currency", "USD")).strip().upper()
        description = str(row.get("Description", "") or row.get("Type", "")).strip()
        reference = str(row.get("Operation ID", "")).strip()
        raw_type = str(row.get("Type", "")).strip()

        # AirTM marks withdrawals/payments as positive with a "debit" type;
        # normalise so outflows are negative
        raw_type_lower = raw_type.lower()
        if any(k in raw_type_lower for k in ("withdraw", "payment", "send", "debit", "fee")):
            if amount > 0:
                amount = -amount

        t = NormalisedBankTransaction(
            institution=Institution.AIRTM,
            date=dt,
            description=description,
            amount=amount,
            currency=currency,
            reference=reference,
            raw_type=raw_type,
        )
        t.import_hash = t.compute_hash()
        rows.append(t)
    return rows


# ─── Parser dispatch ──────────────────────────────────────────────────────────

_PARSERS = {
    Institution.CBA: _parse_cba,
    Institution.ANZ: _parse_anz,
    Institution.WESTPAC: _parse_westpac,
    Institution.NAB: _parse_nab,
    Institution.BENDIGO: _parse_bendigo,
    Institution.PAYPAL: _parse_paypal,
    Institution.WISE: _parse_wise,
    Institution.AIRTM: _parse_airtm,
}


# ─── Main service ─────────────────────────────────────────────────────────────

class BankImportService:
    """
    Orchestrates detection → parsing → FX enrichment → deduplication.

    Usage:
        svc = BankImportService()
        result = await svc.import_file(file_bytes, filename="cba_export.csv",
                                       institution_hint="cba")
    """

    def __init__(self, fx_service: Optional[FXService] = None):
        self._fx = fx_service or FXService()
        self._owns_fx = fx_service is None

    async def import_file(
        self,
        file_bytes: bytes,
        filename: str,
        institution_hint: Optional[str] = None,
        existing_hashes: Optional[set[str]] = None,
    ) -> BankImportResult:
        """
        Parse, enrich and return normalised transactions.

        Args:
            file_bytes: Raw file content (CSV or Excel).
            filename: Original filename (used to determine file type).
            institution_hint: Optional override (e.g. "paypal", "wise").
            existing_hashes: Set of import_hash values already in the DB.

        Returns:
            BankImportResult with normalised + FX-enriched transactions.
        """
        existing_hashes = existing_hashes or set()

        # Load into DataFrame
        try:
            df = self._load_dataframe(file_bytes, filename)
        except Exception as exc:
            return BankImportResult(
                institution=Institution.UNKNOWN,
                total_rows=0, imported=0, duplicates=0, errors=1,
                error_details=[f"Failed to parse file: {exc}"],
            )

        # Detect or override institution
        institution = Institution.UNKNOWN
        if institution_hint:
            try:
                institution = Institution(institution_hint.lower())
            except ValueError:
                pass

        if institution == Institution.UNKNOWN:
            institution = _detect_institution(df)

        logger.info(f"Bank import: detected institution={institution}, rows={len(df)}")

        # Parse rows
        parser = _PARSERS.get(institution)
        if parser is None:
            return BankImportResult(
                institution=institution,
                total_rows=len(df), imported=0, duplicates=0, errors=1,
                error_details=[f"No parser for institution: {institution}"],
            )

        try:
            raw_rows = parser(df)
        except Exception as exc:
            logger.exception(f"Parser error for {institution}")
            return BankImportResult(
                institution=institution,
                total_rows=len(df), imported=0, duplicates=0, errors=1,
                error_details=[f"Parser error: {exc}"],
            )

        # FX enrichment + deduplication
        imported, duplicates, errors = 0, 0, 0
        good: list[NormalisedBankTransaction] = []
        error_details: list[str] = []

        for row in raw_rows:
            if row.import_hash in existing_hashes:
                duplicates += 1
                continue
            try:
                row = await self._enrich_fx(row)
                good.append(row)
                imported += 1
            except Exception as exc:
                errors += 1
                error_details.append(f"{row.date.date()} {row.description[:40]}: {exc}")

        return BankImportResult(
            institution=institution,
            total_rows=len(df),
            imported=imported,
            duplicates=duplicates,
            errors=errors,
            transactions=good,
            error_details=error_details,
        )

    async def _enrich_fx(self, row: NormalisedBankTransaction) -> NormalisedBankTransaction:
        """Convert row amount to AUD using the FX service."""
        if row.currency == "AUD":
            row.amount_aud = row.amount
            row.fx_rate_to_aud = Decimal("1.0")
            return row

        result = await enrich_transaction_with_aud(
            transaction_currency=row.currency,
            quantity=None,
            price_per_unit=None,
            net_amount=row.amount,
            on_date=row.date,
            fx_svc=self._fx,
        )
        row.fx_rate_to_aud = result["fx_rate_to_aud"]
        row.amount_aud = result["net_amount_aud"]
        return row

    @staticmethod
    def _load_dataframe(file_bytes: bytes, filename: str) -> pd.DataFrame:
        """Load CSV or Excel file into a DataFrame with stripped column names."""
        fname_lower = filename.lower()

        if fname_lower.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(file_bytes), dtype=str)
        else:
            # Try common encodings
            for encoding in ("utf-8-sig", "utf-8", "latin-1"):
                try:
                    text = file_bytes.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                text = file_bytes.decode("latin-1", errors="replace")

            # PayPal CSVs sometimes have leading metadata rows; skip until header
            lines = text.splitlines()
            header_idx = 0
            for i, line in enumerate(lines):
                # A header line has multiple comma-separated tokens, no numeric-only start
                parts = line.split(",")
                if len(parts) >= 3 and not parts[0].strip().replace("-", "").replace("/", "").isdigit():
                    header_idx = i
                    break

            clean_text = "\n".join(lines[header_idx:])
            df = pd.read_csv(io.StringIO(clean_text), dtype=str)

        # Strip whitespace from column names
        df.columns = [str(c).strip() for c in df.columns]
        return df

    async def close(self):
        if self._owns_fx:
            await self._fx.close()


# ─── Convenience function ─────────────────────────────────────────────────────

async def import_bank_file(
    file_bytes: bytes,
    filename: str,
    institution_hint: Optional[str] = None,
    existing_hashes: Optional[set[str]] = None,
) -> BankImportResult:
    """One-shot helper that creates and closes its own BankImportService."""
    svc = BankImportService()
    try:
        return await svc.import_file(file_bytes, filename, institution_hint, existing_hashes)
    finally:
        await svc.close()
