"""
FX Rate Service — AUD-centric.

Fetches historical and spot exchange rates with AUD as the primary
reporting currency. Sources:
  1. RBA (Reserve Bank of Australia) — authoritative for ATO purposes
  2. Yahoo Finance — fallback for dates / pairs RBA does not cover
  3. Redis cache — prevents repeated API calls

The ATO requires taxpayers to use a "reasonable" FX rate at the date
of each CGT event. RBA daily rates are explicitly accepted by the ATO.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from shared.cache import cache_get, cache_set

logger = logging.getLogger(__name__)

# RBA publishes daily exchange rates for AUD against major currencies.
# We normalise everything to AUD as the base (1 AUD = X foreign).
RBA_SERIES_ID = {
    "USD": "FXRUSD",
    "EUR": "FXREUR",
    "GBP": "FXRGBP",
    "JPY": "FXRJPY",
    "CNY": "FXRCNY",
    "CAD": "FXRCAD",
    "HKD": "FXRHKD",
    "SGD": "FXRSGD",
    "NZD": "FXRNZD",
}


class FXService:
    """
    Exchange rate service with AUD as the reporting base.
    All rates returned as: 1 AUD = X <foreign currency>.
    To convert foreign → AUD: aud_amount = foreign_amount / rate.
    """

    def __init__(self):
        self._http = httpx.AsyncClient(timeout=15.0)
        # In-memory cache for rates fetched this session
        self._session_cache: dict[str, float] = {}

    async def get_rate_on_date(
        self,
        from_currency: str,
        to_currency: str = "AUD",
        on_date: Optional[datetime] = None,
    ) -> Decimal:
        """
        Get the exchange rate for a currency pair on a specific date.
        Returns: how many `to_currency` units equal 1 `from_currency`.

        For ATO compliance: use the RBA rate on the date of the CGT event.
        """
        if on_date is None:
            on_date = datetime.now(timezone.utc)

        from_c = from_currency.upper()
        to_c = to_currency.upper()

        # Trivial case
        if from_c == to_c:
            return Decimal("1.0")

        date_str = on_date.strftime("%Y-%m-%d")
        cache_key = f"fx:{from_c}:{to_c}:{date_str}"

        cached = await cache_get(cache_key)
        if cached is not None:
            return Decimal(str(cached))

        rate = await self._fetch_rate(from_c, to_c, on_date)
        if rate:
            ttl = 86400 if on_date.date() < datetime.now(timezone.utc).date() else 3600
            await cache_set(cache_key, float(rate), ttl=ttl)
            return rate

        # Hard fallback: return 1.0 and log loudly so the user knows
        logger.error(f"Could not fetch FX rate {from_c}/{to_c} for {date_str}. Using 1.0 — CHECK THIS.")
        return Decimal("1.0")

    async def get_aud_rate(self, foreign_currency: str, on_date: Optional[datetime] = None) -> Decimal:
        """
        Convenience: how many AUD does 1 unit of foreign_currency cost?
        e.g. get_aud_rate("USD") → ~1.55 (1 USD = 1.55 AUD)
        """
        if foreign_currency.upper() == "AUD":
            return Decimal("1.0")
        # get_rate_on_date("USD", "AUD") returns AUD per 1 USD
        return await self.get_rate_on_date(foreign_currency, "AUD", on_date)

    async def convert_to_aud(
        self,
        amount: Decimal,
        from_currency: str,
        on_date: Optional[datetime] = None,
    ) -> tuple[Decimal, Decimal]:
        """
        Convert an amount to AUD.
        Returns: (aud_amount, fx_rate_used)
        fx_rate_used = AUD per 1 unit of from_currency
        """
        if from_currency.upper() == "AUD":
            return amount, Decimal("1.0")

        rate = await self.get_aud_rate(from_currency, on_date)
        aud_amount = (amount * rate).quantize(Decimal("0.01"))
        return aud_amount, rate

    # ─── Internal fetching ────────────────────────────────────────────────

    async def _fetch_rate(
        self, from_c: str, to_c: str, on_date: datetime
    ) -> Optional[Decimal]:
        """Try RBA first, then Yahoo Finance."""

        # RBA publishes AUD/XXX rates.  Both from and to must involve AUD.
        if to_c == "AUD" and from_c in RBA_SERIES_ID:
            rate = await self._rba_rate(from_c, on_date)
            if rate:
                return rate

        if from_c == "AUD" and to_c in RBA_SERIES_ID:
            rate = await self._rba_rate(to_c, on_date)
            if rate:
                return Decimal("1.0") / rate

        # Cross-rate via USD
        if from_c != "AUD" and to_c != "AUD":
            from_aud = await self.get_aud_rate(from_c, on_date)
            to_aud = await self.get_aud_rate(to_c, on_date)
            if from_aud and to_aud and to_aud != Decimal("0"):
                return (from_aud / to_aud).quantize(Decimal("0.000001"))

        # Yahoo Finance fallback
        return await self._yahoo_rate(from_c, to_c, on_date)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
    async def _rba_rate(self, foreign_currency: str, on_date: datetime) -> Optional[Decimal]:
        """
        Fetch RBA daily exchange rate.
        RBA publishes: 1 AUD = X foreign.
        We return AUD units per 1 foreign = 1 / rba_published_rate.
        """
        # RBA statistical tables API (JSON version)
        try:
            params = {
                "series_id": RBA_SERIES_ID[foreign_currency],
                "start_date": (on_date - timedelta(days=7)).strftime("%Y-%m-%d"),
                "end_date": on_date.strftime("%Y-%m-%d"),
            }
            resp = await self._http.get(
                "https://api.rba.gov.au/statistics/chart-data",
                params=params,
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                series = data.get("series", [{}])[0].get("data", [])
                if series:
                    # Most recent value ≤ on_date
                    aud_per_foreign_inv = float(series[-1].get("value", 0))
                    if aud_per_foreign_inv > 0:
                        # RBA publishes AUD/foreign (1 AUD = X foreign)
                        # We want foreign/AUD, then invert for AUD/foreign
                        # Actually: 1 AUD = aud_per_foreign_inv foreign
                        # So: 1 foreign = 1/aud_per_foreign_inv AUD
                        return Decimal(str(1.0 / aud_per_foreign_inv))
        except Exception as e:
            logger.debug(f"RBA API error for {foreign_currency}: {e}")

        return None

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=3))
    async def _yahoo_rate(self, from_c: str, to_c: str, on_date: datetime) -> Optional[Decimal]:
        """Fetch exchange rate from Yahoo Finance."""
        try:
            pair = f"{from_c}{to_c}=X"
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{pair}"
            start = int((on_date - timedelta(days=5)).timestamp())
            end = int((on_date + timedelta(days=1)).timestamp())
            headers = {"User-Agent": "Mozilla/5.0"}
            resp = await self._http.get(
                url, headers=headers,
                params={"interval": "1d", "period1": start, "period2": end}
            )
            resp.raise_for_status()
            data = resp.json()
            result = data["chart"]["result"][0]
            closes = result["indicators"]["quote"][0]["close"]
            closes = [c for c in closes if c is not None]
            if closes:
                return Decimal(str(closes[-1]))
        except Exception as e:
            logger.debug(f"Yahoo FX error {from_c}/{to_c}: {e}")
        return None

    async def close(self):
        await self._http.aclose()


# ─── Helper for batch FX enrichment ──────────────────────────────────────────

async def enrich_transaction_with_aud(
    transaction_currency: str,
    quantity: Optional[Decimal],
    price_per_unit: Optional[Decimal],
    net_amount: Optional[Decimal],
    on_date: datetime,
    fx_svc: Optional[FXService] = None,
) -> dict:
    """
    Given a transaction in any currency, compute the AUD equivalents.
    Returns dict with: fx_rate_to_aud, net_amount_aud, price_per_unit_aud
    """
    svc = fx_svc or FXService()
    try:
        if transaction_currency.upper() == "AUD":
            return {
                "fx_rate_to_aud": Decimal("1.0"),
                "net_amount_aud": net_amount,
                "price_per_unit_aud": price_per_unit,
            }

        rate = await svc.get_aud_rate(transaction_currency, on_date)
        return {
            "fx_rate_to_aud": rate,
            "net_amount_aud": (net_amount * rate).quantize(Decimal("0.01")) if net_amount else None,
            "price_per_unit_aud": (price_per_unit * rate).quantize(Decimal("0.000001")) if price_per_unit else None,
        }
    finally:
        if not fx_svc:
            await svc.close()
