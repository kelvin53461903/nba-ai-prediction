import importlib.util, unittest
from pathlib import Path
P=Path(__file__).resolve().parents[1]/"scripts"/"v80_phase9_4_integrity_audit.py"
s=importlib.util.spec_from_file_location("phase94",P); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)

def row(market):
 base={"provider":"the-odds-api","sport_key":"basketball_nba","event_id":"evt-1",
  "bookmaker":"book-a","home_team":"Boston Celtics","away_team":"Milwaukee Bucks",
  "snapshot_timestamp":"2025-02-01T21:35:00Z","commence_time":"2025-02-02T00:00:00Z","market":market}
 if market=="h2h": base.update(home_price_decimal=1.65,away_price_decimal=2.3,home_no_vig_probability=.5822784810126582,away_no_vig_probability=.4177215189873418)
 elif market=="spreads": base.update(home_price_decimal=1.91,away_price_decimal=1.91,home_point=-4.5,away_point=4.5,home_no_vig_probability=.5,away_no_vig_probability=.5)
 else: base.update(over_price_decimal=1.91,under_price_decimal=1.91,total_point=221.5,under_point=221.5,over_no_vig_probability=.5,under_no_vig_probability=.5)
 return base

class Phase94Tests(unittest.TestCase):
 def test_complete_three_market_group_passes(self):
  r=m.audit_rows([row(x) for x in m.MARKETS])
  self.assertEqual(r["integrity_status"],"PASS"); self.assertEqual(r["complete_three_market_groups"],1)
 def test_incomplete_market_group_is_not_complete(self):
  r=m.audit_rows([row("h2h"),row("spreads")])
  self.assertEqual(r["complete_three_market_groups"],0); self.assertEqual(r["partial_groups"],1)
 def test_different_bookmakers_are_never_combined(self):
  a=row("h2h"); b=row("spreads"); b["bookmaker"]="book-b"; c=row("totals")
  r=m.audit_rows([a,b,c]); self.assertEqual(r["complete_three_market_groups"],0)
 def test_duplicate_same_snapshot_market_is_rejected(self):
  a=row("h2h"); b=row("h2h")
  r=m.audit_rows([a,b]); self.assertEqual(r["invalid_rows"],1); self.assertEqual(r["integrity_status"],"FAIL")
 def test_rejects_naive_timestamp(self):
  a=row("h2h"); a["snapshot_timestamp"]="2025-02-01T21:35:00"
  self.assertEqual(m.validate_row(a),"TIMESTAMP_INVALID")
 def test_rejects_bad_spread_line(self):
  a=row("spreads"); a["away_point"]=3.5
  self.assertEqual(m.validate_row(a),"SPREAD_LINE_PAIR_INVALID")
 def test_rejects_bad_total_line(self):
  a=row("totals"); a["under_point"]=222.5
  self.assertEqual(m.validate_row(a),"TOTAL_LINE_PAIR_INVALID")
 def test_rejects_probability_pair_not_summing_to_one(self):
  a=row("h2h"); a["home_no_vig_probability"]=0.6
  self.assertEqual(m.validate_row(a),"H2H_PROBABILITY_PAIR_INVALID")
 def test_empty_dataset_fails_closed(self):
  self.assertEqual(m.audit_rows([])["integrity_status"],"FAIL")
 def test_audit_does_not_claim_prices_or_roi(self):
  r=m.audit_rows([row(x) for x in m.MARKETS])
  self.assertFalse(r["historical_prices_downloaded_by_this_audit"])
  self.assertFalse(r["paid_api_called_by_this_audit"])
  self.assertEqual(r["production_database_writes"],0)
  self.assertIn("NOT_CALCULABLE",r["roi_clv_status"])
if __name__=="__main__": unittest.main()
