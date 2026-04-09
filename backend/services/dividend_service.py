"""
Dividend sync service (Polygon US equities only).
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import httpx
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models import Asset, Transaction, User
from services.fx_service import FXService
from services.market_data_service import MarketDataService
from services.portfolio_engine import PortfolioEngine
from config import get_settings

logger = logging.getLogger(__name__)


class DividendService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self._http = httpx.AsyncClient(timeout=20.0)
        self._fx = FXService()
        self._portfolio = PortfolioEngine(db, MarketDataService())

    async def close(self):
        await self._http.aclose()
        await self._fx.close()

    async def sync_us_dividends(
        self,
        user: User,
    ) -> dict:
        """
        Fetch US equity dividends from Polygon and insert as DIVIDEND/DISTRIBUTION
        transactions when the user held shares on ex-dividend date.
        """
        settings = get_settings()
        api_key = settings.polygon_api_key.get_secret_value()
        if not api_key:
            return {"status": "skipped", "reason": "missing_polygon_api_key"}

        # Find US equity assets for this user
        assets_result = await self.db.execute(
            select(Asset)
            .join(Transaction, Transaction.asset_id == Asset.id)
            .where(
                Transaction.user_id == user.id,
                Asset.asset_class == "EQUITY",
                Asset.currency == "USD",
            )
            .distinct()
        )
        assets = assets_result.scalars().all()
        if not assets:
            return {"status": "skipped", "reason": "no_us_equities"}

        inserted = 0
        skipped = 0
        errors: list[str] = []

        state_cache: dict[str, any] = {}
        state_cache_by_account: dict[tuple[str, str], any] = {}

        for asset in assets:
            try:
                # Start from last dividend transaction if present, else first trade date
                last_div_q = await self.db.execute(
                    select(func.max(Transaction.transacted_at)).where(
                        Transaction.user_id == user.id,
                        Transaction.asset_id == asset.id,
                        Transaction.transaction_type.in_(["DIVIDEND", "DISTRIBUTION"]),
                    )
                )
                last_div = last_div_q.scalar_one_or_none()

                first_trade_q = await self.db.execute(
                    select(func.min(Transaction.transacted_at)).where(
                        Transaction.user_id == user.id,
                        Transaction.asset_id == asset.id,
                    )
                )
                first_trade = first_trade_q.scalar_one_or_none()

                start_date = last_div or first_trade
                if not start_date:
                    continue

                dividends = await self._fetch_polygon_dividends(
                    asset.symbol,
                    start_date,
                    api_key,
                )

                for div in dividends:
                    ex_date = div.get("ex_dividend_date")
                    pay_date = div.get("pay_date")
                    cash_amount = div.get("cash_amount")
                    div_type = div.get("dividend_type")

                    if not ex_date or cash_amount is None:
                        skipped += 1
                        continue

                    ex_dt = self._parse_date(ex_date)
                    pay_dt = self._parse_date(pay_date) if pay_date else None
                    if not ex_dt:
                        skipped += 1
                        continue

                    # Use ex-dividend date for eligibility; pay date for txn date if available
                    eligibility_day = ex_dt.strftime("%Y-%m-%d")
                    if eligibility_day not in state_cache:
                        state_cache[eligibility_day] = await self._portfolio._reconstruct_state(
                            user.id, None, ex_dt, user.cost_basis_method
                        )
                    state = state_cache[eligibility_day]

                    # Find relevant accounts for this asset up to ex-date
                    acct_result = await self.db.execute(
                        select(Transaction.account_id)
                        .where(
                            Transaction.user_id == user.id,
                            Transaction.asset_id == asset.id,
                            Transaction.transacted_at <= ex_dt,
                        )
                        .distinct()
                    )
                    account_ids = [r[0] for r in acct_result.all() if r[0]]
                    if not account_ids:
                        skipped += 1
                        continue

                    # If multiple accounts, split by account quantity at ex-date
                    account_quantities: list[tuple[str, Decimal]] = []
                    if len(account_ids) == 1:
                        qty = state.quantity(asset.id)
                        if qty > Decimal("0"):
                            account_quantities.append((account_ids[0], qty))
                    else:
                        for acct_id in account_ids:
                            cache_key = (eligibility_day, acct_id)
                            if cache_key not in state_cache_by_account:
                                state_cache_by_account[cache_key] = await self._portfolio._reconstruct_state(
                                    user.id, [acct_id], ex_dt, user.cost_basis_method
                                )
                            acct_state = state_cache_by_account[cache_key]
                            qty = acct_state.quantity(asset.id)
                            if qty > Decimal("0"):
                                account_quantities.append((acct_id, qty))

                    if not account_quantities:
                        skipped += 1
                        continue

                    txn_type = "DISTRIBUTION" if div_type in ("LT", "ST") else "DIVIDEND"
                    txn_date = pay_dt or ex_dt

                    for acct_id, qty in account_quantities:
                        amount = (qty * Decimal(str(cash_amount))).quantize(Decimal("0.01"))
                        if amount <= 0:
                            skipped += 1
                            continue

                        import_hash = hashlib.sha256(
                            f"polygon-dividend|{user.id}|{acct_id}|{asset.id}|{ex_dt.date()}|{cash_amount}".encode()
                        ).hexdigest()

                        exists = await self.db.execute(
                            select(Transaction).where(Transaction.import_hash == import_hash)
                        )
                        if exists.scalar_one_or_none():
                            skipped += 1
                            continue

                        fx_rate_aud = await self._fx.get_aud_rate("USD", txn_date)
                        net_amount_aud = (amount * fx_rate_aud).quantize(Decimal("0.01"))

                        txn = Transaction(
                            account_id=acct_id,
                            user_id=user.id,
                            asset_id=asset.id,
                            transaction_type=txn_type,
                            quantity=qty,
                            price_per_unit=Decimal(str(cash_amount)),
                            fees=Decimal("0"),
                            net_amount=amount,
                            currency="USD",
                            fx_rate_to_aud=fx_rate_aud,
                            net_amount_aud=net_amount_aud,
                            price_per_unit_aud=(Decimal(str(cash_amount)) * fx_rate_aud).quantize(Decimal("0.000001")),
                            transacted_at=txn_date,
                            source="POLYGON_DIVIDEND",
                            import_hash=import_hash,
                            notes=f"Polygon dividend ({div_type or 'CD'})",
                            raw_data=div,
                        )
                        self.db.add(txn)
                        await self.db.flush()
                        inserted += 1
            except Exception as e:
                logger.warning(f"Dividend sync failed for {asset.symbol}: {e}")
                errors.append(f"{asset.symbol}: {e}")

        await self.db.commit()

        return {
            "status": "completed",
            "inserted": inserted,
            "skipped": skipped,
            "errors": errors,
        }

    async def _fetch_polygon_dividends(
        self,
        ticker: str,
        start_date: datetime,
        api_key: str,
    ) -> list[dict]:
        url = "https://api.polygon.io/v3/reference/dividends"
        params = {
            "ticker": ticker,
            "ex_dividend_date.gte": start_date.strftime("%Y-%m-%d"),
            "limit": 1000,
            "apiKey": api_key,
        }

        results: list[dict] = []
        next_url: Optional[str] = None

        while True:
            if next_url:
                resp = await self._http.get(next_url, params={"apiKey": api_key})
            else:
                resp = await self._http.get(url, params=params)
            resp.raise_for_status()
            payload = resp.json()
            results.extend(payload.get("results", []))
            next_url = payload.get("next_url")
            if not next_url:
                break

        return results

    @staticmethod
    def _parse_date(value: str) -> Optional[datetime]:
        if not value:
            return None
        try:
            dt = datetime.strptime(value, "%Y-%m-%d")
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
