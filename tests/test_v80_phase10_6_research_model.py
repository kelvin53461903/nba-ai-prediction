import csv, importlib.util, tempfile, unittest
from pathlib import Path

P=Path(__file__).resolve().parents[1]/'scripts'/'v80_phase10_6_research_model.py'
s=importlib.util.spec_from_file_location('research_model',P)
m=importlib.util.module_from_spec(s); s.loader.exec_module(m)

def sample(game_id, season, day, home_win, ats, total):
    return {
      'game_id':str(game_id),'season':season,'commence_time_utc':f'{day}T23:00:00Z',
      'home_win_pct_last5':'0.6','away_win_pct_last5':'0.4',
      'home_win_pct_last10':'0.6','away_win_pct_last10':'0.4',
      'home_avg_points_for_last5':'115','away_avg_points_for_last5':'108',
      'home_avg_points_against_last5':'108','away_avg_points_against_last5':'115',
      'home_avg_points_for_last10':'114','away_avg_points_for_last10':'109',
      'home_avg_points_against_last10':'109','away_avg_points_against_last10':'114',
      'home_rest_days':'2','away_rest_days':'2',
      'actual_home_win':str(home_win),'ats_result':ats,'total_result':total,
      'open_home_win_prob':'0.58','close_home_win_prob':'0.60',
      'open_spread_home':'-3.5','close_home_cover_prob':'0.51',
      'open_total':'220.5','close_over_prob':'0.50'
    }

class Phase106ResearchModelTests(unittest.TestCase):
    def test_labels_and_push_exclusion(self):
        self.assertEqual(m.label_for(sample(1,'2024-25','2024-10-01',1,'home','over'),'moneyline'),1)
        self.assertEqual(m.label_for(sample(1,'2024-25','2024-10-01',1,'away','under'),'spread'),0)
        self.assertIsNone(m.label_for(sample(1,'2024-25','2024-10-01',1,'push','push'),'spread'))

    def test_features_use_open_not_closing_market_values(self):
        row=sample(1,'2024-25','2024-10-01',1,'home','over')
        before=m.features(row,'moneyline')
        row['close_home_win_prob']='0.99'
        self.assertEqual(before,m.features(row,'moneyline'))

    def test_chronological_training_and_calibration_are_separate(self):
        rows=[]
        for i in range(20):
            day=f'2024-10-{i+1:02d}'
            rows.append(sample(i,'2024-25',day,i%2,'home' if i%2 else 'away','over' if i%2 else 'under'))
        prepared=m.prepare(rows,'moneyline')
        dates=sorted({r['date'] for r in prepared})
        cut=max(1,min(len(dates)-1,__import__('math').ceil(len(dates)*.70)))
        train=[r for r in prepared if r['date']<=dates[cut-1]]
        calibration=[r for r in prepared if r['date']>dates[cut-1]]
        self.assertLess(max(r['date'] for r in train),min(r['date'] for r in calibration))
        self.assertEqual(len(train)+len(calibration),20)

    def test_logistic_model_returns_valid_probability(self):
        rows=[]
        for i in range(20):
            r=sample(i,'2024-25',f'2024-10-{i+1:02d}',i%2,'home' if i%2 else 'away','over' if i%2 else 'under')
            rows.append(m.prepare([r],'moneyline')[0])
        predict=m.fit_logistic(rows)
        self.assertGreater(predict(rows[0]),0)
        self.assertLess(predict(rows[0]),1)

    def test_metrics_brier_logloss_auc(self):
        rs=[{'y':1,'p':0.8},{'y':0,'p':0.2}]
        result=m.metrics(rs,'p')
        self.assertEqual(result['n'],2)
        self.assertEqual(result['brier'],0.04)
        self.assertAlmostEqual(result['auc'],1.0)

    def test_missing_feature_is_rejected(self):
        row=sample(1,'2024-25','2024-10-01',1,'home','over')
        row['home_win_pct_last5']=''
        with self.assertRaises(ValueError): m.features(row,'moneyline')

if __name__=='__main__': unittest.main()
