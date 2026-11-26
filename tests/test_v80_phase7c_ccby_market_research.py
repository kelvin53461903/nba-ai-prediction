import importlib.util,unittest
from pathlib import Path
P=Path(__file__).resolve().parents[1]/"scripts"/"v80_phase7c_ccby_market_research.py"
s=importlib.util.spec_from_file_location("phase7c",P); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
class Phase7CTests(unittest.TestCase):
 def test_timezone_required(self):
  with self.assertRaises(ValueError): m.parse_utc("2025-01-01T20:00:00")
 def test_market_definitions(self):
  self.assertEqual(m.MARKETS["moneyline"][1:3],("home","away"))
  self.assertEqual(m.MARKETS["spread"][1:3],("home","away"))
  self.assertEqual(m.MARKETS["totals"][1:3],("over","under"))
 def test_metrics_are_bounded(self):
  x=m.metrics([0,1,0,1],[.2,.8,.3,.7])
  self.assertEqual(x["n"],4); self.assertLessEqual(x["brier"],1)
 def test_split_requires_both_seasons(self):
  with self.assertRaises(RuntimeError): m.assign_splits([{"_season":"2024-25","_tip":m.parse_utc("2025-01-01T00:00:00Z")}])
if __name__=="__main__": unittest.main()
