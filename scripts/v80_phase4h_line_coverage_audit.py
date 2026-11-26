#!/usr/bin/env python3
"""Phase 4H line-level completeness audit for exact-score ESPN/Parquet joins.

Reuses Phase 4G's read-only DB query and exact scoreboard matching. Joins only
on a unique ESPN event ID. Reports line-field coverage; never writes to Neon.
"""
from __future__ import annotations
import importlib.util, json
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from pathlib import Path
import duckdb, requests

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("phase4g",ROOT/"scripts"/"v80_phase4g_full_crosswalk_audit.py")
phase4g=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(phase4g)
CACHE=Path(".cache_v80_phase4h"); OUT=Path("artifacts/v80_phase4h")

def classify_line(row):
 spread=row.get("home_point")
 total=row.get("over_under")
 books=row.get("n_books")
 return {
  "spread_valid": spread is not None and abs(float(spread)) <= 40,
  "spread_missing": spread is None,
  "total_valid": total is not None and 150 <= float(total) <= 300,
  "total_missing": total is None,
  "book_count_valid": books is not None and int(books) >= 1,
  "spread_invalid": spread is not None and abs(float(spread)) > 40,
  "total_invalid": total is not None and not (150 <= float(total) <= 300),
 }

def main():
 CACHE.mkdir(exist_ok=True); OUT.mkdir(parents=True,exist_ok=True)
 p=CACHE/"closing_lines_odds_api.parquet"
 if not p.exists():
  r=requests.get(phase4g.PARQUET_URL,timeout=180); r.raise_for_status(); p.write_bytes(r.content)
 con=duckdb.connect()
 parquet_rows=con.execute("""
  SELECT CAST(game_id AS VARCHAR) AS event_id, home_point, over_under,
         n_books, game_spread, home_favorite, commence_time, snapshot, spread_source
  FROM read_parquet(?)
 """,[str(p)]).fetchall()
 names=["event_id","home_point","over_under","n_books","game_spread","home_favorite","commence_time","snapshot","spread_source"]
 line_by_id={str(row[0]):dict(zip(names,row)) for row in parquet_rows}
 duplicate_count=len(parquet_rows)-len(line_by_id)
 games=phase4g.db_rows()
 query_dates=set()
 for g in games:
  for off in range(-2,3): query_dates.add((g["game_date"]+timedelta(days=off)).isoformat())
 events_by_id={}; failures=[]
 with ThreadPoolExecutor(max_workers=8) as pool:
  futures=[pool.submit(phase4g.fetch_one,d) for d in sorted(query_dates)]
  for f in as_completed(futures):
   day,events,error=f.result()
   if error: failures.append({"date":day,"error":error})
   for e in events:
    if e["event_id"]: events_by_id[e["event_id"]]=e
 rows=[]
 for g in games:
  candidates=[]
  from datetime import datetime
  for e in events_by_id.values():
   try: ed=datetime.fromisoformat(e["utc_date"].replace("Z","+00:00")).date()
   except Exception: continue
   if abs((ed-g["game_date"]).days)<=2: candidates.append(e)
  matches=phase4g.exact_candidates(g,candidates)
  if len(matches)!=1:
   rows.append({"season":g["season"],"status":"NO_OR_AMBIGUOUS_SCORE_MATCH"})
   continue
  event_id=matches[0]["event_id"]
  line=line_by_id.get(event_id)
  if line is None:
   rows.append({"season":g["season"],"event_id":event_id,"status":"SOURCE_ID_MISSING"})
   continue
  q=classify_line(line)
  rows.append({"season":g["season"],"event_id":event_id,"status":"MATCHED_LINE_ROW",
   "home_point":line["home_point"],"over_under":line["over_under"],"n_books":line["n_books"],
   "spread_source":line["spread_source"],**q})
 matched=[r for r in rows if r["status"]=="MATCHED_LINE_ROW"]
 seasons={}
 for season in sorted({g["season"] for g in games}):
  sr=[r for r in rows if r.get("season")==season]
  mr=[r for r in sr if r["status"]=="MATCHED_LINE_ROW"]
  seasons[season]={"nba_games":len(sr),"matched_line_rows":len(mr),
   "valid_spread":sum(r["spread_valid"] for r in mr),
   "valid_total":sum(r["total_valid"] for r in mr),
   "both_lines_valid":sum(r["spread_valid"] and r["total_valid"] for r in mr),
   "missing_spread":sum(r["spread_missing"] for r in mr),
   "missing_total":sum(r["total_missing"] for r in mr)}
 report={"phase":"V8.0_PHASE4H","mode":"READ_ONLY_LINE_COMPLETENESS_AUDIT",
  "nba_games":len(games),"parquet_rows":len(parquet_rows),"duplicate_event_ids":duplicate_count,
  "unique_espn_events":len(events_by_id),"scoreboard_date_queries":len(query_dates),
  "scoreboard_failures":failures,"status_counts":dict(Counter(r["status"] for r in rows)),
  "line_coverage":{"matched_rows":len(matched),
   "valid_spread":sum(r["spread_valid"] for r in matched),
   "valid_total":sum(r["total_valid"] for r in matched),
   "both_lines_valid":sum(r["spread_valid"] and r["total_valid"] for r in matched),
   "missing_spread":sum(r["spread_missing"] for r in matched),
   "missing_total":sum(r["total_missing"] for r in matched),
   "invalid_spread":sum(r["spread_invalid"] for r in matched),
   "invalid_total":sum(r["total_invalid"] for r in matched),
   "valid_book_count":sum(r["book_count_valid"] for r in matched)},
  "by_season":seasons,"two_way_spread_prices":False,"two_way_total_prices":False,
  "moneyline_prices":False,"opening_lines":False,"roi_calculable":False,"clv_calculable":False,
  "source_license":"NOASSERTION — legal review required before persistent import",
  "database_writes":0,
  "acceptance":"REQUIRES_REVIEW" if failures or duplicate_count or len(matched)==0 else "LINE_COVERAGE_MEASURED_NOT_PRODUCTION_ACCEPTED",
  "limitations":["Consensus line only; no two-sided prices.","No moneyline odds or opening line.","No ROI or CLV calculation is supported by this source.","Source licence remains unresolved; do not persist or redistribute."]}
 out=OUT/"line_level_market_coverage.json"
 out.write_text(json.dumps(report,indent=2,default=str),encoding="utf-8")
 print(json.dumps(report,indent=2,default=str))
 print(f"RESULT: PHASE 4H LINE COMPLETENESS AUDIT COMPLETE; report={out}")
if __name__=="__main__": main()
