import importlib.util
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,ROOT/path)
 module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module
normalizer=load("v80_phase9_normalizer",Path("scripts/v80_phase9_price_normalizer.py"))
auditor=load("v80_phase9_4_audit",Path("scripts/v80_phase9_4_integrity_audit.py"))

EVENT={
 "id":"nba-event-2025-02-02-bos-mil",
 "home_team":"Boston Celtics",
 "away_team":"Milwaukee Bucks",
 "commence_time":"2025-02-02T00:00:00Z",
 "bookmakers":[{
  "key":"bookmaker-a",
  "markets":[
   {"key":"h2h","last_update":"2025-02-01T21:34:00Z","outcomes":[
    {"name":"Boston Celtics","price":1.65},{"name":"Milwaukee Bucks","price":2.30}]},
   {"key":"spreads","last_update":"2025-02-01T21:34:00Z","outcomes":[
    {"name":"Boston Celtics","price":1.91,"point":-4.5},{"name":"Milwaukee Bucks","price":1.91,"point":4.5}]},
   {"key":"totals","last_update":"2025-02-01T21:34:00Z","outcomes":[
    {"name":"Over","price":1.91,"point":221.5},{"name":"Under","price":1.91,"point":221.5}]}
  ]}
 ]
}

class NormalizerAuditContractTests(unittest.TestCase):
 def test_real_normalizer_rows_pass_integrity_auditor(self):
  rows=normalizer.normalize_historical_response({
   "timestamp":"2025-02-01T21:35:00Z","data":EVENT})
  self.assertEqual(len(rows),3)
  for row in rows:
   self.assertIsNone(auditor.validate_row(row),row)
  report=auditor.audit_rows(rows)
  self.assertEqual(report["integrity_status"],"PASS")
  self.assertEqual(report["complete_three_market_groups"],1)
 def test_market_group_is_not_complete_if_one_market_missing(self):
  event={**EVENT,"bookmakers":[{**EVENT["bookmakers"][0],"markets":EVENT["bookmakers"][0]["markets"][:2]}]}
  rows=normalizer.normalize_historical_response({"timestamp":"2025-02-01T21:35:00Z","data":event})
  report=auditor.audit_rows(rows)
  self.assertEqual(report["complete_three_market_groups"],0)
  self.assertEqual(report["partial_groups"],1)
 def test_different_bookmakers_do_not_form_complete_group(self):
  book=EVENT["bookmakers"][0]
  split=[{**book,"key":"book-a","markets":[book["markets"][0]]},
         {**book,"key":"book-b","markets":[book["markets"][1]]},
         {**book,"key":"book-c","markets":[book["markets"][2]]}]
  rows=normalizer.normalize_historical_response({"timestamp":"2025-02-01T21:35:00Z","data":{**EVENT,"bookmakers":split}})
  report=auditor.audit_rows(rows)
  self.assertEqual(report["complete_three_market_groups"],0)
  self.assertEqual(report["partial_groups"],3)
 def test_bad_spread_points_are_dropped_by_normalizer(self):
  event={**EVENT,"bookmakers":[{**EVENT["bookmakers"][0],"markets":[
   EVENT["bookmakers"][0]["markets"][0],
   {"key":"spreads","outcomes":[{"name":"Boston Celtics","price":1.91,"point":-4.5},{"name":"Milwaukee Bucks","price":1.91,"point":3.5}]},
   EVENT["bookmakers"][0]["markets"][2]
  ]}]}
  rows=normalizer.normalize_historical_response({"timestamp":"2025-02-01T21:35:00Z","data":event})
  self.assertEqual({r["market"] for r in rows},{"h2h","totals"})
 def test_bad_total_points_are_dropped_by_normalizer(self):
  event={**EVENT,"bookmakers":[{**EVENT["bookmakers"][0],"markets":[
   EVENT["bookmakers"][0]["markets"][0],EVENT["bookmakers"][0]["markets"][1],
   {"key":"totals","outcomes":[{"name":"Over","price":1.91,"point":221.5},{"name":"Under","price":1.91,"point":222.5}]}
  ]}]}
  rows=normalizer.normalize_historical_response({"timestamp":"2025-02-01T21:35:00Z","data":event})
  self.assertEqual({r["market"] for r in rows},{"h2h","spreads"})
 def test_same_pair_probabilities_sum_to_one_after_normalization(self):
  rows=normalizer.normalize_historical_response({"timestamp":"2025-02-01T21:35:00Z","data":EVENT})
  for row in rows:
   err=auditor.validate_row(row)
   self.assertIsNone(err)
if __name__=="__main__": unittest.main()
