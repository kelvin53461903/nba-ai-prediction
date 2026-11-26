import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "v80_phase3_source_audit.py"
spec = importlib.util.spec_from_file_location("v80_phase3_source_audit", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class HistoricalOddsAuditHelpersTest(unittest.TestCase):
    def test_american_odds_conversion(self):
        self.assertAlmostEqual(module.american_to_implied_probability(-150), 0.6)
        self.assertAlmostEqual(module.american_to_implied_probability(130), 100 / 230)
        with self.assertRaises(ValueError):
            module.american_to_implied_probability(0)

    def test_two_way_devig_normalizes_probabilities(self):
        home, away = module.devig_two_way(-150, 130)
        self.assertAlmostEqual(home + away, 1.0)
        self.assertGreater(home, 0.5)

    def test_brier_score(self):
        self.assertAlmostEqual(module.brier_score([(0.8, 1.0), (0.2, 0.0)]), 0.04)
        self.assertIsNone(module.brier_score([]))

    def test_market_quality_gate_rejects_bad_total_distribution(self):
        reasons = module.market_quality_rejection_reasons(
            ml_brier=0.20,
            score_exact=100,
            score_mismatch=0,
            score_missing=0,
            total_over_rate=0.90,
            mean_total_line=194.0,
            mean_actual_total=222.0,
            invalid_spread_rows=0,
            invalid_total_rows=0,
        )
        self.assertTrue(any("over/under settlement is severely imbalanced" in x for x in reasons))
        self.assertTrue(any("mean total line differs" in x for x in reasons))

    def test_market_quality_gate_accepts_plausible_synthetic_fixture(self):
        reasons = module.market_quality_rejection_reasons(
            ml_brier=0.20,
            score_exact=100,
            score_mismatch=0,
            score_missing=0,
            total_over_rate=0.51,
            mean_total_line=222.0,
            mean_actual_total=222.5,
            invalid_spread_rows=0,
            invalid_total_rows=0,
        )
        self.assertEqual(reasons, [])

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
