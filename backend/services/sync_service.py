"""
Broker & Exchange Sync Service.

Connects to Plaid (traditional brokers), Kraken, Coinbase, and Binance
to automatically import trades and balances.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
import urllib.parse
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
        # Fetch trade history
        trades = await self._fetch_trades(api_key, api_secret)
        for trade in trades:
            txn = await self._normalize_trade(trade, account.id, user_id)
            if txn:
                imported += 1

        # Fetch ledger entries (deposits, withdrawals, staking)
        ledger = await self._fetch_ledger(api_key, api_secret)
        for entry in ledger:
            txn = await self._normalize_ledger_entry(entry, account.id, user_id)
            if txn:
                imported += 1

        await self.db.commit()
        return {"imported": imported, "provider": "kraken"}

    async def _fetch_trades(self, api_key: str, api_secret: str) -> list[dict]:
        """Fetch /TradesHistory endpoint."""
        try:
            data = await self._private_request("/0/private/TradesHistory", {}, api_key, api_secret)
            return list(data.get("result", {}).get("trades", {}).values())
        except Exception as e:
            logger.error(f"Kraken trades fetch error: {e}")
            return []

    async def _fetch_ledger(self, api_key: str, api_secret: str) -> list[dict]:
        """Fetch /Ledgers endpoint."""
        try:
            data = await self._private_request("/0/private/Ledgers", {}, api_key, api_secret)
            return list(data.get("result", {}).get("ledger", {}).values())
        except Exception as e:
            logger.error(f"Kraken ledger fetch error: {e}")
            return []

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

    async def _normalize_trade(self, trade: dict, account_id: str, user_id: str) -> Optional[Transaction]:
        """Normalize a Kraken trade to canonical transaction."""
        try:
            pair = trade.get("pair", "")
            # Extract base symbol (XXBT → BTC, XETH → ETH, etc.)
            symbol = self._normalize_symbol(pair)

            txn_type = "BUY" if trade.get("type") == "buy" else "SELL"
            quantity = Decimal(str(trade.get("vol", 0)))
            price = Decimal(str(trade.get("price", 0)))
            fees = Decimal(str(trade.get("fee", 0)))
            time_val = trade.get("time", 0)
            txn_date = datetime.fromtimestamp(float(time_val), tz=timezone.utc)

            external_id = trade.get("ordertxid", trade.get("txid", ""))
            import_hash = hashlib.sha256(f"kraken|{external_id}|{txn_type}|{symbol}".encode()).hexdigest()

            # Check duplicate
            existing = await self.db.execute(
                select(Transaction).where(Transaction.import_hash == import_hash)
            )
            if existing.scalar_one_or_none():
                return None

            asset_id = await self._resolve_asset(symbol)

            txn = Transaction(
                account_id=account_id,
                user_id=user_id,
                asset_id=asset_id,
                transaction_type=txn_type,
                quantity=quantity,
                price_per_unit=price,
                fees=fees,
                net_amount=quantity * price - fees if txn_type == "SELL" else -(quantity * price + fees),
                currency="USD",
                transacted_at=txn_date,
                external_id=external_id,
                import_hash=import_hash,
                source="KRAKEN",
                raw_data=trade,
            )
            self.db.add(txn)
            return txn
        except Exception as e:
            logger.warning(f"Failed to normalize Kraken trade: {e}")
            return None

    async def _normalize_ledger_entry(self, entry: dict, account_id: str, user_id: str) -> Optional[Transaction]:
        """Normalize a Kraken ledger entry (deposit, withdrawal, staking)."""
        ledger_type = entry.get("type", "").lower()
        type_map = {
            "deposit": "DEPOSIT",
            "withdrawal": "WITHDRAWAL",
            "staking": "STAKE_REWARD",
            "transfer": "TRANSFER_IN",
        }
        txn_type = type_map.get(ledger_type)
        if not txn_type:
            return None

        try:
            asset_code = entry.get("asset", "")
            symbol = self._normalize_symbol(asset_code)
            amount = Decimal(str(entry.get("amount", 0)))
            fee = Decimal(str(entry.get("fee", 0)))
            time_val = entry.get("time", 0)
            txn_date = datetime.fromtimestamp(float(time_val), tz=timezone.utc)
            ref_id = entry.get("refid", "")

            import_hash = hashlib.sha256(f"kraken|ledger|{ref_id}|{txn_type}".encode()).hexdigest()
            existing = await self.db.execute(
                select(Transaction).where(Transaction.import_hash == import_hash)
            )
            if existing.scalar_one_or_none():
                return None

            asset_id = await self._resolve_asset(symbol)
            txn = Transaction(
                account_id=account_id,
                user_id=user_id,
                asset_id=asset_id,
                transaction_type=txn_type,
                quantity=abs(amount),
                fees=fee,
                net_amount=amount,
                currency="USD",
                transacted_at=txn_date,
                external_id=ref_id,
                import_hash=import_hash,
                source="KRAKEN",
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
        return asset.id

    @staticmethod
    def _normalize_symbol(raw: str) -> str:
        """Normalize Kraken asset symbols (XXBT→BTC, XETH→ETH, ZUSD→USD)."""
        mapping = {
            "XXBT": "BTC", "XBT": "BTC", "XETH": "ETH",
            "ZUSD": "USD", "ZEUR": "EUR", "ZGBP": "GBP",
            "XXRP": "XRP", "XLTC": "LTC", "XXLM": "XLM",
        }
        sym = raw.upper().split("/")[0].replace("USD", "")
        return mapping.get(sym, sym) or raw.upper()

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
