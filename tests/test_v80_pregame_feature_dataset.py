import importlib.util, unittest
from pathlib import Path
P=Path(__file__).resolve().parents[1]/'scripts'/'v80_pregame_feature_dataset.py'
s=importlib.util.spec_from_file_location('pregame_features',P); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
def game(gid,home,away,hs,ascore,tip,status='Final'):
 return {'game_id':gid,'season':'2025-26','home_team_id':home,'away_team_id':away,'home_score':hs,'away_score':ascore,'commence_time_utc':tip,'game_status':status}
class PregameFeatureTests(unittest.TestCase):
 def test_first_appearance_has_no_history(self):
  rows=m.build_pregame_rows([game('1','A','B',100,90,'2025-01-01T00:00:00Z')])
  self.assertEqual(rows[0]['home_games_before'],0); self.assertEqual(rows[0]['away_games_before'],0)
 def test_uses_only_strictly_earlier_games(self):
  data=[game('1','A','B',100,90,'2025-01-01T00:00:00Z'),game('2','A','C',110,100,'2025-01-02T00:00:00Z')]
  rows=m.build_pregame_rows(data); second=next(x for x in rows if x['game_id']=='2')
  self.assertEqual(second['home_games_before'],1); self.assertEqual(second['home_avg_points_for_last5'],100.0)
 def test_same_tipoff_games_do_not_leak_into_each_other(self):
  data=[game('1','A','B',100,90,'2025-01-01T00:00:00Z'),game('2','A','C',110,100,'2025-01-01T00:00:00Z')]
  rows=m.build_pregame_rows(data); second=next(x for x in rows if x['game_id']=='2')
  self.assertEqual(second['home_games_before'],0)
 def test_history_is_team_specific_and_rest_days_computed(self):
  data=[game('1','A','B',100,90,'2025-01-01T00:00:00Z'),game('2','C','A',95,105,'2025-01-03T12:00:00Z')]
  rows=m.build_pregame_rows(data); second=next(x for x in rows if x['game_id']=='2')
  self.assertEqual(second['away_games_before'],1); self.assertEqual(second['away_rest_days'],2.5)
 def test_ignores_non_final_games(self):
  rows=m.build_pregame_rows([game('1','A','B',0,0,'2025-01-01T00:00:00Z','Scheduled')])
  self.assertEqual(rows,[])
 def test_rejects_duplicate_game_ids(self):
  g=game('1','A','B',100,90,'2025-01-01T00:00:00Z')
  with self.assertRaises(ValueError): m.build_pregame_rows([g,g])
 def test_rejects_timezone_naive_tipoff(self):
  with self.assertRaises(ValueError): m.build_pregame_rows([game('1','A','B',100,90,'2025-01-01T00:00:00')])
 def test_rejects_same_team_and_negative_scores(self):
  with self.assertRaises(ValueError): m.build_pregame_rows([game('1','A','A',100,90,'2025-01-01T00:00:00Z')])
  with self.assertRaises(ValueError): m.build_pregame_rows([game('2','A','B',-1,90,'2025-01-01T00:00:00Z')])
if __name__=='__main__': unittest.main()