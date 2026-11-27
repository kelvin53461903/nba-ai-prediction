import importlib.util
import unittest
from pathlib import Path

P=Path(__file__).resolve().parents[1]/'scripts'/'v80_market_backtest.py'
s=importlib.util.spec_from_file_location('backtest',P)
m=importlib.util.module_from_spec(s); s.loader.exec_module(m)

def rows():
    out=[]
    for i in range(10):
        for market in ('moneyline','spread','total'):
            out.append({'game_id':f'g{i}','game_date':f'2026-11-{i+1:02d}','market':market,
              'model_probability':0.62,'market_probability':0.58,'outcome':i%2,
              'prediction_timestamp':f'2026-11-{i+1:02d}T10:00:00Z',
              'tipoff_timestamp':f'2026-11-{i+1:02d}T23:00:00Z'})
    return out

class MarketBacktestTests(unittest.TestCase):
    def test_chronological_split_keeps_latest_dates_in_holdout(self):
        train,test=m.chronological_holdout(rows(),0.2)
        self.assertLess(max(r['game_date'] for r in train),min(r['game_date'] for r in test))
        self.assertEqual(len(test),6)

    def test_scores_all_three_markets_against_market_baseline(self):
        result=m.compare_model_to_market(rows(),0.2)
        self.assertEqual(set(result['markets']),{'moneyline','spread','total'})
        self.assertEqual(result['holdout_rows'],6)
        self.assertEqual(result['roi'],'NOT_CALCULATED')
        self.assertEqual(result['clv'],'NOT_CALCULATED')

    def test_rejects_prediction_after_tipoff(self):
        data=rows(); data[0]['prediction_timestamp']='2026-11-02T23:30:00Z'
        self.assertTrue(any('before tipoff' in e for e in m.validate_prediction_rows(data)))

    def test_rejects_timezone_naive_prediction(self):
        data=rows(); data[0]['prediction_timestamp']='2026-11-01T10:00:00'
        self.assertTrue(any('must include timezone' in e for e in m.validate_prediction_rows(data)))

    def test_rejects_probability_outside_open_interval(self):
        data=rows(); data[0]['model_probability']=1.0
        self.assertTrue(any('model_probability' in e for e in m.validate_prediction_rows(data)))

    def test_rejects_duplicate_game_market(self):
        data=rows(); data.append(dict(data[0]))
        self.assertTrue(any('duplicate game_id/market' in e for e in m.validate_prediction_rows(data)))

    def test_rejects_non_binary_outcome(self):
        data=rows(); data[0]['outcome']=2
        self.assertTrue(any('outcome must be binary' in e for e in m.validate_prediction_rows(data)))

    def test_rejects_invalid_holdout_fraction(self):
        with self.assertRaises(ValueError): m.chronological_holdout(rows(),0.8)

if __name__=='__main__': unittest.main()