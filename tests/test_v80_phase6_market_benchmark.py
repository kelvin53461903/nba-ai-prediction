import importlib.util, unittest
from pathlib import Path
import numpy as np
P=Path(__file__).resolve().parents[1]/"scripts"/"v80_phase6_market_benchmark.py"
s=importlib.util.spec_from_file_location("phase6",P); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
class Phase6Tests(unittest.TestCase):
 def test_metrics_are_finite(self):
  q=m.metrics([0,1,0,1],[.2,.8,.4,.7])
  self.assertEqual(q["n"],4); self.assertGreaterEqual(q["brier"],0); self.assertLessEqual(q["brier"],1)
 def test_clips_extreme_probabilities(self):
  q=m.metrics([0,1],[0,1]); self.assertTrue(np.isfinite(q["log_loss"]))
 def test_market_targets_exclude_push(self):
  self.assertEqual(m.MARKETS["spread"]["positive"],"HOME_COVER")
  self.assertEqual(m.MARKETS["total"]["positive"],"OVER")
  self.assertEqual(m.MARKETS["spread"]["push"],"PUSH")
if __name__=="__main__": unittest.main()
