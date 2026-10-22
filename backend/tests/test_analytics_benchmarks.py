import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.analytics_engine import AnalyticsEngine


class AnalyticsBenchmarkTests(unittest.TestCase):
    def test_indexes_benchmark_to_portfolio_starting_value(self):
        chart_index = pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"])
        benchmark = pd.Series(
            [50.0, 55.0, 60.0],
            index=pd.to_datetime(["2026-01-01", "2026-01-03", "2026-01-04"]),
        )

        indexed = AnalyticsEngine._index_benchmark_to_portfolio_base(
            benchmark,
            chart_index,
            base_value=1000.0,
        )

        self.assertEqual(indexed.round(2).tolist(), [1000.0, 1000.0, 1100.0, 1200.0])

    def test_late_starting_benchmark_begins_at_first_available_point(self):
        chart_index = pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"])
        benchmark = pd.Series(
            [80.0, 88.0],
            index=pd.to_datetime(["2026-01-03", "2026-01-04"]),
        )

        indexed = AnalyticsEngine._index_benchmark_to_portfolio_base(
            benchmark,
            chart_index,
            base_value=1000.0,
        )

        self.assertEqual(indexed.index.strftime("%Y-%m-%d").tolist(), ["2026-01-03", "2026-01-04"])
        self.assertEqual(indexed.round(2).tolist(), [1000.0, 1100.0])

    def test_cash_benchmark_compounds_from_portfolio_base(self):
        chart_index = pd.to_datetime(["2026-01-01", "2026-07-02"])

        indexed = AnalyticsEngine._build_cash_benchmark_series(
            chart_index,
            base_value=1000.0,
            annual_rate=0.05,
        )

        self.assertEqual(indexed.iloc[0], 1000.0)
        self.assertGreater(indexed.iloc[-1], 1024.0)
        self.assertLess(indexed.iloc[-1], 1026.0)


if __name__ == "__main__":
    unittest.main()
