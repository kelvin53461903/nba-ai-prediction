import importlib.util, unittest
from pathlib import Path
import numpy as np
P=Path(__file__).resolve().parents[1]/"scripts"/"v80_phase7_calibration_gate.py"
s=importlib.util.spec_from_file_location("phase7",P); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
class Phase7Tests(unittest.TestCase):
 def test_logit_clips_zero_one(self):
  z=m.logit([0,1]); self.assertTrue(np.isfinite(z).all())
 def test_score_calibration_gap(self):
  x=m.score([0,1,0,1],[.2,.8,.4,.6]); self.assertAlmostEqual(x["calibration_gap"],0)
 def test_reliability_bins_cover_observations(self):
  x=m.reliability([0,1,1],[.1,.6,.9]); self.assertEqual(sum(v["n"] for v in x),3)
 def test_marketline_moneyline_unavailable_by_design(self):
  self.assertNotIn("moneyline",m.SPECS)
if __name__=="__main__": unittest.main()
