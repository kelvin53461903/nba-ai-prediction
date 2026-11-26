import importlib.util, unittest
from pathlib import Path
P=Path(__file__).resolve().parents[1]/"scripts"/"v80_phase9_historical_price_probe.py"
s=importlib.util.spec_from_file_location("phase9",P); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)
class FakeResponse:
 def __init__(self,data,status=200,headers=None,text=""):
  self._data=data; self.status_code=status; self.headers=headers or {}; self.text=text
 def json(self): return self._data
class FakeSession:
 def __init__(self,events,markets): self.events=events; self.markets=markets; self.calls=[]
 def get(self,url,params,timeout):
  self.calls.append((url,params))
  if url.endswith("/events"): return FakeResponse(self.events,headers={"x-requests-remaining":"90"})
  return FakeResponse(self.markets,headers={"x-requests-remaining":"89"})
class Phase9Tests(unittest.TestCase):
 def test_market_summary_detects_three_featured_markets(self):
  x=m.summarize_markets([{"key":"book-a","markets":[{"key":"h2h"},{"key":"spreads"},{"key":"totals"}]}])
  self.assertTrue(x["has_h2h"]); self.assertTrue(x["has_spreads"]); self.assertTrue(x["has_totals"])
 def test_coverage_probe_never_calls_paid_odds_endpoint(self):
  s=FakeSession([{"id":"evt1","home_team":"A","away_team":"B","commence_time":"2025-02-01T23:00:00Z"}],
   [{"key":"book-a","markets":[{"key":"h2h"},{"key":"spreads"},{"key":"totals"}]}])
  r=m.run_probe("dummy-key",s)
  self.assertFalse(r["paid_historical_odds_endpoint_called"])
  self.assertFalse(r["historical_prices_downloaded"])
  self.assertEqual(len(s.calls),len(m.SAMPLES)*2)
  self.assertTrue(all("/odds" not in u for u,p in s.calls))
 def test_probe_does_not_fail_if_date_has_no_events(self):
  s=FakeSession([],[])
  r=m.run_probe("dummy-key",s)
  self.assertTrue(all(x["coverage_status"]=="NO_EVENTS_AT_SNAPSHOT" for x in r["sample_snapshots"]))
 def test_missing_key_is_rejected(self):
  with self.assertRaises(RuntimeError): m.run_probe("")
if __name__=="__main__": unittest.main()
