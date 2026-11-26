import importlib.util,unittest
from pathlib import Path
import numpy as np
P=Path(__file__).resolve().parents[1]/"scripts"/"v80_phase7b_model_comparison.py"
s=importlib.util.spec_from_file_location("phase7b",P); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
class Phase7BTests(unittest.TestCase):
 def test_logit_is_finite_at_extremes(self):
  self.assertTrue(np.isfinite(m.logit([0,1])).all())
 def test_candidate_set_contains_baseline_and_advanced(self):
  self.assertIn("market_only_logistic",["market_only_logistic","rolling_features_logistic","rolling_features_hist_gradient_boosting"])
  self.assertEqual(len(m.NUM),len(set(m.NUM)))
 def test_market_targets_and_push_exclusion(self):
  self.assertEqual(m.SPECS["spread"][1:],("HOME_COVER","AWAY_COVER"))
  self.assertEqual(m.SPECS["total"][1:],("OVER","UNDER"))
 def test_metrics_range(self):
  x=m.metrics([0,1,0,1],[.2,.8,.3,.7])
  self.assertEqual(x["n"],4); self.assertGreaterEqual(x["brier"],0); self.assertLessEqual(x["brier"],1)
if __name__=="__main__":unittest.main()
