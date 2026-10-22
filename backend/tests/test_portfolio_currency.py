import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.portfolio_engine import PortfolioEngine, PortfolioState
from shared.models import Asset, Transaction


class _FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _FakeScalars(self._rows)


class _FakeDb:
    def __init__(self, assets):
        self._assets = assets

    async def execute(self, _query):
        return _FakeResult(self._assets)


class _FakeMarketData:
    def __init__(self, prices=None):
        self._prices = prices or {"BTC": 30000.0}

    async def get_batch_prices(self, _symbols, _symbol_currencies=None):
        return self._prices


class _FakeFXService:
    @staticmethod
    def _normalize_currency(code):
        c = code.upper()
        return "USD" if c in {"USDT", "USDC", "DAI", "BUSD"} else c

    async def get_rate_on_date(self, from_currency, to_currency="AUD", on_date=None):
        from_c = self._normalize_currency(from_currency)
        to_c = self._normalize_currency(to_currency)
        if from_c == to_c:
            return Decimal("1.0")
        if from_c == "USD" and to_c == "AUD":
            return Decimal("1.7")
        if from_c == "AUD" and to_c == "USD":
            return Decimal("0.5882352941")
        raise AssertionError(f"Unexpected FX lookup {from_currency}/{to_currency}")

    async def close(self):
        return None


class PortfolioCurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_crypto_prices_are_usd_and_realized_gain_uses_historical_fx_legs(self):
        asset = Asset(
            id="asset-btc",
            symbol="BTC",
            name="Bitcoin",
            asset_class="CRYPTO",
            currency="AUD",  # Simulates an imported asset record with account/native currency.
        )
        engine = PortfolioEngine(_FakeDb([asset]), _FakeMarketData())
        state = PortfolioState(as_of=datetime(2026, 1, 2, tzinfo=timezone.utc))

        buy = Transaction(
            id="buy-1",
            account_id="acct",
            user_id="user",
            asset_id=asset.id,
            transaction_type="BUY",
            quantity=Decimal("1"),
            price_per_unit=Decimal("10000"),
            fees=Decimal("0"),
            currency="USD",
            fx_rate_to_aud=Decimal("1.5"),
            transacted_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        sell = Transaction(
            id="sell-1",
            account_id="acct",
            user_id="user",
            asset_id=asset.id,
            transaction_type="SELL",
            quantity=Decimal("0.4"),
            price_per_unit=Decimal("20000"),
            fees=Decimal("0"),
            currency="USD",
            fx_rate_to_aud=Decimal("1.6"),
            transacted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

        state = engine._apply_buy(state, buy, asset)
        state = engine._apply_sell(state, sell, asset, "FIFO")

        with patch("services.portfolio_engine.FXService", _FakeFXService):
            aud = await engine._hydrate_with_prices(state, "user", "AUD")
            usd = await engine._hydrate_with_prices(state, "user", "USD")

        self.assertEqual(aud.holdings[0].original_currency, "USD")
        self.assertEqual(aud.holdings[0].last_price, Decimal("51000.000000"))
        self.assertEqual(aud.holdings[0].total_cost_basis, Decimal("9000.0000000000"))
        self.assertEqual(aud.holdings[0].market_value, Decimal("30600.0000000000"))
        self.assertEqual(aud.total_realized_gain_long, Decimal("6800.0000000000"))

        self.assertEqual(usd.holdings[0].last_price, Decimal("30000.000000"))
        self.assertEqual(usd.holdings[0].total_cost_basis, Decimal("5294.1176470588"))
        self.assertEqual(usd.holdings[0].market_value, Decimal("18000.0000000000"))
        self.assertEqual(usd.total_realized_gain_long, Decimal("4000.0000000000"))

    async def test_display_currency_toggle_preserves_unrealized_gain_sign_and_percent(self):
        asset = Asset(
            id="asset-us",
            symbol="ABC",
            name="ABC Corp",
            asset_class="EQUITY",
            currency="USD",
        )
        engine = PortfolioEngine(_FakeDb([asset]), _FakeMarketData({"ABC": 80.0}))
        state = PortfolioState(as_of=datetime(2026, 1, 2, tzinfo=timezone.utc))

        buy = Transaction(
            id="buy-abc",
            account_id="acct",
            user_id="user",
            asset_id=asset.id,
            transaction_type="BUY",
            quantity=Decimal("1"),
            price_per_unit=Decimal("100"),
            fees=Decimal("0"),
            currency="USD",
            fx_rate_to_aud=Decimal("1.0"),
            transacted_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )

        state = engine._apply_buy(state, buy, asset)

        with patch("services.portfolio_engine.FXService", _FakeFXService):
            aud = await engine._hydrate_with_prices(state, "user", "AUD")
            usd = await engine._hydrate_with_prices(state, "user", "USD")

        self.assertGreater(aud.total_unrealized_gain, 0)
        self.assertGreater(usd.total_unrealized_gain, 0)
        self.assertEqual(aud.total_unrealized_gain_pct, usd.total_unrealized_gain_pct)
        self.assertEqual(aud.holdings[0].unrealized_gain_pct, usd.holdings[0].unrealized_gain_pct)

    async def test_income_without_open_holdings_converts_from_aud_base_for_display(self):
        engine = PortfolioEngine(_FakeDb([]), _FakeMarketData({}))
        state = PortfolioState(as_of=datetime(2026, 1, 2, tzinfo=timezone.utc))
        dividend = Transaction(
            id="div-1",
            account_id="acct",
            user_id="user",
            asset_id=None,
            transaction_type="DIVIDEND",
            net_amount=Decimal("100"),
            currency="USD",
            fx_rate_to_aud=Decimal("1.5"),
            transacted_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
        )

        state = engine._apply_dividend(state, dividend, None)

        with patch("services.portfolio_engine.FXService", _FakeFXService):
            aud = await engine._hydrate_with_prices(state, "user", "AUD")
            usd = await engine._hydrate_with_prices(state, "user", "USD")

        self.assertEqual(aud.dividend_income, Decimal("150.0000000000"))
        self.assertEqual(usd.dividend_income, Decimal("88.2352941176"))
        self.assertEqual(usd.holdings, [])


if __name__ == "__main__":
    unittest.main()
