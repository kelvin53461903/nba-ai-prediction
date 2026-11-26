import importlib.util, unittest
from pathlib import Path
P=Path(__file__).resolve().parents[1]/"scripts"/"v80_phase6b_rolling_features.py"
s=importlib.util.spec_from_file_location("phase6b",P); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
def game(i,day,home,away,hs,as_):
 return {"nba_game_id":str(i),"game_date":day,"commence_time_utc":day+"T20:00:00+00:00","home_team":home,"away_team":away,"home_score":hs,"away_score":as_}
class Phase6BTests(unittest.TestCase):
 def test_first_game_has_no_prior_form(self):
  x=m.enrich_rows([game(1,"2025-01-01","A","B",100,90)])[0]
  self.assertEqual(x["home_prev_games"],0); self.assertIsNone(x["home_prev_win_rate"])
 def test_prior_game_only(self):
  rows=[game(1,"2025-01-01","A","B",100,90),game(2,"2025-01-02","A","C",110,100)]
  x=m.enrich_rows(rows)[1]
  self.assertEqual(x["home_prev_games"],1); self.assertEqual(x["home_prev_win_rate"],1.0)
  self.assertEqual(x["home_prev_points_for_avg"],100.0)
 def test_same_day_results_not_used(self):
  rows=[game(1,"2025-01-01","A","B",100,90),game(2,"2025-01-01","A","C",70,80),game(3,"2025-01-02","A","D",110,100)]
  x=m.enrich_rows(rows)
  same_day=next(r for r in x if r["nba_game_id"]=="2")
  next_day=next(r for r in x if r["nba_game_id"]=="3")
  self.assertEqual(same_day["home_prev_games"],0)
  self.assertEqual(next_day["home_prev_games"],2)
if __name__=="__main__": unittest.main()

