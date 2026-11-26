import importlib.util, unittest
from pathlib import Path
P=Path(__file__).resolve().parents[1]/"scripts"/"v80_phase6c_market_elo_features.py"
s=importlib.util.spec_from_file_location("phase6c",P); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
def game(i,day,h,a,hs,as_,line=-3,total=210):
 return {"nba_game_id":str(i),"game_date":day,"commence_time_utc":day+"T20:00:00+00:00","home_team":h,"away_team":a,"home_score":hs,"away_score":as_,"home_point":line,"over_under":total}
class Phase6CTests(unittest.TestCase):
 def test_first_game_has_no_prior_features(self):
  x=m.enrich_rows([game(1,"2025-01-01","A","B",110,100)])[0]
  self.assertIsNone(x["home_prev5_win_rate"]); self.assertEqual(x["home_elo"],1500.0)
 def test_prior_ats_and_total_residual(self):
  rows=[game(1,"2025-01-01","A","B",110,100,-3,205),game(2,"2025-01-02","A","C",110,100,-3,205)]
  x=m.enrich_rows(rows)[1]
  self.assertEqual(x["home_prev5_ats_cover_rate"],1.0)
  self.assertEqual(x["home_prev5_over_rate"],1.0)
  self.assertEqual(x["home_prev5_total_residual_avg"],5.0)
 def test_same_day_results_are_not_used(self):
  rows=[game(1,"2025-01-01","A","B",120,90),game(2,"2025-01-01","A","C",80,110),game(3,"2025-01-02","A","D",115,100)]
  x=m.enrich_rows(rows)
  same=next(r for r in x if r["nba_game_id"]=="2")
  nxt=next(r for r in x if r["nba_game_id"]=="3")
  self.assertIsNone(same["home_prev5_win_rate"])
  self.assertEqual(nxt["home_prev5_win_rate"],.5)
  self.assertEqual(nxt["home_prev5_net_points_avg"],0.0)
 def test_elo_changes_only_after_date_batch(self):
  rows=[game(1,"2025-01-01","A","B",120,90),game(2,"2025-01-01","C","D",90,120),game(3,"2025-01-02","A","E",100,90)]
  x=m.enrich_rows(rows)
  same=next(r for r in x if r["nba_game_id"]=="2")
  nxt=next(r for r in x if r["nba_game_id"]=="3")
  self.assertEqual(same["home_elo"],1500.0)
  self.assertNotEqual(nxt["home_elo"],1500.0)

 def test_pre_tip_filter_keeps_only_strictly_earlier_snapshot(self):
  base=game(10,"2025-01-03","A","B",110,100)
  rows=[
   {**base,"closing_snapshot":"2025-01-03T19:59:00Z"},
   {**base,"nba_game_id":"11","closing_snapshot":"2025-01-03T20:00:00Z"},
   {**base,"nba_game_id":"12","closing_snapshot":"2025-01-03T20:01:00Z"},
  ]
  kept,rejected=m.filter_pre_tip_rows(rows)
  self.assertEqual([r["nba_game_id"] for r in kept],["10"])
  self.assertEqual(rejected["snapshot_at_or_after_tip"],2)
 def test_pre_tip_filter_rejects_timezone_naive_and_missing(self):
  base=game(20,"2025-01-03","A","B",110,100)
  rows=[{**base,"closing_snapshot":"2025-01-03T19:59:00"},
        {**base,"nba_game_id":"21","closing_snapshot":None}]
  kept,rejected=m.filter_pre_tip_rows(rows)
  self.assertEqual(kept,[])
  self.assertEqual(rejected["missing_or_invalid_timestamp"],2)
 def test_pre_tip_filter_compares_timezone_offsets_as_instants(self):
  base=game(30,"2025-01-03","A","B",110,100)
  rows=[{**base,"closing_snapshot":"2025-01-04T04:59:00+09:00"}]
  kept,rejected=m.filter_pre_tip_rows(rows)
  self.assertEqual(len(kept),1)
  self.assertEqual(sum(rejected.values()),0)
if __name__=="__main__": unittest.main()
