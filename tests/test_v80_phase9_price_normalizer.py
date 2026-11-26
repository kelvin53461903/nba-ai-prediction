import importlib.util,unittest
from pathlib import Path
P=Path(__file__).resolve().parents[1]/"scripts"/"v80_phase9_price_normalizer.py"
s=importlib.util.spec_from_file_location("price_normalizer",P); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
EVENT={"id":"evt1","home_team":"Boston Celtics","away_team":"Milwaukee Bucks"}
BOOK={"key":"book-a","markets":[
 {"key":"h2h","last_update":"2025-02-01T21:35:00Z","outcomes":[{"name":"Boston Celtics","price":1.65},{"name":"Milwaukee Bucks","price":2.3}]},
 {"key":"spreads","last_update":"2025-02-01T21:35:00Z","outcomes":[{"name":"Boston Celtics","price":1.91,"point":-4.5},{"name":"Milwaukee Bucks","price":1.91,"point":4.5}]},
 {"key":"totals","last_update":"2025-02-01T21:35:00Z","outcomes":[{"name":"Over","price":1.91,"point":221.5},{"name":"Under","price":1.91,"point":221.5}]}
]}
class PriceNormalizerTests(unittest.TestCase):
 def test_devig_decimal(self):
  a,b=m.devig_decimal(2.0,2.0); self.assertAlmostEqual(a,.5); self.assertAlmostEqual(b,.5)
 def test_normalizes_three_paired_markets(self):
  rows=m.normalize_bookmaker_event(EVENT,BOOK,"2025-02-01T21:35:00Z")
  self.assertEqual([x["market"] for x in rows],["h2h","spreads","totals"])
  self.assertTrue(all(x["bookmaker"]=="book-a" for x in rows))
  self.assertTrue(all(x["snapshot_timestamp"]=="2025-02-01T21:35:00Z" for x in rows))
 def test_rejects_unpaired_spread_line(self):
  b={**BOOK,"markets":[dict(BOOK["markets"][1],outcomes=[
   {"name":"Boston Celtics","price":1.91,"point":-4.5},
   {"name":"Milwaukee Bucks","price":1.91,"point":3.5}])]}
  self.assertEqual(m.normalize_bookmaker_event(EVENT,b,"t"),[])
 def test_rejects_unpaired_total_line(self):
  b={**BOOK,"markets":[dict(BOOK["markets"][2],outcomes=[
   {"name":"Over","price":1.91,"point":221.5},
   {"name":"Under","price":1.91,"point":222.5}])]}
  self.assertEqual(m.normalize_bookmaker_event(EVENT,b,"t"),[])
 def test_rejects_missing_side_or_invalid_price(self):
  b={**BOOK,"markets":[{"key":"h2h","outcomes":[{"name":"Boston Celtics","price":1.65},{"name":"Milwaukee Bucks","price":1.0}]}]}
  self.assertEqual(m.normalize_bookmaker_event(EVENT,b,"t"),[])
 def test_wrapped_response_schema(self):
  rows=m.normalize_historical_response({"timestamp":"2025-02-01T21:35:00Z","data":{**EVENT,"bookmakers":[BOOK]}})
  self.assertEqual(len(rows),3)
 def test_rejects_missing_snapshot_timestamp(self):
  with self.assertRaises(ValueError): m.normalize_historical_response({"data":{**EVENT,"bookmakers":[BOOK]}})
if __name__=="__main__":unittest.main()
