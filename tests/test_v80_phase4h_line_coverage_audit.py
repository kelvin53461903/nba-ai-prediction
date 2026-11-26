import importlib.util, unittest
from pathlib import Path
PATH=Path(__file__).resolve().parents[1]/"scripts"/"v80_phase4h_line_coverage_audit.py"
spec=importlib.util.spec_from_file_location("v80_phase4h_line_coverage_audit",PATH)
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
class Phase4HTests(unittest.TestCase):
 def test_valid_lines(self):
  q=m.classify_line({"home_point":-4.5,"over_under":221.5,"n_books":12})
  self.assertTrue(q["spread_valid"]); self.assertTrue(q["total_valid"]); self.assertTrue(q["book_count_valid"])
 def test_missing_lines_are_not_imputed(self):
  q=m.classify_line({"home_point":None,"over_under":None,"n_books":None})
  self.assertTrue(q["spread_missing"]); self.assertTrue(q["total_missing"])
  self.assertFalse(q["spread_valid"]); self.assertFalse(q["total_valid"])
 def test_invalid_ranges(self):
  q=m.classify_line({"home_point":55,"over_under":310,"n_books":0})
  self.assertTrue(q["spread_invalid"]); self.assertTrue(q["total_invalid"])
  self.assertFalse(q["book_count_valid"])
if __name__=="__main__": unittest.main()
