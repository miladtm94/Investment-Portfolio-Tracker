import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.market_data_service import MarketDataService


class FakeMarketDataService(MarketDataService):
    def __init__(self):
        self.calls: list[str] = []

    async def _polygon_history(self, symbol, start, end):
        self.calls.append(f"polygon:{symbol}")
        return []

    async def _yahoo_history(self, symbol, start, end, currency="USD"):
        self.calls.append(f"yahoo:{symbol}")
        return [{"date": "2026-01-01", "close": 100, "open": 100, "high": 100, "low": 100, "volume": 0}]


class MarketDataServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_polygon_history_falls_back_to_yahoo(self):
        service = FakeMarketDataService()

        prices = await service._get_equity_history(
            "BTC-USD",
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 2, tzinfo=timezone.utc),
            "USD",
        )

        self.assertEqual(prices[0]["close"], 100)
        self.assertEqual(service.calls, ["polygon:BTC-USD", "yahoo:BTC-USD"])


if __name__ == "__main__":
    unittest.main()
