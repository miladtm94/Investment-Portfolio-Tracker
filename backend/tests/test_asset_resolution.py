import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.dialects import postgresql

from shared.assets import get_or_create_asset
from shared.models import Asset


class FakeResult:
    def __init__(self, asset):
        self._asset = asset

    def scalar_one_or_none(self):
        return self._asset


class FakeSession:
    """Records the lookup query and returns a preset asset (or None)."""

    def __init__(self, existing=None):
        self.existing = existing
        self.queries: list[str] = []
        self.added: list[Asset] = []

    async def execute(self, query):
        self.queries.append(str(query.compile(dialect=postgresql.dialect())))
        return FakeResult(self.existing)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass


class AssetResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_equity_lookup_is_scoped_to_currency(self):
        db = FakeSession()
        asset = await get_or_create_asset(db, "CBA", "aud")

        self.assertIn("assets.currency", db.queries[0])
        self.assertEqual(asset.currency, "AUD")
        self.assertEqual(asset.asset_class, "EQUITY")
        self.assertEqual(db.added, [asset])

    async def test_crypto_lookup_ignores_currency_and_is_quoted_in_usd(self):
        db = FakeSession()
        asset = await get_or_create_asset(db, "BTC", "AUD", "CRYPTO")

        self.assertNotIn("assets.currency =", db.queries[0])
        self.assertEqual(asset.currency, "USD")

    async def test_existing_asset_is_reused(self):
        existing = Asset(symbol="CBA", name="CBA", asset_class="EQUITY", currency="AUD")
        db = FakeSession(existing)

        asset = await get_or_create_asset(db, "CBA", "AUD")

        self.assertIs(asset, existing)
        self.assertEqual(db.added, [])

    async def test_optional_fields_are_set_on_create(self):
        db = FakeSession()
        asset = await get_or_create_asset(db, "VTI", "USD", "ETF", name="Vanguard Total", isin=None, cusip="922908769")

        self.assertEqual(asset.name, "Vanguard Total")
        self.assertEqual(asset.cusip, "922908769")
        self.assertIsNone(asset.isin)


if __name__ == "__main__":
    unittest.main()
