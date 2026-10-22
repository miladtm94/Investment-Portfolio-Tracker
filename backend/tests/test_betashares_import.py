import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.transaction_import import TransactionImporter


class BetasharesImportTests(unittest.TestCase):
    def setUp(self):
        self.importer = TransactionImporter.__new__(TransactionImporter)

    def test_hint_maps_activity_export_and_fractional_trade(self):
        row = {
            "Trade Date": "18/08/2026",
            "Market Code": "ASX",
            "Transaction Type": "Buy",
            "Instrument Code": "DHHF.ASX",
            "Comments": "Consolidated portfolio purchase",
            "Quantity": "1.23456789",
            "Price": "$35.50",
            "Amount": "AUD 43.83",
        }

        profile = self.importer._profile_for_hint("betashares_direct", row)
        parsed = self.importer._normalize_row(row, profile)

        self.assertEqual(profile.name, "Betashares Direct")
        self.assertEqual(parsed.symbol, "DHHF")
        self.assertEqual(parsed.transaction_type, "BUY")
        self.assertEqual(parsed.quantity, Decimal("1.23456789"))
        self.assertEqual(parsed.price, Decimal("35.50"))
        self.assertEqual(parsed.net_amount, Decimal("-43.83"))
        self.assertEqual(parsed.currency, "AUD")

    def test_consolidated_transfer_in_alias_is_supported(self):
        row = {
            "Transaction Date": "2026-08-01",
            "Activity Type": "In-specie transfer-in",
            "ASX Code": "VAS",
            "Units": "12.345678",
            "Cost Price": "95.25",
            "Currency Code": "AUD",
            "Description": "Transferred from another portfolio",
        }

        profile = self.importer._profile_for_hint("betashares", row)
        parsed = self.importer._normalize_row(row, profile)

        self.assertEqual(parsed.transaction_type, "TRANSFER_IN")
        self.assertEqual(parsed.symbol, "VAS")
        self.assertEqual(parsed.quantity, Decimal("12.345678"))
        self.assertEqual(parsed.price, Decimal("95.25"))

    def test_header_signature_auto_detects_betashares_activity_csv(self):
        row = {
            "Trade Date": "2026-08-18",
            "Instrument Code": "NDQ",
            "Market Code": "ASX",
            "Transaction Type": "BUY",
            "Quantity": "0.5",
            "Price": "55",
            "Amount": "27.50",
        }

        profile = self.importer._detect_broker(row)

        self.assertEqual(profile.name, "Betashares Direct")

    def test_import_hash_is_stable_per_account_but_distinct_across_portfolios(self):
        legacy_hash = "same-exported-parcel"

        first = self.importer._scoped_import_hash("portfolio-1", legacy_hash)
        repeated = self.importer._scoped_import_hash("portfolio-1", legacy_hash)
        consolidated = self.importer._scoped_import_hash("portfolio-2", legacy_hash)

        self.assertEqual(first, repeated)
        self.assertNotEqual(first, consolidated)


if __name__ == "__main__":
    unittest.main()
