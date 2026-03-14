"""
Transaction Import Engine.

Parses CSV/Excel/JSON exports from brokers and exchanges,
normalizes to canonical schema, and deduplicates against existing records.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from shared.models import Account, Asset, Transaction

logger = logging.getLogger(__name__)

ZERO = Decimal("0")

CANONICAL_FIELDS = [
    "date", "type", "symbol", "quantity", "price",
    "fees", "currency", "amount", "exchange", "notes",
]

TYPE_ALIASES = {
    # Buys
    "buy": "BUY", "bought": "BUY", "purchase": "BUY", "b": "BUY",
    # Sells
    "sell": "SELL", "sold": "SELL", "s": "SELL",
    # Dividends
    "dividend": "DIVIDEND", "div": "DIVIDEND", "dividends reinvested": "DIVIDEND",
    # Transfers
    "transfer": "TRANSFER_IN", "deposit": "DEPOSIT", "withdrawal": "WITHDRAWAL",
    # Crypto
    "stake_reward": "STAKE_REWARD", "staking": "STAKE_REWARD",
    "airdrop": "AIRDROP", "mining": "MINING_REWARD",
    "swap": "SWAP", "convert": "SWAP", "exchange": "SWAP",
    # Splits
    "split": "SPLIT",
    # Fees
    "fee": "FEE", "commission": "FEE",
}


@dataclass
class ParsedTransaction:
    """A normalized transaction ready for deduplication and insertion."""
    date: datetime
    transaction_type: str
    symbol: str
    quantity: Optional[Decimal]
    price: Optional[Decimal]
    fees: Decimal
    currency: str
    net_amount: Optional[Decimal]
    notes: Optional[str]
    raw_row: dict
    import_hash: str


@dataclass
class ImportResult:
    """Result of an import operation."""
    total_rows: int
    imported: int
    duplicates: int
    errors: int
    error_details: list[str]
    transactions: list[str]  # IDs of imported transactions


class TransactionImporter:
    """
    Multi-format transaction importer with automatic schema detection.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def import_file(
        self,
        file_content: bytes,
        file_name: str,
        account_id: str,
        user_id: str,
        source: str = "CSV_IMPORT",
    ) -> ImportResult:
        """
        Auto-detect file format and import transactions.
        """
        ext = file_name.lower().split(".")[-1]

        if ext in ("csv", "txt"):
            rows = self._parse_csv(file_content)
        elif ext in ("xlsx", "xls"):
            rows = self._parse_excel(file_content)
        elif ext == "json":
            rows = self._parse_json(file_content)
        else:
            return ImportResult(0, 0, 0, 1, [f"Unsupported file format: {ext}"], [])

        # Normalize and detect schema
        normalized = self._normalize_rows(rows)

        # Deduplicate and insert
        return await self._process_transactions(normalized, account_id, user_id, source)

    def _parse_csv(self, content: bytes) -> list[dict]:
        """
        Parse CSV with automatic delimiter detection.
        Falls back gracefully for files with metadata rows before the header
        (e.g. CommSec, Stake exports).
        """
        for encoding in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                text = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = content.decode("latin-1", errors="replace")

        lines = text.splitlines()

        # Find the first line that looks like a real header:
        # has multiple comma/tab/semicolon-separated tokens and no leading digits
        header_idx = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            # A data/header line has at least 2 delimited tokens
            for delim in (",", "\t", ";"):
                parts = stripped.split(delim)
                if len(parts) >= 2 and not parts[0].strip().lstrip("-").replace(".", "").isdigit():
                    header_idx = i
                    break
            else:
                continue
            break

        clean_text = "\n".join(lines[header_idx:])

        # Try sniffer first, fall back to comma
        try:
            dialect = csv.Sniffer().sniff(clean_text[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel  # plain comma

        reader = csv.DictReader(io.StringIO(clean_text), dialect=dialect)
        return [dict(row) for row in reader if any(v and str(v).strip() for v in row.values())]

    def _parse_excel(self, content: bytes) -> list[dict]:
        """Parse Excel file."""
        df = pd.read_excel(io.BytesIO(content), engine="openpyxl")
        df = df.dropna(how="all")
        return df.to_dict(orient="records")

    def _parse_json(self, content: bytes) -> list[dict]:
        """Parse JSON export."""
        data = json.loads(content)
        if isinstance(data, list):
            return data
        # Try to find the records array
        for key in ("transactions", "trades", "history", "records", "data"):
            if key in data and isinstance(data[key], list):
                return data[key]
        return [data]

    def _normalize_rows(self, rows: list[dict]) -> list[ParsedTransaction]:
        """
        Detect field mapping and normalize each row to canonical schema.
        """
        if not rows:
            return []

        # Auto-detect column mapping
        mapping = self._detect_schema(rows[0])
        normalized = []

        for i, row in enumerate(rows):
            try:
                txn = self._normalize_row(row, mapping)
                if txn:
                    normalized.append(txn)
            except Exception as e:
                logger.warning(f"Row {i}: parse error: {e} — row: {row}")

        return normalized

    def _detect_schema(self, sample_row: dict) -> dict[str, str]:
        """
        Map source columns to canonical field names using fuzzy matching.
        Returns: {canonical_field: source_column}
        """
        COLUMN_PATTERNS = {
            "date": ["date", "time", "datetime", "trade date", "transaction date", "timestamp", "settled"],
            "type": ["type", "transaction type", "action", "transaction", "side", "order type"],
            "symbol": ["symbol", "ticker", "asset", "coin", "currency", "instrument", "security"],
            "quantity": ["quantity", "qty", "amount", "shares", "units", "size", "filled qty"],
            "price": ["price", "price per share", "unit price", "fill price", "avg price", "rate"],
            "fees": ["fees", "fee", "commission", "cost", "charges", "brokerage"],
            "currency": ["currency", "ccy", "quote currency"],
            "net_amount": ["net amount", "total", "net", "proceeds", "value", "subtotal", "consideration"],
            "notes": ["notes", "description", "memo", "comment", "details", "reference"],
        }

        keys = [k.lower().strip() for k in sample_row.keys()]
        mapping = {}

        for canonical, patterns in COLUMN_PATTERNS.items():
            for pattern in patterns:
                matches = [k for k in keys if pattern in k or k in pattern]
                if matches:
                    # Find original casing
                    original_keys = list(sample_row.keys())
                    for orig in original_keys:
                        if orig.lower().strip() == matches[0]:
                            mapping[canonical] = orig
                            break
                    break

        return mapping

    def _normalize_row(self, row: dict, mapping: dict[str, str]) -> Optional[ParsedTransaction]:
        """Normalize a single row to canonical schema."""

        def get(field: str, default=None):
            col = mapping.get(field)
            if col and col in row:
                v = row[col]
                return str(v).strip() if v is not None and str(v).strip() != "" else default
            return default

        # Date
        date_str = get("date")
        if not date_str:
            return None
        txn_date = self._parse_date(date_str)
        if not txn_date:
            return None

        # Type
        type_raw = (get("type") or "BUY").lower().strip()
        txn_type = TYPE_ALIASES.get(type_raw, type_raw.upper())

        # Symbol
        symbol = get("symbol", "")
        if not symbol:
            return None
        symbol = symbol.upper().strip().replace("-USD", "").replace("/USD", "")

        # Numeric fields
        quantity = self._parse_decimal(get("quantity"))
        price = self._parse_decimal(get("price"))
        fees = self._parse_decimal(get("fees")) or ZERO
        net_amount = self._parse_decimal(get("net_amount"))

        currency = (get("currency") or "USD").upper()[:3]
        notes = get("notes")

        # Compute import hash for deduplication
        hash_input = f"{txn_date.date()}|{txn_type}|{symbol}|{quantity}|{price}|{fees}"
        import_hash = hashlib.sha256(hash_input.encode()).hexdigest()

        return ParsedTransaction(
            date=txn_date,
            transaction_type=txn_type,
            symbol=symbol,
            quantity=quantity,
            price=price,
            fees=fees,
            currency=currency,
            net_amount=net_amount,
            notes=notes,
            raw_row=row,
            import_hash=import_hash,
        )

    async def _process_transactions(
        self,
        normalized: list[ParsedTransaction],
        account_id: str,
        user_id: str,
        source: str,
    ) -> ImportResult:
        """Deduplicate and insert transactions into the database."""
        imported = 0
        duplicates = 0
        errors = 0
        error_details = []
        imported_ids = []

        # Fetch account to validate
        account_result = await self.db.execute(
            select(Account).where(Account.id == account_id, Account.user_id == user_id)
        )
        account = account_result.scalar_one_or_none()
        if not account:
            return ImportResult(len(normalized), 0, 0, 1, ["Account not found"], [])

        for parsed in normalized:
            try:
                # Check for duplicate via import_hash
                existing = await self.db.execute(
                    select(Transaction).where(Transaction.import_hash == parsed.import_hash)
                )
                if existing.scalar_one_or_none():
                    duplicates += 1
                    continue

                # Resolve or create asset
                asset_id = await self._resolve_asset(parsed.symbol)

                # Compute net amount if not provided
                net_amount = parsed.net_amount
                if net_amount is None and parsed.quantity and parsed.price:
                    qty = abs(parsed.quantity)
                    net_amount = qty * parsed.price
                    if parsed.transaction_type == "SELL":
                        net_amount = net_amount - parsed.fees
                    else:
                        net_amount = -(net_amount + parsed.fees)

                txn = Transaction(
                    account_id=account_id,
                    user_id=user_id,
                    asset_id=asset_id,
                    transaction_type=parsed.transaction_type,
                    quantity=parsed.quantity,
                    price_per_unit=parsed.price,
                    fees=parsed.fees,
                    net_amount=net_amount,
                    currency=parsed.currency,
                    transacted_at=parsed.date,
                    source=source,
                    import_hash=parsed.import_hash,
                    notes=parsed.notes,
                    raw_data=parsed.raw_row,
                )
                self.db.add(txn)
                await self.db.flush()
                imported_ids.append(txn.id)
                imported += 1

            except Exception as e:
                errors += 1
                error_details.append(f"Row error: {e}")
                logger.error(f"Import error for {parsed.symbol}: {e}")

        await self.db.commit()

        return ImportResult(
            total_rows=len(normalized),
            imported=imported,
            duplicates=duplicates,
            errors=errors,
            error_details=error_details,
            transactions=imported_ids,
        )

    async def _resolve_asset(self, symbol: str) -> Optional[str]:
        """Look up or create an asset record."""
        result = await self.db.execute(
            select(Asset).where(Asset.symbol == symbol)
        )
        asset = result.scalar_one_or_none()

        if not asset:
            # Infer asset class from symbol
            CRYPTO_SYMBOLS = {"BTC", "ETH", "SOL", "USDT", "USDC", "BNB", "XRP", "ADA", "MATIC", "LINK", "DOT", "AVAX"}
            asset_class = "CRYPTO" if symbol in CRYPTO_SYMBOLS else "EQUITY"

            asset = Asset(
                symbol=symbol,
                name=symbol,
                asset_class=asset_class,
                currency="USD",
            )
            self.db.add(asset)
            await self.db.flush()

        return asset.id

    @staticmethod
    def _parse_date(value: str) -> Optional[datetime]:
        """Try multiple date formats."""
        formats = [
            "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y",
            "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ",
            "%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S",
            "%d-%m-%Y", "%b %d, %Y", "%B %d, %Y",
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(value.split(".")[0].strip(), fmt)
                if dt.tzinfo is None:
                    from datetime import timezone
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue
        return None

    @staticmethod
    def _parse_decimal(value: Optional[str]) -> Optional[Decimal]:
        if not value:
            return None
        # Remove currency symbols, commas, parentheses (negative)
        cleaned = value.replace(",", "").replace("$", "").replace("£", "").replace("€", "").strip()
        is_negative = cleaned.startswith("(") and cleaned.endswith(")")
        cleaned = cleaned.strip("()")
        try:
            d = Decimal(cleaned)
            return -d if is_negative else d
        except InvalidOperation:
            return None
