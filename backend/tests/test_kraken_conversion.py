import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.kraken_utils import detect_ledger_conversion_refs


ASSET_MAP = {"XXBT": "BTC", "XBT": "BTC"}
FIAT_SYMBOLS = {"USD", "EUR", "GBP", "AUD", "CAD", "JPY", "CHF"}
STABLECOIN_SYMBOLS = {"USDC", "USDT", "DAI", "BUSD"}


def normalize_asset(raw: str) -> str:
    return ASSET_MAP.get(raw.upper().strip(), raw.upper().strip())


class KrakenConversionTests(unittest.TestCase):
    def test_detects_ledger_only_usdc_to_btc_conversion(self):
        ledger = [
            ("L1", {"refid": "CONVERT-1", "type": "funding", "asset": "USDC", "amount": "-1000"}),
            ("L2", {"refid": "CONVERT-1", "type": "funding", "asset": "XXBT", "amount": "0.01"}),
        ]

        detected = detect_ledger_conversion_refs(
            ledger,
            {},
            normalize_asset,
            FIAT_SYMBOLS,
            STABLECOIN_SYMBOLS,
        )

        self.assertEqual(detected["CONVERT-1"]["USDC"], ("SELL", Decimal("1.0")))
        self.assertEqual(detected["CONVERT-1"]["BTC"], ("BUY", Decimal("100000.0000000000")))

    def test_ignores_refs_already_present_in_trades_history(self):
        ledger = [
            ("L1", {"refid": "TRADE-1", "type": "trade", "asset": "USDC", "amount": "-1000"}),
            ("L2", {"refid": "TRADE-1", "type": "trade", "asset": "XXBT", "amount": "0.01"}),
        ]

        detected = detect_ledger_conversion_refs(
            ledger,
            {"TRADE-1": "BTC"},
            normalize_asset,
            FIAT_SYMBOLS,
            STABLECOIN_SYMBOLS,
        )

        self.assertEqual(detected, {})


if __name__ == "__main__":
    unittest.main()
