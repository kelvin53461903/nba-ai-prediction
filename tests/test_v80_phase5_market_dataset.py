import importlib.util, unittest
from pathlib import Path
PATH=Path(__file__).resolve().parents[1]/"scripts"/"v80_phase5_market_dataset.py"
spec=importlib.util.spec_from_file_location("v80_phase5_market_dataset",PATH)
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
class Phase5Tests(unittest.TestCase):
 def test_home_cover(self): self.assertEqual(m.classify_ats(110,100,-4.5),"HOME_COVER")
 def test_away_cover(self): self.assertEqual(m.classify_ats(100,110,-4.5),"AWAY_COVER")
 def test_spread_push(self): self.assertEqual(m.classify_ats(104.5,100,-4.5),"PUSH")
 def test_over_under_push(self):
  self.assertEqual(m.classify_total(110,105,214),"OVER")
  self.assertEqual(m.classify_total(100,100,205),"UNDER")
  self.assertEqual(m.classify_total(105,100,205),"PUSH")
 def test_chronological_splits(self):
  self.assertEqual(m.split_for_season("2020-21"),"TRAIN")
  self.assertEqual(m.split_for_season("2023-24"),"VALIDATION")
  self.assertEqual(m.split_for_season("2024-25"),"TEST")
  self.assertEqual(m.split_for_season("2025-26"),"FINAL_HOLDOUT")
if __name__=="__main__": unittest.main()
