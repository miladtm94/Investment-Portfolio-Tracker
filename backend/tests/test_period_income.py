import asyncio
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from routers.portfolio import _amount_to_aud, _period_dates, _period_income


class FakeFX:
    @staticmethod
    def _normalize_currency(code):
        return code.upper()

    async def get_rate_on_date(self, from_currency, to_currency="AUD", on_date=None):
        if from_currency == to_currency:
            return Decimal("1")
        if from_currency == "USD" and to_currency == "AUD":
            return Decimal("1.5")
        raise AssertionError(f"Unexpected FX pair {from_currency}/{to_currency}")

    async def close(self):
        return None


def income_txn(**overrides):
    values = {
        "asset_id": "asset-1",
        "net_amount_aud": None,
        "net_amount": None,
        "net_amount_usd": None,
        "gross_amount": None,
        "tax_withheld": None,
        "quantity": None,
        "dividend_per_share": None,
        "price_per_unit": None,
        "currency": "AUD",
        "fx_rate_to_aud": None,
        "transacted_at": datetime(2026, 4, 21, 2, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class PeriodIncomeTests(unittest.TestCase):
    def test_amount_to_aud_supports_aud_only_and_gross_only_imports(self):
        fx = FakeFX()
        aud_only = income_txn(net_amount_aud=Decimal("-25.50"))
        gross_only = income_txn(gross_amount=Decimal("120"), tax_withheld=Decimal("20"))

        self.assertEqual(asyncio.run(_amount_to_aud(aud_only, fx)), Decimal("25.50"))
        self.assertEqual(asyncio.run(_amount_to_aud(gross_only, fx)), Decimal("100"))

    def test_period_income_sums_ledger_directly_and_keeps_assetless_income_in_total(self):
        rows = [
            income_txn(net_amount_aud=Decimal("25.50")),
            income_txn(asset_id=None, net_amount=Decimal("10"), currency="USD", fx_rate_to_aud=Decimal("1.5")),
        ]

        class Result:
            class Scalars:
                def all(self):
                    return rows

            def scalars(self):
                return self.Scalars()

        class DB:
            async def execute(self, _query):
                return Result()

        with patch("routers.portfolio.FXService", FakeFX):
            total, by_asset = asyncio.run(_period_income(
                "user",
                ["account"],
                datetime(2026, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 6, 30, 23, 59, tzinfo=timezone.utc),
                "AUD",
                DB(),
            ))

        self.assertEqual(total, 40.50)
        self.assertEqual(by_asset, {"asset-1": 25.50})

    def test_custom_period_includes_the_entire_end_date(self):
        class Result:
            def scalar(self):
                return datetime(2025, 1, 1, tzinfo=timezone.utc)

        class DB:
            async def execute(self, _query):
                return Result()

        start, end = asyncio.run(_period_dates(
            "CUSTOM", "user", ["account"], DB(), "2026-04-01", "2026-04-21"
        ))

        self.assertEqual(start, datetime(2026, 4, 1, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2026, 4, 21, 23, 59, 59, 999999, tzinfo=timezone.utc))
