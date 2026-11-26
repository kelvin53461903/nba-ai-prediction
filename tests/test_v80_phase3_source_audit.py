import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "v80_phase3_source_audit.py"
spec = importlib.util.spec_from_file_location("v80_phase3_source_audit", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class HistoricalOddsAuditHelpersTest(unittest.TestCase):
    def test_sbr_day_parses_yyyymmdd(self):
        self.assertEqual(
            module.sbr_day({"date": 20250115}).isoformat(),
            "2025-01-15",
        )

    def test_close_lines_standard_columns(self):
        spread, total = module.sbr_close_lines({
            "home_close_spread": -4.5,
            "close_over_under": 224.5,
            "home_close_ml": -180,
            "away_close_ml": 155,
        })
        self.assertEqual(spread, -4.5)
        self.assertEqual(total, 224.5)

    def test_close_lines_detects_swapped_fields(self):
        spread, total = module.sbr_close_lines({
            "home_close_spread": 221.5,
            "close_over_under": -3.5,
            "home_close_ml": -150,
            "away_close_ml": 130,
        })
        self.assertEqual(spread, -3.5)
        self.assertEqual(total, 221.5)

    def test_close_lines_rejects_unrecoverable_spread(self):
        spread, total = module.sbr_close_lines({
            "home_close_spread": 221.5,
            "close_over_under": -3.5,
            "home_close_ml": 0,
            "away_close_ml": 0,
        })
        self.assertIsNone(spread)
        self.assertEqual(total, 221.5)


if __name__ == "__main__":
    unittest.main()
