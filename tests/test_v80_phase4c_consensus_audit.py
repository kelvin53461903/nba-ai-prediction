import importlib.util
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "scripts" / "v80_phase4c_consensus_audit.py"
spec = importlib.util.spec_from_file_location("v80_phase4c_consensus_audit", PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class Phase4CConsensusAuditTests(unittest.TestCase):
    def test_required_schema(self):
        self.assertEqual(module.validate_schema({"game_id", "home_point", "over_under", "spread_source"}), [])

    def test_missing_schema_fields(self):
        self.assertEqual(module.validate_schema({"game_id", "home_point"}), ["over_under", "spread_source"])

    def test_plausible_spread(self):
        self.assertTrue(module.plausible_spread(-22.5))
        self.assertFalse(module.plausible_spread(45.0))
        self.assertFalse(module.plausible_spread(None))

    def test_plausible_total(self):
        self.assertTrue(module.plausible_total(225.5))
        self.assertFalse(module.plausible_total(301.0))
        self.assertFalse(module.plausible_total(None))

if __name__ == "__main__":
    unittest.main()
