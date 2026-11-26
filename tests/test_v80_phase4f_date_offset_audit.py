import importlib.util, unittest
from pathlib import Path
PATH=Path(__file__).resolve().parents[1]/"scripts"/"v80_phase4f_date_offset_audit.py"
spec=importlib.util.spec_from_file_location("v80_phase4f_date_offset_audit",PATH)
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
class Phase4FTests(unittest.TestCase):
 def setUp(self):
  self.game={"home_team":"Boston Celtics","away_team":"Miami Heat","home_score":116,"away_score":120}
  self.event={"event_id":"123","home":"Boston Celtics","away":"Miami Heat","home_score":116,"away_score":120}
 def test_exact_score_team_match(self):
  self.assertEqual(len(m.candidate_match(self.game,[self.event])),1)
 def test_wrong_score_rejected(self):
  e=dict(self.event,home_score=117)
  self.assertEqual(m.candidate_match(self.game,[e]),[])
 def test_wrong_home_away_rejected(self):
  e=dict(self.event,home="Miami Heat",away="Boston Celtics")
  self.assertEqual(m.candidate_match(self.game,[e]),[])
 def test_duplicate_exact_events_are_ambiguous(self):
  self.assertEqual(len(m.candidate_match(self.game,[self.event,dict(self.event,event_id="456")])),2)
if __name__=="__main__": unittest.main()
