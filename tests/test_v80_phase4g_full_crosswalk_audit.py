import importlib.util, unittest
from pathlib import Path
PATH=Path(__file__).resolve().parents[1]/"scripts"/"v80_phase4g_full_crosswalk_audit.py"
spec=importlib.util.spec_from_file_location("v80_phase4g_full_crosswalk_audit",PATH)
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
class Phase4GTests(unittest.TestCase):
 def setUp(self):
  self.g={"home_team":"Boston Celtics","away_team":"Miami Heat","home_score":116,"away_score":120}
  self.e={"event_id":"123","home":"Boston Celtics","away":"Miami Heat","home_score":116,"away_score":120}
 def test_exact_match(self): self.assertEqual(len(m.exact_candidates(self.g,[self.e])),1)
 def test_wrong_score(self): self.assertEqual(m.exact_candidates(self.g,[dict(self.e,away_score=119)]),[])
 def test_wrong_venue_order(self): self.assertEqual(m.exact_candidates(self.g,[dict(self.e,home="Miami Heat",away="Boston Celtics")]),[])
 def test_ambiguous(self): self.assertEqual(len(m.exact_candidates(self.g,[self.e,dict(self.e,event_id="456")])),2)
 def test_team_alias(self): self.assertEqual(m.canon("LA Clippers"),"Los Angeles Clippers")
if __name__=="__main__": unittest.main()
