"""
Broker & Exchange Sync Service.

Connects to Plaid (traditional brokers), Kraken, Coinbase, and Binance
to automatically import trades and balances.
"""
from __future__ import annotations

import hashlib
import hmac
import asyncio
import logging
import time
import urllib.parse
import xml.etree.ElementTree as ET
from base64 import b64decode, b64encode
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from config import get_settings
from shared.models import Account, ApiCredential, Asset, Transaction
from shared.cache import cache_invalidate_user

logger = logging.getLogger(__name__)
settings = get_settings()

ZERO = Decimal("0")


class SyncService:
    """Orchestrates account synchronization across all providers."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.http = httpx.AsyncClient(timeout=30.0)

    async def sync_account(self, account_id: str, user_id: str) -> dict:
        """Sync a single account and return summary."""
        account_result = await self.db.execute(
            select(Account).where(Account.id == account_id, Account.user_id == user_id)
        )
        account = account_result.scalar_one_or_none()
        if not account:
            return {"error": "Account not found"}

        # Update sync status
        account.sync_status = "SYNCING"
        await self.db.commit()

        try:
            cred_result = await self.db.execute(
                select(ApiCredential).where(
                    ApiCredential.account_id == account_id,
                    ApiCredential.is_active == True,
                )
            )
            credential = cred_result.scalar_one_or_none()

            if not credential:
                return {"error": "No credentials found for account"}

            provider = credential.provider.upper()
            if provider == "KRAKEN":
                result = await KrakenConnector(self.db, self.http).sync(account, credential, user_id)
            elif provider == "COINBASE":
                result = await CoinbaseConnector(self.db, self.http).sync(account, credential, user_id)
            elif provider == "BINANCE":
                result = await BinanceConnector(self.db, self.http).sync(account, credential, user_id)
            elif provider == "PLAID":
                result = await PlaidConnector(self.db, self.http).sync(account, credential, user_id)
            elif provider in {"IBKR", "INTERACTIVE_BROKERS"}:
                result = await IBKRFlexConnector(self.db, self.http).sync(account, credential, user_id)
            else:
                result = {"error": f"Unsupported provider: {provider}"}

            account.sync_status = "SYNCED"
            account.last_synced_at = datetime.now(timezone.utc)
            await self.db.commit()

            await cache_invalidate_user(user_id)
            return result

        except Exception as e:
            account.sync_status = "ERROR"
            await self.db.commit()
            logger.error(f"Sync failed for account {account_id}: {e}")
            return {"error": str(e)}

    async def close(self):
        await self.http.aclose()


class KrakenConnector:
    """Kraken REST API connector."""
    BASE_URL = "https://api.kraken.com"

    def __init__(self, db: AsyncSession, http: httpx.AsyncClient):
        self.db = db
        self.http = http

    async def sync(self, account: Account, credential: ApiCredential, user_id: str) -> dict:
        api_key = self._decrypt(credential.encrypted_api_key)
        api_secret = self._decrypt(credential.encrypted_api_secret)

        imported = 0
        errors = []

        # Fetch trade history — track which base symbol each trade imported
        trades, trade_err = await self._fetch_trades(api_key, api_secret)
        if trade_err:
            errors.append(trade_err)
        # Map trade_id → base symbol imported from /TradesHistory
        trade_base_symbols: dict[str, str] = {}
        for trade_id, trade in trades:
            pair = trade.get("pair", "")
            base_sym, _ = self._parse_pair(pair)
            trade_base_symbols[trade_id] = base_sym
            txn = await self._normalize_trade(trade, trade_id, account.id, user_id)
            if txn:
                imported += 1

        # Fetch ledger entries (deposits, withdrawals, staking, trade quote-side)
        ledger, ledger_err = await self._fetch_ledger(api_key, api_secret)
        if ledger_err:
            errors.append(ledger_err)
        for ledger_id, entry in ledger:
            txn = await self._normalize_ledger_entry(entry, ledger_id, trade_base_symbols, account.id, user_id)
            if txn:
                imported += 1

        await self.db.commit()

        result: dict = {"imported": imported, "provider": "kraken"}
        if errors and imported == 0:
            result["error"] = "; ".join(errors)
        return result

    async def _fetch_trades(self, api_key: str, api_secret: str) -> tuple[list[tuple[str, dict]], Optional[str]]:
        """Fetch all pages from /TradesHistory. Returns list of (trade_id, trade_data)."""
        try:
            all_trades: list[tuple[str, dict]] = []
            offset = 0
            while True:
                data = await self._private_request(
                    "/0/private/TradesHistory", {"ofs": offset}, api_key, api_secret
                )
                trades = data.get("result", {}).get("trades", {})
                if not trades:
                    break
                all_trades.extend(trades.items())  # preserve trade IDs as keys
                count = data.get("result", {}).get("count", 0)
                offset += len(trades)
                if offset >= count:
                    break
                import asyncio
                await asyncio.sleep(1)
            logger.info(f"Kraken: fetched {len(all_trades)} trades (paginated)")
            return all_trades, None
        except Exception as e:
            logger.error(f"Kraken trades fetch error: {e}")
            return [], str(e)

    async def _fetch_ledger(self, api_key: str, api_secret: str) -> tuple[list[tuple[str, dict]], Optional[str]]:
        """Fetch all pages from /Ledgers. Returns list of (ledger_id, entry_data)."""
        try:
            all_entries: list[tuple[str, dict]] = []
            offset = 0
            while True:
                data = await self._private_request(
                    "/0/private/Ledgers", {"ofs": offset}, api_key, api_secret
                )
                entries = data.get("result", {}).get("ledger", {})
                if not entries:
                    break
                all_entries.extend(entries.items())  # preserve ledger IDs as keys
                count = data.get("result", {}).get("count", 0)
                offset += len(entries)
                if offset >= count:
                    break
                import asyncio
                await asyncio.sleep(1)
            logger.info(f"Kraken: fetched {len(all_entries)} ledger entries (paginated)")
            return all_entries, None
        except Exception as e:
            logger.error(f"Kraken ledger fetch error: {e}")
            return [], str(e)

    async def _private_request(self, path: str, data: dict, api_key: str, api_secret: str) -> dict:
        """Sign and execute a Kraken private API request."""
        nonce = str(int(time.time() * 1000))
        data["nonce"] = nonce

        post_data = urllib.parse.urlencode(data)
        encoded = (nonce + post_data).encode()
        message = path.encode() + hashlib.sha256(encoded).digest()

        mac = hmac.new(b64decode(api_secret), message, hashlib.sha512)
        sig = b64encode(mac.digest()).decode()

        headers = {
            "API-Key": api_key,
            "API-Sign": sig,
            "Content-Type": "application/x-www-form-urlencoded",
        }

        resp = await self.http.post(f"{self.BASE_URL}{path}", data=data, headers=headers)
        resp.raise_for_status()
        result = resp.json()
        if result.get("error"):
            raise Exception(f"Kraken API error: {result['error']}")
        return result

    async def _normalize_trade(self, trade: dict, trade_id: str, account_id: str, user_id: str) -> Optional[Transaction]:
        """Normalize a Kraken trade to canonical transaction."""
        try:
            pair = trade.get("pair", "")
            symbol, quote_currency = self._parse_pair(pair)

            if not symbol or symbol == quote_currency or symbol in KrakenConnector.FIAT_SYMBOLS:
                # Skip fiat trades (e.g., EURUSD) — stablecoins are kept
                return None

            txn_type = "BUY" if trade.get("type") == "buy" else "SELL"
            quantity = Decimal(str(trade.get("vol", 0)))
            price = Decimal(str(trade.get("price", 0)))
            fees = Decimal(str(trade.get("fee", 0)))
            cost = Decimal(str(trade.get("cost", 0)))
            time_val = trade.get("time", 0)
            txn_date = datetime.fromtimestamp(float(time_val), tz=timezone.utc)

            external_id = trade.get("ordertxid", trade_id)
            import_hash = hashlib.sha256(f"kraken|trade|{trade_id}|{txn_type}|{symbol}".encode()).hexdigest()

            # Check duplicate
            existing = await self.db.execute(
                select(Transaction).where(Transaction.import_hash == import_hash)
            )
            if existing.scalar_one_or_none():
                return None

            asset_id = await self._resolve_asset(symbol)

            # Use Kraken's reported cost for net_amount (more accurate than qty * price)
            if txn_type == "SELL":
                net_amount = cost - fees
            else:
                net_amount = -(cost + fees)

            txn = Transaction(
                account_id=account_id,
                user_id=user_id,
                asset_id=asset_id,
                transaction_type=txn_type,
                quantity=quantity,
                price_per_unit=price,
                fees=fees,
                net_amount=net_amount,
                currency=quote_currency,
                transacted_at=txn_date,
                external_id=external_id,
                import_hash=import_hash,
                source="KRAKEN_API",
                raw_data=trade,
            )
            self.db.add(txn)
            return txn
        except Exception as e:
            logger.warning(f"Failed to normalize Kraken trade: {e}")
            return None

    async def _normalize_ledger_entry(
        self, entry: dict, ledger_id: str, trade_base_symbols: dict[str, str],
        account_id: str, user_id: str,
    ) -> Optional[Transaction]:
        """Normalize a Kraken ledger entry (deposit, withdrawal, staking, trade quote-side)."""
        ledger_type = entry.get("type", "").lower()

        try:
            asset_code = entry.get("asset", "")
            symbol = self._normalize_asset(asset_code)

            # Skip fiat currency ledger entries
            if symbol in KrakenConnector.FIAT_SYMBOLS:
                return None

            amount = Decimal(str(entry.get("amount", 0)))
            if amount == ZERO:
                return None

            is_stablecoin = symbol in KrakenConnector.STABLECOIN_SYMBOLS

            # Map ledger types to transaction types
            if ledger_type == "staking":
                txn_type = "STAKE_REWARD"
            elif ledger_type == "deposit":
                txn_type = "TRANSFER_IN"
            elif ledger_type == "withdrawal":
                txn_type = "TRANSFER_OUT"
            elif ledger_type == "transfer":
                # Internal Kraken transfers (spot↔staking, spot↔futures).
                # These don't change total holdings — skip them.
                return None
            elif ledger_type == "funding":
                txn_type = "TRANSFER_IN" if amount > ZERO else "TRANSFER_OUT"
            elif ledger_type == "spend":
                # Kraken Pay / on-chain spend
                txn_type = "TRANSFER_OUT"
            elif ledger_type == "receive":
                # Kraken Pay / on-chain receive
                txn_type = "TRANSFER_IN"
            elif ledger_type == "trade":
                ref_id = entry.get("refid", "")
                base_sym = trade_base_symbols.get(ref_id)
                if base_sym and base_sym == symbol:
                    # This is the base asset side — already imported via /TradesHistory
                    return None
                if not is_stablecoin and base_sym:
                    # Non-stablecoin and trade exists in /TradesHistory — skip
                    return None
                txn_type = "BUY" if amount > ZERO else "SELL"
            else:
                logger.debug(f"Skipping Kraken ledger type '{ledger_type}' for {symbol}: amount={amount}")
                return None

            fee = Decimal(str(entry.get("fee", 0)))
            time_val = entry.get("time", 0)
            txn_date = datetime.fromtimestamp(float(time_val), tz=timezone.utc)
            ref_id = entry.get("refid", "")

            # Use ledger_id (unique per entry) in import_hash to avoid collisions
            import_hash = hashlib.sha256(f"kraken|ledger|{ledger_id}".encode()).hexdigest()
            existing = await self.db.execute(
                select(Transaction).where(Transaction.import_hash == import_hash)
            )
            if existing.scalar_one_or_none():
                return None

            price_per_unit = Decimal("1.0") if is_stablecoin else None

            # Kraken's `amount` is gross; `fee` is deducted separately.
            # For inflows: net received = amount - fee
            # For outflows: net spent = |amount| + fee
            if amount > ZERO:
                net_quantity = amount - fee
            else:
                net_quantity = abs(amount) + fee

            asset_id = await self._resolve_asset(symbol)
            txn = Transaction(
                account_id=account_id,
                user_id=user_id,
                asset_id=asset_id,
                transaction_type=txn_type,
                quantity=net_quantity,
                price_per_unit=price_per_unit,
                fees=fee,
                net_amount=amount,
                currency="USD",
                transacted_at=txn_date,
                external_id=ref_id,
                import_hash=import_hash,
                source="KRAKEN_API",
                raw_data=entry,
            )
            self.db.add(txn)
            return txn
        except Exception as e:
            logger.warning(f"Failed to normalize Kraken ledger: {e}")
            return None

    async def _resolve_asset(self, symbol: str) -> Optional[str]:
        result = await self.db.execute(select(Asset).where(Asset.symbol == symbol))
        asset = result.scalar_one_or_none()
        if not asset:
            asset = Asset(symbol=symbol, name=symbol, asset_class="CRYPTO", currency="USD")
            self.db.add(asset)
            await self.db.flush()
        elif asset.asset_class != "CRYPTO":
            # Fix misclassified crypto assets (e.g., BTC/ETH created as EQUITY by CSV import)
            asset.asset_class = "CRYPTO"
            await self.db.flush()
        return asset.id

    # Kraken uses non-standard asset codes
    ASSET_MAP = {
        "XXBT": "BTC", "XBT": "BTC", "XETH": "ETH", "XLTC": "LTC",
        "XXRP": "XRP", "XXLM": "XLM", "XDAO": "DAO", "XXDG": "DOGE",
        "ZUSD": "USD", "ZEUR": "EUR", "ZGBP": "GBP", "ZAUD": "AUD",
        "ZCAD": "CAD", "ZJPY": "JPY", "ZCHF": "CHF",
        # Staked variants → canonical symbol
        "SOL03": "SOL", "SOL.S": "SOL", "ETH2": "ETH", "ETH.S": "ETH",
        "DOT.S": "DOT", "DOT28": "DOT", "ADA.S": "ADA",
        "ATOM.S": "ATOM", "MATIC.S": "MATIC", "XRP.S": "XRP",
        "FLOW.S": "FLOW", "KAVA.S": "KAVA", "MINA.S": "MINA",
        # Flexible staking variants
        "SOL.F": "SOL", "ETH.F": "ETH", "DOT.F": "DOT", "ADA.F": "ADA",
        "ATOM.F": "ATOM", "MATIC.F": "MATIC", "XRP.F": "XRP",
    }

    # True fiat currencies to skip in ledger entries
    FIAT_SYMBOLS = {"USD", "EUR", "GBP", "AUD", "CAD", "JPY", "CHF"}
    # Stablecoins — treated as crypto assets, NOT skipped
    STABLECOIN_SYMBOLS = {"USDC", "USDT", "DAI", "BUSD"}

    # Quote currencies Kraken appends to pairs (order matters: longest first)
    QUOTE_SUFFIXES = ["USDC", "USDT", "ZUSD", "ZEUR", "ZAUD", "ZGBP", "USD", "EUR", "AUD", "GBP"]

    @classmethod
    def _normalize_asset(cls, raw: str) -> str:
        """Normalize a single Kraken asset code: XXBT→BTC, SOL03→SOL, ETH.S→ETH."""
        raw = raw.upper().strip()
        # Check direct mapping first (includes staked variants like SOL03, ETH.S)
        if raw in cls.ASSET_MAP:
            return cls.ASSET_MAP[raw]
        # Try with .S suffix stripped
        base = raw.split(".")[0]
        if base in cls.ASSET_MAP:
            return cls.ASSET_MAP[base]
        # Try stripping trailing digits for staked variants (SOL03→SOL, DOT28→DOT)
        import re
        base_no_digits = re.sub(r'\d+$', '', raw)
        if base_no_digits and base_no_digits in cls.ASSET_MAP:
            return cls.ASSET_MAP[base_no_digits]
        return base_no_digits or base

    @classmethod
    def _parse_pair(cls, pair: str) -> tuple[str, str]:
        """
        Parse a Kraken trading pair into (base_symbol, quote_currency).
        Examples: ETHUSDC → (ETH, USD), XBTUSDC → (BTC, USD), SOLUSDC → (SOL, USD),
                  XETHZUSD → (ETH, USD), USDTZUSD → (USDT, USD)
        """
        pair = pair.upper().strip()

        # Try known quote suffixes
        for suffix in cls.QUOTE_SUFFIXES:
            if pair.endswith(suffix) and len(pair) > len(suffix):
                base_raw = pair[:-len(suffix)]
                base = cls._normalize_asset(base_raw)
                quote = cls._normalize_asset(suffix)
                # Normalize stablecoin quotes to USD
                if quote in ("USDC", "USDT"):
                    quote = "USD"
                return base, quote

        # Fallback: return as-is
        return cls._normalize_asset(pair), "USD"

    @staticmethod
    def _decrypt(encrypted: Optional[bytes]) -> str:
        """Placeholder: in production, use KMS envelope decryption."""
        if not encrypted:
            return ""
        return encrypted.decode("utf-8", errors="replace")


class CoinbaseConnector:
    """Coinbase Advanced Trade API connector."""
    BASE_URL = "https://api.coinbase.com"

    def __init__(self, db: AsyncSession, http: httpx.AsyncClient):
        self.db = db
        self.http = http

    async def sync(self, account: Account, credential: ApiCredential, user_id: str) -> dict:
        api_key = self._decrypt(credential.encrypted_api_key)
        api_secret = self._decrypt(credential.encrypted_api_secret)

        imported = 0
        fills = await self._fetch_fills(api_key, api_secret)
        for fill in fills:
            txn = await self._normalize_fill(fill, account.id, user_id)
            if txn:
                imported += 1

        await self.db.commit()
        return {"imported": imported, "provider": "coinbase"}

    async def _fetch_fills(self, api_key: str, api_secret: str) -> list[dict]:
        """Fetch order fills from Coinbase Advanced Trade."""
        try:
            headers = self._sign_request("GET", "/api/v3/brokerage/orders/historical/fills", api_key, api_secret)
            resp = await self.http.get(
                f"{self.BASE_URL}/api/v3/brokerage/orders/historical/fills",
                headers=headers,
                params={"limit": 1000},
            )
            resp.raise_for_status()
            return resp.json().get("fills", [])
        except Exception as e:
            logger.error(f"Coinbase fills fetch error: {e}")
            return []

    async def _normalize_fill(self, fill: dict, account_id: str, user_id: str) -> Optional[Transaction]:
        try:
            side = fill.get("side", "").upper()
            txn_type = "BUY" if side == "BUY" else "SELL"
            product_id = fill.get("product_id", "")
            symbol = product_id.split("-")[0]
            quantity = Decimal(str(fill.get("size", 0)))
            price = Decimal(str(fill.get("price", 0)))
            commission = Decimal(str(fill.get("commission", 0)))
            trade_time = fill.get("trade_time", "")
            txn_date = datetime.fromisoformat(trade_time.rstrip("Z") + "+00:00") if trade_time else datetime.now(timezone.utc)
            trade_id = fill.get("trade_id", "")

            import_hash = hashlib.sha256(f"coinbase|{trade_id}".encode()).hexdigest()
            existing = await self.db.execute(
                select(Transaction).where(Transaction.import_hash == import_hash)
            )
            if existing.scalar_one_or_none():
                return None

            asset_id = await self._resolve_asset(symbol)
            txn = Transaction(
                account_id=account_id, user_id=user_id, asset_id=asset_id,
                transaction_type=txn_type, quantity=quantity, price_per_unit=price,
                fees=commission, currency="USD", transacted_at=txn_date,
                external_id=trade_id, import_hash=import_hash, source="COINBASE", raw_data=fill,
            )
            self.db.add(txn)
            return txn
        except Exception as e:
            logger.warning(f"Coinbase fill normalize error: {e}")
            return None

    async def _resolve_asset(self, symbol: str) -> Optional[str]:
        result = await self.db.execute(select(Asset).where(Asset.symbol == symbol))
        asset = result.scalar_one_or_none()
        if not asset:
            asset = Asset(symbol=symbol, name=symbol, asset_class="CRYPTO", currency="USD")
            self.db.add(asset)
            await self.db.flush()
        return asset.id

    def _sign_request(self, method: str, path: str, api_key: str, api_secret: str) -> dict:
        """Sign Coinbase Advanced Trade API request."""
        timestamp = str(int(time.time()))
        message = timestamp + method + path
        signature = hmac.new(api_secret.encode(), message.encode(), hashlib.sha256).hexdigest()
        return {
            "CB-ACCESS-KEY": api_key,
            "CB-ACCESS-SIGN": signature,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
        }

    @staticmethod
    def _decrypt(encrypted: Optional[bytes]) -> str:
        if not encrypted:
            return ""
        return encrypted.decode("utf-8", errors="replace")


class BinanceConnector:
    """Binance REST API connector."""
    BASE_URL = "https://api.binance.com"

    def __init__(self, db: AsyncSession, http: httpx.AsyncClient):
        self.db = db
        self.http = http

    async def sync(self, account: Account, credential: ApiCredential, user_id: str) -> dict:
        api_key = self._decrypt(credential.encrypted_api_key)
        api_secret = self._decrypt(credential.encrypted_api_secret)

        imported = 0
        # Fetch recent trades for common pairs
        common_pairs = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
        for pair in common_pairs:
            trades = await self._fetch_my_trades(pair, api_key, api_secret)
            for trade in trades:
                txn = await self._normalize_trade(trade, account.id, user_id, pair)
                if txn:
                    imported += 1

        await self.db.commit()
        return {"imported": imported, "provider": "binance"}

    async def _fetch_my_trades(self, symbol: str, api_key: str, api_secret: str) -> list[dict]:
        try:
            params = {"symbol": symbol, "limit": 1000, "timestamp": int(time.time() * 1000)}
            query = urllib.parse.urlencode(params)
            signature = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
            params["signature"] = signature
            headers = {"X-MBX-APIKEY": api_key}
            resp = await self.http.get(f"{self.BASE_URL}/api/v3/myTrades", params=params, headers=headers)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning(f"Binance trades fetch error for {symbol}: {e}")
            return []

    async def _normalize_trade(self, trade: dict, account_id: str, user_id: str, pair: str) -> Optional[Transaction]:
        try:
            symbol = pair.replace("USDT", "").replace("BTC", "")
            if not symbol:
                symbol = pair[:3]
            is_buyer = trade.get("isBuyer", False)
            txn_type = "BUY" if is_buyer else "SELL"
            quantity = Decimal(str(trade.get("qty", 0)))
            price = Decimal(str(trade.get("price", 0)))
            commission = Decimal(str(trade.get("commission", 0)))
            trade_id = str(trade.get("id", ""))
            trade_time = trade.get("time", 0)
            txn_date = datetime.fromtimestamp(trade_time / 1000, tz=timezone.utc)

            import_hash = hashlib.sha256(f"binance|{trade_id}|{pair}".encode()).hexdigest()
            existing = await self.db.execute(
                select(Transaction).where(Transaction.import_hash == import_hash)
            )
            if existing.scalar_one_or_none():
                return None

            asset_id = await self._resolve_asset(symbol)
            txn = Transaction(
                account_id=account_id, user_id=user_id, asset_id=asset_id,
                transaction_type=txn_type, quantity=quantity, price_per_unit=price,
                fees=commission, currency="USDT", transacted_at=txn_date,
                external_id=trade_id, import_hash=import_hash, source="BINANCE", raw_data=trade,
            )
            self.db.add(txn)
            return txn
        except Exception as e:
            logger.warning(f"Binance trade normalize error: {e}")
            return None

    async def _resolve_asset(self, symbol: str) -> Optional[str]:
        result = await self.db.execute(select(Asset).where(Asset.symbol == symbol))
        asset = result.scalar_one_or_none()
        if not asset:
            asset = Asset(symbol=symbol, name=symbol, asset_class="CRYPTO", currency="USD")
            self.db.add(asset)
            await self.db.flush()
        return asset.id

    @staticmethod
    def _decrypt(encrypted: Optional[bytes]) -> str:
        if not encrypted:
            return ""
        return encrypted.decode("utf-8", errors="replace")


class IBKRFlexConnector:
    """Interactive Brokers Flex Web Service connector."""
    BASE_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"

    def __init__(self, db: AsyncSession, http: httpx.AsyncClient):
        self.db = db
        self.http = http

    async def sync(self, account: Account, credential: ApiCredential, user_id: str) -> dict:
        flex_token = self._decrypt(credential.encrypted_access_token)
        query_id = self._decrypt(credential.encrypted_api_key)

        if not flex_token or not query_id:
            return {"imported": 0, "provider": "ibkr", "error": "Missing IBKR Flex token or query ID"}

        xml_text = await self._fetch_statement(flex_token, query_id)
        root = ET.fromstring(xml_text)

        imported = 0
        trade_count = 0
        cash_count = 0

        trades = self._elements(root, "Trade")
        cash_transactions = self._elements(root, "CashTransaction")
        dividend_accruals = self._elements(root, "ChangeInDividendAccrual")

        for trade in trades:
            trade_count += 1
            txn = await self._normalize_trade(trade.attrib, account.id, user_id)
            if txn:
                imported += 1

        for cash_txn in cash_transactions:
            cash_count += 1
            txn = await self._normalize_cash_transaction(cash_txn.attrib, account.id, user_id)
            if txn:
                imported += 1

        dividend_count = 0
        for dividend in dividend_accruals:
            dividend_count += 1
            txn = await self._normalize_dividend_accrual(dividend.attrib, account.id, user_id)
            if txn:
                imported += 1

        await self.db.commit()
        result: dict = {
            "imported": imported,
            "provider": "ibkr",
            "trades_found": trade_count,
            "cash_transactions_found": cash_count,
            "dividend_accruals_found": dividend_count,
        }
        if trade_count == 0 and cash_count == 0 and dividend_count == 0:
            result["error"] = (
                "IBKR returned a Flex report, but it did not contain Trades, Cash Transactions, "
                "or Change in Dividend Accruals rows. Edit the Activity Flex Query to include those sections, "
                "set delivery format to XML, save it, then sync again."
            )
        return result

    async def _fetch_statement(self, flex_token: str, query_id: str) -> str:
        """Generate and retrieve an IBKR Flex statement XML document."""
        request_id = await self._send_request(flex_token, query_id)

        # IBKR often needs a short processing window before the statement is ready.
        for delay in (2, 3, 5, 8, 13):
            await asyncio.sleep(delay)
            statement = await self._get_statement(flex_token, request_id)
            if statement:
                return statement

        raise Exception("IBKR Flex statement was not ready. Try again in a minute.")

    async def _send_request(self, flex_token: str, query_id: str) -> str:
        params = {"t": flex_token, "q": query_id, "v": "3"}
        resp = await self.http.get(f"{self.BASE_URL}/SendRequest", params=params, headers=self._headers())
        resp.raise_for_status()
        root = ET.fromstring(resp.text)

        status = self._find_text(root, "Status")
        if status and status.lower() != "success":
            code = self._find_text(root, "ErrorCode")
            message = self._find_text(root, "ErrorMessage") or "IBKR Flex request failed"
            raise Exception(f"IBKR Flex error {code or ''}: {message}".strip())

        reference_code = self._find_text(root, "ReferenceCode")
        if not reference_code:
            raise Exception("IBKR Flex did not return a reference code")
        return reference_code

    async def _get_statement(self, flex_token: str, reference_code: str) -> Optional[str]:
        params = {"t": flex_token, "q": reference_code, "v": "3"}
        resp = await self.http.get(f"{self.BASE_URL}/GetStatement", params=params, headers=self._headers(), follow_redirects=True)
        resp.raise_for_status()

        root = ET.fromstring(resp.text)
        status = self._find_text(root, "Status")
        if status and status.lower() != "success":
            message = self._find_text(root, "ErrorMessage") or ""
            code = self._find_text(root, "ErrorCode") or ""
            if "not ready" in message.lower() or code in {"1019", "1021"}:
                return None
            raise Exception(f"IBKR Flex error {code}: {message}".strip())

        if (
            self._elements(root, "Trade")
            or self._elements(root, "CashTransaction")
            or self._elements(root, "ChangeInDividendAccrual")
            or self._local_name(root.tag) == "FlexQueryResponse"
        ):
            return resp.text
        return None

    async def _normalize_trade(self, trade: dict, account_id: str, user_id: str) -> Optional[Transaction]:
        try:
            symbol = self._clean_symbol(self._value(trade, "symbol", "Symbol", "underlyingSymbol", "UnderlyingSymbol"))
            if not symbol:
                return None

            quantity = abs(self._decimal(self._value(trade, "quantity", "Quantity")))
            if quantity == ZERO:
                return None

            buy_sell = self._value(trade, "buySell", "Buy/Sell", "side", "Side").upper()
            signed_qty = self._decimal(self._value(trade, "quantity", "Quantity"))
            txn_type = "SELL" if buy_sell.startswith("S") or signed_qty < ZERO else "BUY"

            price = self._decimal(self._value(trade, "tradePrice", "TradePrice", "price", "Price"))
            fees = abs(self._decimal(self._value(trade, "ibCommission", "IBCommission", "commission", "Commission")))
            net_cash = self._maybe_decimal(self._value(trade, "netCash", "NetCash"))
            currency = self._value(trade, "currency", "Currency", "currencyPrimary", "CurrencyPrimary", "ibCommissionCurrency", "IBCommissionCurrency") or "USD"
            txn_date = self._parse_ibkr_date(self._value(trade, "dateTime", "DateTime", "tradeDate", "TradeDate", "reportDate", "ReportDate"))
            transaction_id = self._value(trade, "transactionID", "TransactionID", "tradeID", "TradeID", "ibExecID", "IBExecID")

            import_hash = hashlib.sha256(
                f"ibkr|trade|{transaction_id}|{symbol}|{txn_type}|{txn_date.isoformat()}|{quantity}|{price}|{net_cash}".encode()
            ).hexdigest()
            existing = await self.db.execute(select(Transaction).where(Transaction.import_hash == import_hash))
            if existing.scalar_one_or_none():
                return None

            asset_id = await self._resolve_asset(symbol, currency, trade)
            if net_cash is None:
                gross = quantity * price
                net_cash = gross - fees if txn_type == "SELL" else -(gross + fees)

            txn = Transaction(
                account_id=account_id,
                user_id=user_id,
                asset_id=asset_id,
                transaction_type=txn_type,
                quantity=quantity,
                price_per_unit=price,
                fees=fees,
                net_amount=net_cash,
                currency=currency,
                transacted_at=txn_date,
                external_id=transaction_id or None,
                import_hash=import_hash,
                source="IBKR_API",
                raw_data=trade,
                notes=self._value(trade, "description", "Description"),
            )
            self.db.add(txn)
            return txn
        except Exception as e:
            logger.warning(f"IBKR trade normalize error: {e}")
            return None

    async def _normalize_cash_transaction(self, cash_txn: dict, account_id: str, user_id: str) -> Optional[Transaction]:
        try:
            raw_type = self._value(cash_txn, "type", "Type", "transactionType", "TransactionType", "activityCode", "ActivityCode").lower()
            description = self._value(cash_txn, "description", "Description")
            symbol = self._clean_symbol(self._value(cash_txn, "symbol", "Symbol", "underlyingSymbol", "UnderlyingSymbol"))
            amount = self._decimal(self._value(cash_txn, "amount", "Amount", "netAmount", "NetAmount"))
            if amount == ZERO:
                return None

            txn_type = self._map_cash_type(raw_type, description)
            if not txn_type:
                return None

            currency = self._value(cash_txn, "currency", "Currency", "currencyPrimary", "CurrencyPrimary") or "USD"
            txn_date = self._parse_ibkr_date(self._value(cash_txn, "dateTime", "DateTime", "date", "Date", "reportDate", "ReportDate"))
            transaction_id = self._value(cash_txn, "transactionID", "TransactionID", "transactionId", "TransactionId")

            import_hash = hashlib.sha256(
                f"ibkr|cash|{transaction_id}|{txn_type}|{symbol}|{txn_date.isoformat()}|{amount}|{description}".encode()
            ).hexdigest()
            existing = await self.db.execute(select(Transaction).where(Transaction.import_hash == import_hash))
            if existing.scalar_one_or_none():
                return None

            asset_id = await self._resolve_asset(symbol, currency, cash_txn) if symbol else None
            quantity = self._maybe_decimal(self._value(cash_txn, "quantity", "Quantity"))
            dividend_per_share = None
            if txn_type in {"DIVIDEND", "DISTRIBUTION"} and quantity and quantity != ZERO:
                dividend_per_share = abs(amount / quantity)

            txn = Transaction(
                account_id=account_id,
                user_id=user_id,
                asset_id=asset_id,
                transaction_type=txn_type,
                quantity=abs(quantity) if quantity is not None else None,
                price_per_unit=None,
                gross_amount=abs(amount),
                fees=abs(amount) if txn_type == "FEE" else ZERO,
                net_amount=amount,
                currency=currency,
                transacted_at=txn_date,
                tax_withheld=abs(amount) if txn_type == "FEE" and "tax" in description.lower() else None,
                dividend_per_share=dividend_per_share,
                external_id=transaction_id or None,
                import_hash=import_hash,
                source="IBKR_API",
                raw_data=cash_txn,
                notes=description,
            )
            self.db.add(txn)
            return txn
        except Exception as e:
            logger.warning(f"IBKR cash transaction normalize error: {e}")
            return None

    async def _normalize_dividend_accrual(self, dividend: dict, account_id: str, user_id: str) -> Optional[Transaction]:
        try:
            code = self._value(dividend, "code", "Code").upper()
            if code and code not in {"PO", "RE"}:
                return None

            symbol = self._clean_symbol(self._value(dividend, "symbol", "Symbol", "underlyingSymbol", "UnderlyingSymbol"))
            if not symbol:
                return None

            amount = (
                self._maybe_decimal(self._value(dividend, "netAmount", "NetAmount"))
                or self._maybe_decimal(self._value(dividend, "grossAmount", "GrossAmount"))
                or ZERO
            )
            if amount == ZERO:
                return None

            currency = self._value(dividend, "currency", "Currency", "currencyPrimary", "CurrencyPrimary") or "USD"
            txn_date = self._parse_ibkr_date(
                self._value(dividend, "payDate", "PayDate", "exDate", "ExDate", "date", "Date", "reportDate", "ReportDate")
            )
            quantity = self._maybe_decimal(self._value(dividend, "quantity", "Quantity"))
            tax = abs(self._decimal(self._value(dividend, "tax", "Tax")))
            transaction_id = self._value(dividend, "transactionID", "TransactionID", "transactionId", "TransactionId")
            gross_rate = self._maybe_decimal(self._value(dividend, "grossRate", "GrossRate"))

            import_hash = hashlib.sha256(
                f"ibkr|dividend_accrual|{transaction_id}|{symbol}|{txn_date.isoformat()}|{amount}|{code}".encode()
            ).hexdigest()
            existing = await self.db.execute(select(Transaction).where(Transaction.import_hash == import_hash))
            if existing.scalar_one_or_none():
                return None

            asset_id = await self._resolve_asset(symbol, currency, dividend)
            txn = Transaction(
                account_id=account_id,
                user_id=user_id,
                asset_id=asset_id,
                transaction_type="DIVIDEND",
                quantity=abs(quantity) if quantity is not None else None,
                gross_amount=abs(amount) + tax,
                fees=ZERO,
                net_amount=amount,
                currency=currency,
                transacted_at=txn_date,
                tax_withheld=tax or None,
                dividend_per_share=gross_rate,
                external_id=transaction_id or None,
                import_hash=import_hash,
                source="IBKR_API",
                raw_data=dividend,
                notes=f"Dividend accrual {code}".strip(),
            )
            self.db.add(txn)
            return txn
        except Exception as e:
            logger.warning(f"IBKR dividend accrual normalize error: {e}")
            return None

    async def _resolve_asset(self, symbol: str, currency: str, data: dict) -> Optional[str]:
        result = await self.db.execute(select(Asset).where(Asset.symbol == symbol))
        asset = result.scalar_one_or_none()
        if not asset:
            asset_category = self._value(data, "assetCategory", "AssetCategory", "AssetClass").upper()
            asset_class = "ETF" if asset_category == "ETF" else "EQUITY"
            asset = Asset(
                symbol=symbol,
                name=self._value(data, "description", "Description") or symbol,
                asset_class=asset_class,
                currency=currency,
                isin=self._value(data, "isin", "ISIN") or None,
            )
            self.db.add(asset)
            await self.db.flush()
        return asset.id

    @staticmethod
    def _find_text(root: ET.Element, tag: str) -> Optional[str]:
        for node in root.iter():
            if IBKRFlexConnector._local_name(node.tag) == tag:
                return node.text.strip() if node.text else None
        return None

    @staticmethod
    def _elements(root: ET.Element, tag: str) -> list[ET.Element]:
        return [node for node in root.iter() if IBKRFlexConnector._local_name(node.tag) == tag]

    @staticmethod
    def _local_name(tag: str) -> str:
        return tag.rsplit("}", 1)[-1] if "}" in tag else tag

    @staticmethod
    def _headers() -> dict:
        return {"User-Agent": "Investment-Portfolio-Tracker/1.0"}

    @staticmethod
    def _value(data: dict, *keys: str) -> str:
        lowered = {str(k).lower(): v for k, v in data.items()}
        for key in keys:
            if key in data and data[key] is not None:
                return str(data[key]).strip()
            value = lowered.get(key.lower())
            if value is not None:
                return str(value).strip()
        return ""

    @staticmethod
    def _clean_symbol(symbol: str) -> str:
        return (symbol or "").strip().upper().split(" ")[0]

    @staticmethod
    def _decimal(value: Optional[str]) -> Decimal:
        if value in (None, ""):
            return ZERO
        cleaned = str(value).replace(",", "").replace("$", "").strip()
        if cleaned.startswith("(") and cleaned.endswith(")"):
            cleaned = "-" + cleaned[1:-1]
        try:
            return Decimal(cleaned)
        except Exception:
            return ZERO

    @classmethod
    def _maybe_decimal(cls, value: Optional[str]) -> Optional[Decimal]:
        if value in (None, ""):
            return None
        return cls._decimal(value)

    @staticmethod
    def _map_cash_type(raw_type: str, description: str) -> Optional[str]:
        text = f"{raw_type} {description}".lower()
        if "dividend" in text or raw_type in {"dividends", "payment in lieu of dividends"}:
            return "DIVIDEND"
        if "withholding" in text or "withheld" in text:
            return "FEE"
        if "interest" in text:
            return "INTEREST"
        if "fee" in text or "commission" in text:
            return "FEE"
        if "deposit" in text:
            return "DEPOSIT"
        if "withdrawal" in text:
            return "WITHDRAWAL"
        return None

    @staticmethod
    def _parse_ibkr_date(value: Optional[str]) -> datetime:
        if not value:
            return datetime.now(timezone.utc)
        cleaned = value.strip().replace(";", " ")
        for fmt in (
            "%Y%m%d",
            "%Y%m%d %H:%M:%S",
            "%Y-%m-%d",
            "%Y-%m-%d %H:%M:%S",
            "%m/%d/%Y",
            "%m/%d/%Y %H:%M:%S",
        ):
            try:
                return datetime.strptime(cleaned.split(".")[0], fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        try:
            dt = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return datetime.now(timezone.utc)

    @staticmethod
    def _decrypt(encrypted: Optional[bytes]) -> str:
        if not encrypted:
            return ""
        return encrypted.decode("utf-8", errors="replace")


class PlaidConnector:
    """Plaid investment transactions connector."""
    BASE_URL = "https://production.plaid.com"

    def __init__(self, db: AsyncSession, http: httpx.AsyncClient):
        self.db = db
        self.http = http

    async def sync(self, account: Account, credential: ApiCredential, user_id: str) -> dict:
        access_token = self._decrypt(credential.encrypted_access_token)

        transactions = await self._fetch_investment_transactions(access_token)
        imported = 0
        for txn_data in transactions:
            txn = await self._normalize_transaction(txn_data, account.id, user_id)
            if txn:
                imported += 1

        await self.db.commit()
        return {"imported": imported, "provider": "plaid"}

    async def _fetch_investment_transactions(self, access_token: str) -> list[dict]:
        """Fetch investment transactions from Plaid."""
        try:
            payload = {
                "client_id": settings.plaid_client_id.get_secret_value(),
                "secret": settings.plaid_secret.get_secret_value(),
                "access_token": access_token,
                "start_date": (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d"),
                "end_date": datetime.now().strftime("%Y-%m-%d"),
            }
            base = f"https://{settings.plaid_env}.plaid.com"
            resp = await self.http.post(
                f"{base}/investments/transactions/get",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            return resp.json().get("investment_transactions", [])
        except Exception as e:
            logger.error(f"Plaid investment transactions error: {e}")
            return []

    async def _normalize_transaction(self, txn_data: dict, account_id: str, user_id: str) -> Optional[Transaction]:
        try:
            plaid_type = txn_data.get("type", "").lower()
            type_map = {
                "buy": "BUY", "sell": "SELL", "dividend": "DIVIDEND",
                "transfer": "TRANSFER_IN", "fee": "FEE",
            }
            txn_type = type_map.get(plaid_type, "BUY")
            ticker = txn_data.get("security", {}).get("ticker_symbol", "")
            if not ticker:
                return None

            quantity = Decimal(str(txn_data.get("quantity", 0)))
            price = Decimal(str(txn_data.get("price", 0)))
            fees = Decimal(str(txn_data.get("fees", 0)))
            amount = Decimal(str(txn_data.get("amount", 0)))
            date_str = txn_data.get("date", "")
            txn_date = datetime.fromisoformat(date_str) if date_str else datetime.now(timezone.utc)
            if txn_date.tzinfo is None:
                txn_date = txn_date.replace(tzinfo=timezone.utc)
            txn_id = txn_data.get("investment_transaction_id", "")

            import_hash = hashlib.sha256(f"plaid|{txn_id}".encode()).hexdigest()
            existing = await self.db.execute(
                select(Transaction).where(Transaction.import_hash == import_hash)
            )
            if existing.scalar_one_or_none():
                return None

            asset_id = await self._resolve_asset(ticker, txn_data.get("security", {}))
            txn = Transaction(
                account_id=account_id, user_id=user_id, asset_id=asset_id,
                transaction_type=txn_type, quantity=quantity, price_per_unit=price,
                fees=fees, net_amount=amount, currency="USD", transacted_at=txn_date,
                external_id=txn_id, import_hash=import_hash, source="PLAID", raw_data=txn_data,
            )
            self.db.add(txn)
            return txn
        except Exception as e:
            logger.warning(f"Plaid transaction normalize error: {e}")
            return None

    async def _resolve_asset(self, symbol: str, security_data: dict) -> Optional[str]:
        result = await self.db.execute(select(Asset).where(Asset.symbol == symbol))
        asset = result.scalar_one_or_none()
        if not asset:
            asset = Asset(
                symbol=symbol,
                name=security_data.get("name", symbol),
                asset_class="EQUITY",
                isin=security_data.get("isin"),
                cusip=security_data.get("cusip"),
                currency="USD",
            )
            self.db.add(asset)
            await self.db.flush()
        return asset.id

    @staticmethod
    def _decrypt(encrypted: Optional[bytes]) -> str:
        if not encrypted:
            return ""
        return encrypted.decode("utf-8", errors="replace")
