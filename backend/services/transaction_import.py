"""
Transaction Import Engine.

Parses CSV/Excel/JSON exports from brokers and exchanges,
auto-detects broker format, normalizes to canonical schema,
and deduplicates against existing records.

Supported brokers:
  - CommSec (ASX)           — AUD trades, "B"/"S" type codes
  - CMC Invest (ASX)        — AUD trades, "Buy"/"Sell"
  - Stake (US equities)     — USD trades with FX column
  - Moomoo (US equities)    — USD trades with commission
  - Interactive Brokers      — Flex Query CSV export (wide format)
  - Kraken (crypto)         — "pair" column with txid
  - Coinbase (crypto)       — "Spot Price" column
  - Robinhood / Schwab / Fidelity — standard US broker format
  - Generic CSV             — auto-mapped via fuzzy column matching
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from shared.models import Account, Asset, Transaction
from services.fx_service import FXService

logger = logging.getLogger(__name__)

ZERO = Decimal("0")


# ─── Type Aliases ────────────────────────────────────────────────────────────

TYPE_ALIASES = {
    # Buys
    "buy": "BUY", "bought": "BUY", "purchase": "BUY", "b": "BUY",
    "exchtrade": "BUY",  # IBKR — determined by quantity sign
    # Sells
    "sell": "SELL", "sold": "SELL", "s": "SELL",
    # Dividends & Distributions
    "dividend": "DIVIDEND", "div": "DIVIDEND", "dividends reinvested": "DIVIDEND",
    "dividends": "DIVIDEND", "cash dividend": "DIVIDEND",
    "payment in lieu of dividends": "DIVIDEND", "payment in lieu": "DIVIDEND",
    "distribution": "DISTRIBUTION", "dist": "DISTRIBUTION",
    "managed fund distribution": "DISTRIBUTION", "trust distribution": "DISTRIBUTION",
    "capital gains distribution": "DISTRIBUTION", "return of capital": "DISTRIBUTION",
    # Interest
    "interest": "INTEREST", "bond interest": "INTEREST", "credit interest": "INTEREST",
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


# ─── Broker Detection ────────────────────────────────────────────────────────

@dataclass
class BrokerProfile:
    """Configuration for a specific broker's CSV format."""
    name: str
    default_currency: str
    column_map: dict[str, str]   # {canonical_field: exact_column_name}
    type_field: str = "type"
    symbol_cleanup: Optional[str] = None  # regex to strip from symbols
    quantity_signed: bool = False  # IBKR uses negative qty for sells
    date_format: Optional[str] = None


# Broker signatures: {frozenset_of_lowercase_columns: BrokerProfile}
BROKER_SIGNATURES: list[tuple[set[str], BrokerProfile]] = [
    # CommSec (variant 1) — has "Security Code" and "Brokerage ($)"
    (
        {"security code", "brokerage ($)"},
        BrokerProfile(
            name="CommSec",
            default_currency="AUD",
            column_map={
                "date": "Date",
                "type": "Type",
                "symbol": "Security Code",
                "quantity": "Quantity",
                "price": "Price ($)",
                "fees": "Brokerage ($)",
                "net_amount": "Net Proceeds ($)",
                "notes": "Security Description",
            },
            date_format="%d/%m/%Y",
        ),
    ),

    # CommSec (variant 2) — has "Security" and "Brokerage (inc GST.)"
    (
        {"security", "brokerage (inc gst.)"},
        BrokerProfile(
            name="CommSec",
            default_currency="AUD",
            column_map={
                "date": "Trade Date",
                "type": "Buy/ Sell",
                "symbol": "Security",
                "quantity": "Units",
                "price": "Average Price ($)",
                "fees": "Brokerage (inc GST.)",
                "net_amount": "Net Proceeds ($)",
                "notes": "Confirmation Number",
            },
            date_format="%d/%m/%Y",
        ),
    ),

    # CMC Invest — has "AsxCode" and "Brokerage" (real export format)
    (
        {"asxcode", "brokerage"},
        BrokerProfile(
            name="CMC Invest",
            default_currency="AUD",
            column_map={
                "date": "Trade Date",
                "type": "Order Type",
                "symbol": "AsxCode",
                "quantity": "Quantity",
                "price": "Price",
                "fees": "Brokerage",
                "net_amount": "Consideration",
                "notes": "Account Name",
            },
            date_format="%Y-%m-%d",
        ),
    ),

    # IBKR Flex Query — has "TradePrice" and "IBCommission"
    (
        {"tradeprice", "ibcommission"},
        BrokerProfile(
            name="Interactive Brokers",
            default_currency="USD",
            column_map={
                "date": "TradeDate",
                "type": "TransactionType",
                "symbol": "Symbol",
                "quantity": "Quantity",
                "price": "TradePrice",
                "fees": "IBCommission",
                "net_amount": "NetCash",
                "currency": "CurrencyPrimary",
                "notes": "Description",
            },
            quantity_signed=True,  # negative qty = sell
            date_format=None,  # Auto-detect: supports %Y%m%d, %m/%d/%Y, etc.
        ),
    ),

    # Stake — has "Side" and "Brokerage" and "FX Rate"
    (
        {"side", "fx rate"},
        BrokerProfile(
            name="Stake",
            default_currency="USD",
            column_map={
                "date": "Trade Date",
                "type": "Side",
                "symbol": "Symbol",
                "quantity": "Quantity",
                "price": "Price",
                "fees": "Brokerage",
                "currency": "Currency",
                "net_amount": "Total (USD)",
                "notes": "Market",
            },
        ),
    ),

    # Moomoo — Tax Documents export: has "Instrument Code", "Market Code", "Brokerage Currency"
    (
        {"instrument code", "market code", "brokerage currency"},
        BrokerProfile(
            name="Moomoo",
            default_currency="USD",
            column_map={
                "date": "Trade Date",
                "type": "Transaction Type",
                "symbol": "Instrument Code",
                "quantity": "Quantity",
                "price": "Price",
                "fees": "Brokerage",
                "currency": "Brokerage Currency",
                "notes": "Comments",
            },
            date_format="%Y-%m-%d",
        ),
    ),

    # Kraken — has "pair" and "txid" and "vol"
    (
        {"pair", "txid", "vol"},
        BrokerProfile(
            name="Kraken",
            default_currency="USD",
            column_map={
                "date": "time",
                "type": "type",
                "symbol": "pair",
                "quantity": "vol",
                "price": "price",
                "fees": "fee",
                "net_amount": "cost",
            },
            symbol_cleanup=r"^X{1,2}|Z?USD$|ZUSD$",  # XXBTZUSD -> BTC
        ),
    ),

    # Coinbase — has "Spot Price at Transaction"
    (
        {"spot price at transaction"},
        BrokerProfile(
            name="Coinbase",
            default_currency="USD",
            column_map={
                "date": "Timestamp",
                "type": "Transaction Type",
                "symbol": "Asset",
                "quantity": "Quantity Transacted",
                "price": "Spot Price at Transaction",
                "fees": "Fees and/or Spread",
                "net_amount": "Total (inclusive of fees and/or spread)",
                "currency": "Spot Price Currency",
                "notes": "Notes",
            },
        ),
    ),
]

# Kraken symbol map: exchange symbol -> canonical symbol
KRAKEN_SYMBOLS = {
    "XXBT": "BTC", "XETH": "ETH", "XXRP": "XRP", "XLTC": "LTC",
    "XXLM": "XLM", "XDAO": "DAO", "XXDG": "DOGE",
    "SOL": "SOL", "LINK": "LINK", "DOT": "DOT", "ADA": "ADA",
    "AVAX": "AVAX", "MATIC": "MATIC", "UNI": "UNI", "ATOM": "ATOM",
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
    broker: str = "Unknown"


@dataclass
class ImportResult:
    """Result of an import operation."""
    total_rows: int
    imported: int
    duplicates: int
    errors: int
    error_details: list[str]
    transactions: list[str]  # IDs of imported transactions
    broker_detected: str = "Unknown"


class TransactionImporter:
    """
    Multi-format transaction importer with automatic broker detection.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self._fx = FXService()

    async def import_file(
        self,
        file_content: bytes,
        file_name: str,
        account_id: str,
        user_id: str,
        source: str = "CSV_IMPORT",
    ) -> ImportResult:
        ext = file_name.lower().split(".")[-1]

        if ext in ("csv", "txt"):
            rows = self._parse_csv(file_content)
        elif ext in ("xlsx", "xls"):
            rows = self._parse_excel(file_content)
        elif ext == "json":
            rows = self._parse_json(file_content)
        else:
            return ImportResult(0, 0, 0, 1, [f"Unsupported file format: {ext}"], [])

        if not rows:
            return ImportResult(0, 0, 0, 1, ["No data rows found in file"], [])

        # Detect broker from column headers
        broker = self._detect_broker(rows[0])
        logger.info(f"Detected broker: {broker.name} ({len(rows)} rows)")

        # Normalize rows using broker-specific mapping
        normalized = self._normalize_rows(rows, broker)

        try:
            result = await self._process_transactions(normalized, account_id, user_id, source)
            result.broker_detected = broker.name
            return result
        finally:
            await self._fx.close()

    # ─── File Parsers ────────────────────────────────────────────────────

    def _parse_csv(self, content: bytes) -> list[dict]:
        """Parse CSV with encoding detection, metadata skipping, dialect sniffing."""
        for encoding in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                text = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = content.decode("latin-1", errors="replace")

        lines = text.splitlines()

        # Skip metadata/preamble: find first line with 3+ comma-separated tokens
        # where the first token is not purely numeric
        header_idx = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            for delim in (",", "\t", ";"):
                parts = [p.strip().strip('"') for p in stripped.split(delim)]
                if len(parts) >= 3 and not parts[0].lstrip("-").replace(".", "").isdigit():
                    header_idx = i
                    break
            else:
                continue
            break

        clean_text = "\n".join(lines[header_idx:])

        try:
            dialect = csv.Sniffer().sniff(clean_text[:8192], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel

        reader = csv.DictReader(io.StringIO(clean_text), dialect=dialect)
        return [dict(row) for row in reader if any(v and str(v).strip() for v in row.values())]

    def _parse_excel(self, content: bytes) -> list[dict]:
        df = pd.read_excel(io.BytesIO(content), engine="openpyxl")
        df = df.dropna(how="all")
        return df.to_dict(orient="records")

    def _parse_json(self, content: bytes) -> list[dict]:
        data = json.loads(content)
        if isinstance(data, list):
            return data
        for key in ("transactions", "trades", "history", "records", "data"):
            if key in data and isinstance(data[key], list):
                return data[key]
        return [data]

    # ─── Broker Detection ────────────────────────────────────────────────

    def _detect_broker(self, sample_row: dict) -> BrokerProfile:
        """Identify broker from column names in the first row."""
        cols_lower = {k.lower().strip() for k in sample_row.keys() if k is not None}

        for signature_cols, profile in BROKER_SIGNATURES:
            if signature_cols.issubset(cols_lower):
                # Verify column_map keys actually exist (case-insensitive)
                return self._resolve_column_casing(profile, sample_row)

        # Fallback: generic fuzzy mapping
        return self._build_generic_profile(sample_row)

    def _resolve_column_casing(self, profile: BrokerProfile, sample_row: dict) -> BrokerProfile:
        """Match profile's expected columns to actual casing in the file."""
        actual_keys = [k for k in sample_row.keys() if k is not None]
        lower_to_actual = {k.lower().strip(): k for k in actual_keys}

        resolved_map = {}
        for canonical, expected_col in profile.column_map.items():
            actual = lower_to_actual.get(expected_col.lower().strip())
            if actual:
                resolved_map[canonical] = actual
            else:
                # Fuzzy fallback for this field
                for actual_key in actual_keys:
                    if expected_col.lower() in actual_key.lower() or actual_key.lower() in expected_col.lower():
                        resolved_map[canonical] = actual_key
                        break

        return BrokerProfile(
            name=profile.name,
            default_currency=profile.default_currency,
            column_map=resolved_map,
            type_field=profile.type_field,
            symbol_cleanup=profile.symbol_cleanup,
            quantity_signed=profile.quantity_signed,
            date_format=profile.date_format,
        )

    def _build_generic_profile(self, sample_row: dict) -> BrokerProfile:
        """Build a generic broker profile using fuzzy column matching."""
        PATTERNS = {
            "date": ["date", "time", "datetime", "trade date", "transaction date", "timestamp", "settled"],
            "type": ["type", "transaction type", "action", "transaction", "side", "order type"],
            "symbol": ["symbol", "ticker", "asset", "coin", "instrument", "security", "stock code"],
            "quantity": ["quantity", "qty", "shares", "units", "size", "filled qty", "vol"],
            "price": ["price", "price per share", "unit price", "fill price", "avg price", "trade price", "spot price"],
            "fees": ["fees", "fee", "commission", "brokerage", "charges", "comm"],
            "currency": ["currency", "ccy", "quote currency", "currency primary"],
            "net_amount": ["net amount", "total", "net", "proceeds", "value", "subtotal", "consideration", "net cash", "cost", "amount", "cash amount"],
            "notes": ["notes", "description", "memo", "comment", "details", "reference", "name"],
        }

        keys = [k for k in sample_row.keys() if k is not None]
        keys_lower = [k.lower().strip() for k in keys]
        mapping = {}
        used_keys = set()

        for canonical, patterns in PATTERNS.items():
            for pattern in patterns:
                for idx, kl in enumerate(keys_lower):
                    if keys[idx] not in used_keys and (pattern == kl or pattern in kl or kl in pattern):
                        # Avoid mapping "amount" to both "quantity" and "net_amount"
                        if canonical == "quantity" and ("net" in kl or "total" in kl or "proceed" in kl):
                            continue
                        mapping[canonical] = keys[idx]
                        used_keys.add(keys[idx])
                        break
                if canonical in mapping:
                    break

        # Guess currency from column names
        currency = "USD"
        for k in keys_lower:
            if "aud" in k or "($)" in k:
                currency = "AUD"
                break

        return BrokerProfile(
            name="Auto-detected",
            default_currency=currency,
            column_map=mapping,
        )

    # ─── Normalization ───────────────────────────────────────────────────

    def _normalize_rows(self, rows: list[dict], broker: BrokerProfile) -> list[ParsedTransaction]:
        normalized = []
        for i, row in enumerate(rows):
            try:
                txn = self._normalize_row(row, broker)
                if txn:
                    normalized.append(txn)
            except Exception as e:
                logger.warning(f"Row {i}: parse error: {e} — row: {row}")
        return normalized

    def _normalize_row(self, row: dict, broker: BrokerProfile) -> Optional[ParsedTransaction]:
        """Normalize a single row using the broker profile."""
        col_map = broker.column_map

        def get(field: str, default=None):
            col = col_map.get(field)
            if col and col in row:
                v = row[col]
                if v is not None and str(v).strip() != "":
                    return str(v).strip()
            return default

        # ── Date ──
        date_str = get("date")
        if not date_str:
            return None

        if broker.date_format:
            txn_date = self._parse_date_with_format(date_str, broker.date_format)
        else:
            txn_date = self._parse_date(date_str)
        if not txn_date:
            return None

        # ── Quantity (parse early — IBKR uses sign for buy/sell) ──
        quantity = self._parse_decimal(get("quantity"))

        # ── Type ──
        type_raw = (get("type") or "BUY").lower().strip()
        txn_type = TYPE_ALIASES.get(type_raw, type_raw.upper())

        # IBKR: negative quantity = sell
        if broker.quantity_signed and quantity is not None:
            if quantity < 0:
                txn_type = "SELL"
                quantity = abs(quantity)
            else:
                txn_type = "BUY"

        # ── Symbol ──
        symbol = get("symbol", "")
        if not symbol:
            return None
        symbol = symbol.upper().strip()

        # Kraken pair cleanup: XXBTZUSD -> BTC
        if broker.name == "Kraken":
            symbol = self._clean_kraken_symbol(symbol)
        else:
            # Generic cleanup
            symbol = symbol.replace("-USD", "").replace("/USD", "").replace(".AX", "")

        if not symbol:
            return None

        # ── Numeric fields ──
        price = self._parse_decimal(get("price"))
        fees = self._parse_decimal(get("fees")) or ZERO
        # IBKR reports commission as negative
        fees = abs(fees)
        net_amount = self._parse_decimal(get("net_amount"))

        # ── Currency ──
        currency = (get("currency") or broker.default_currency).upper()
        # Normalize to 3-char ISO code
        if len(currency) > 3:
            currency = currency[:3]

        # ── Notes ──
        notes = get("notes")

        # Fallback: infer income types from notes if type is ambiguous
        if txn_type not in {
            "BUY", "SELL", "DIVIDEND", "DISTRIBUTION", "INTEREST",
            "TRANSFER_IN", "TRANSFER_OUT", "DEPOSIT", "WITHDRAWAL",
            "STAKE_REWARD", "AIRDROP", "MINING_REWARD", "SWAP", "SPLIT", "FEE",
        }:
            note_lc = (notes or "").lower()
            if "dividend" in note_lc or "distribution" in note_lc:
                txn_type = "DIVIDEND"

        # ── Import hash ──
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
            broker=broker.name,
        )

    # ─── Symbol Cleanup ──────────────────────────────────────────────────

    @staticmethod
    def _clean_kraken_symbol(pair: str) -> str:
        """Convert Kraken pair to canonical symbol: XXBTZUSD -> BTC, XETHZUSD -> ETH."""
        pair = pair.upper()
        # Remove quote currency suffix
        for suffix in ("ZUSD", "USD", "ZEUR", "EUR", "ZAUD", "AUD"):
            if pair.endswith(suffix):
                base = pair[: -len(suffix)]
                return KRAKEN_SYMBOLS.get(base, base.lstrip("X"))
        # If no quote currency found, just return as-is
        return KRAKEN_SYMBOLS.get(pair, pair)

    # ─── Database Operations ─────────────────────────────────────────────

    async def _process_transactions(
        self,
        normalized: list[ParsedTransaction],
        account_id: str,
        user_id: str,
        source: str,
    ) -> ImportResult:
        imported = 0
        duplicates = 0
        errors = 0
        error_details = []
        imported_ids = []

        account_result = await self.db.execute(
            select(Account).where(Account.id == account_id, Account.user_id == user_id)
        )
        account = account_result.scalar_one_or_none()
        if not account:
            return ImportResult(len(normalized), 0, 0, 1, ["Account not found"], [])

        broker_name = normalized[0].broker if normalized else "Unknown"

        for parsed in normalized:
            try:
                existing = await self.db.execute(
                    select(Transaction).where(
                        Transaction.import_hash == parsed.import_hash,
                        Transaction.account_id == account_id,
                    )
                )
                if existing.scalar_one_or_none():
                    duplicates += 1
                    continue

                asset_id = await self._resolve_asset(parsed.symbol, parsed.currency)

                net_amount = parsed.net_amount
                if net_amount is None and parsed.quantity and parsed.price:
                    qty = abs(parsed.quantity)
                    net_amount = qty * parsed.price
                    if parsed.transaction_type == "SELL":
                        net_amount = net_amount - parsed.fees
                    elif parsed.transaction_type in ("DIVIDEND", "DISTRIBUTION", "INTEREST"):
                        # Income events should be positive by default
                        net_amount = net_amount
                    else:
                        net_amount = -(net_amount + parsed.fees)

                # AUD conversion — uses RBA daily rates (ATO-approved)
                fx_rate_aud = await self._fx.get_aud_rate(parsed.currency, parsed.date)
                net_amount_aud = (net_amount * fx_rate_aud).quantize(Decimal("0.01")) if net_amount is not None else None
                price_aud = (parsed.price * fx_rate_aud).quantize(Decimal("0.000001")) if parsed.price is not None else None

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
                    fx_rate_to_aud=fx_rate_aud,
                    net_amount_aud=net_amount_aud,
                    price_per_unit_aud=price_aud,
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
                error_details.append(f"Row error ({parsed.symbol}): {e}")
                logger.error(f"Import error for {parsed.symbol}: {e}")

        await self.db.commit()

        return ImportResult(
            total_rows=len(normalized),
            imported=imported,
            duplicates=duplicates,
            errors=errors,
            error_details=error_details,
            transactions=imported_ids,
            broker_detected=broker_name,
        )

    async def _resolve_asset(self, symbol: str, currency: str = "USD") -> Optional[str]:
        result = await self.db.execute(
            select(Asset).where(Asset.symbol == symbol)
        )
        asset = result.scalar_one_or_none()

        if not asset:
            CRYPTO_SYMBOLS = {
                "BTC", "ETH", "SOL", "USDT", "USDC", "BNB", "XRP", "ADA",
                "MATIC", "LINK", "DOT", "AVAX", "DOGE", "LTC", "UNI", "ATOM",
                "XLM", "ALGO", "FIL", "AAVE", "NEAR", "OP", "ARB",
            }
            asset_class = "CRYPTO" if symbol in CRYPTO_SYMBOLS else "EQUITY"

            asset = Asset(
                symbol=symbol,
                name=symbol,
                asset_class=asset_class,
                currency=currency,
            )
            self.db.add(asset)
            await self.db.flush()

        return asset.id

    # ─── Date Parsing ────────────────────────────────────────────────────

    @staticmethod
    def _parse_date_with_format(value: str, fmt: str) -> Optional[datetime]:
        """Parse date with a known format, then fallback to generic."""
        from datetime import timezone
        try:
            dt = datetime.strptime(value.split(".")[0].strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return TransactionImporter._parse_date(value)

    @staticmethod
    def _parse_date(value: str) -> Optional[datetime]:
        from datetime import timezone
        formats = [
            "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y",
            "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M:%S",
            "%d/%m/%Y %H:%M:%S", "%d-%m-%Y",
            "%Y%m%d",  # IBKR compact
            "%b %d, %Y", "%B %d, %Y",
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(value.split(".")[0].strip(), fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue
        return None

    @staticmethod
    def _parse_decimal(value: Optional[str]) -> Optional[Decimal]:
        if not value:
            return None
        cleaned = value.replace(",", "").replace("$", "").replace("£", "").replace("€", "").strip()
        is_negative = cleaned.startswith("(") and cleaned.endswith(")")
        cleaned = cleaned.strip("()")
        # Handle trailing minus (some brokers)
        if cleaned.endswith("-"):
            cleaned = "-" + cleaned[:-1]
        try:
            d = Decimal(cleaned)
            return -d if is_negative else d
        except InvalidOperation:
            return None
