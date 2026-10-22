import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.signal_engine import SignalEngine


def make_candles(start_price: float, step: float, count: int = 90):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    price = start_price
    for i in range(count):
        price += step
        rows.append({
            "date": (start + timedelta(hours=i)).isoformat(),
            "open": price - step * 0.4,
            "high": price + abs(step) + 0.5,
            "low": price - abs(step) - 0.5,
            "close": price,
            "volume": 1_000_000 + i * 2_000,
        })
    return rows


class SignalEngineTests(unittest.TestCase):
    def test_uptrend_generates_buy_signal_with_trade_plan(self):
        result = SignalEngine(make_candles(100, 0.8), "60").analyze()

        self.assertIn(result["signal"], {"BUY", "STRONG BUY"})
        self.assertGreater(result["tradePlan"]["entry"], result["tradePlan"]["stopLoss"])
        self.assertGreater(result["tradePlan"]["takeProfit2"], result["tradePlan"]["entry"])
        self.assertGreaterEqual(len(result["evidence"]), 5)

    def test_downtrend_generates_sell_signal_with_trade_plan(self):
        result = SignalEngine(make_candles(200, -0.8), "60").analyze()

        self.assertIn(result["signal"], {"SELL", "STRONG SELL"})
        self.assertLess(result["tradePlan"]["entry"], result["tradePlan"]["stopLoss"])
        self.assertLess(result["tradePlan"]["takeProfit2"], result["tradePlan"]["entry"])
        self.assertGreaterEqual(len(result["evidence"]), 5)


if __name__ == "__main__":
    unittest.main()
