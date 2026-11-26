import importlib.util
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "scripts" / "v80_phase4b_sbr_repair_audit.py"
spec = importlib.util.spec_from_file_location("v80_phase4b_sbr_repair_audit", PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SBRRepairAuditTests(unittest.TestCase):
    def test_normal_closing_lines(self):
        self.assertEqual(module.sbr_close({
            "home_close_spread": -4.5, "close_over_under": 224.5,
            "home_close_ml": -180, "away_close_ml": 155,
        }), (-4.5, 224.5))

    def test_swapped_lines_home_favorite(self):
        self.assertEqual(module.sbr_close({
            "home_close_spread": 221.5, "close_over_under": 3.5,
            "home_close_ml": -150, "away_close_ml": 130,
        }), (-3.5, 221.5))

    def test_swapped_lines_away_favorite(self):
        self.assertEqual(module.sbr_close({
            "home_close_spread": 221.5, "close_over_under": 3.5,
            "home_close_ml": 130, "away_close_ml": -150,
        }), (3.5, 221.5))

    def test_swapped_line_with_sign_lost(self):
        self.assertEqual(module.sbr_close({
            "home_close_spread": 221.5, "close_over_under": -3.5,
            "home_close_ml": -150, "away_close_ml": 130,
        }), (-3.5, 221.5))

    def test_swapped_zero_spread(self):
        self.assertEqual(module.sbr_close({
            "home_close_spread": 221.5, "close_over_under": 0.0,
            "home_close_ml": -110, "away_close_ml": -110,
        }), (0.0, 221.5))

    def test_swapped_missing_moneyline_rejects_spread(self):
        self.assertEqual(module.sbr_close({
            "home_close_spread": 221.5, "close_over_under": 3.5,
            "home_close_ml": 0, "away_close_ml": 0,
        }), (None, 221.5))

    def test_impossible_total_rejected(self):
        self.assertEqual(module.sbr_close({
            "home_close_spread": -4.5, "close_over_under": 1955.5,
            "home_close_ml": -180, "away_close_ml": 155,
        }), (-4.5, None))

    def test_bubble_date_correction(self):
        self.assertEqual(module.sbr_date({"season": 2019, "date": 20190830.0}).isoformat(), "2020-08-30")

    def test_american_odds_devig(self):
        self.assertAlmostEqual(module.devig(-150, 130), 0.5660377358490566)


if __name__ == "__main__":
    unittest.main()
