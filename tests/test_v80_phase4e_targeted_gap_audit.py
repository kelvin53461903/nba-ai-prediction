import importlib.util, unittest
from pathlib import Path
PATH=Path(__file__).resolve().parents[1]/"scripts"/"v80_phase4e_targeted_gap_audit.py"
spec=importlib.util.spec_from_file_location("v80_phase4e_targeted_gap_audit",PATH)
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
class Phase4ETests(unittest.TestCase):
 def test_event_parse_et_date(self):
  payload={"events":[{"id":"1","date":"2022-12-02T01:00:00Z","competitions":[{"competitors":[{"homeAway":"home","score":"100","team":{"displayName":"A"}},{"homeAway":"away","score":"99","team":{"displayName":"B"}}]}]}]}
  e=m.get_events(payload)[0]
  self.assertEqual(e["et_date"],"2022-12-01")
  self.assertEqual(e["home_score"],100)
 def test_empty_scoreboard(self):
  self.assertEqual(m.get_events({"events":[]}),[])
if __name__=="__main__": unittest.main()
