import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.period_utils import cap_period_start_to_earliest_transaction


class PeriodUtilsTests(unittest.TestCase):
    def test_caps_start_to_first_transaction_day(self):
        requested = datetime(2023, 1, 1, tzinfo=timezone.utc)
        first_txn = datetime(2025, 4, 9, 14, 30, tzinfo=timezone.utc)

        capped = cap_period_start_to_earliest_transaction(requested, first_txn)

        self.assertEqual(capped, datetime(2025, 4, 9, tzinfo=timezone.utc))

    def test_keeps_requested_start_when_data_exists_before_range(self):
        requested = datetime(2025, 1, 1, tzinfo=timezone.utc)
        first_txn = datetime(2024, 10, 22, 9, 0, tzinfo=timezone.utc)

        capped = cap_period_start_to_earliest_transaction(requested, first_txn)

        self.assertEqual(capped, requested)


if __name__ == "__main__":
    unittest.main()
