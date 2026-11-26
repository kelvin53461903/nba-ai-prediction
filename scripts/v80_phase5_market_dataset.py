#!/usr/bin/env python3
"""Phase 5: create a read-only, chronological spread/total benchmark dataset.

Inputs: Phase 4G exact-score ESPN crosswalk JSON, pinned closing-lines Parquet,
and the isolated NBA results DB. Output stays in GitHub Actions artifacts.
No database writes, no model fitting, and no ROI claims.
"""
from __future__ import annotations
import importlib.util, json
from collections import Counter, defaultdict
from pathlib import Path
import duckdb

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("phase4g",ROOT/"scripts"/"v80_phase4g_full_crosswalk_audit.py")
phase4g=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(phase4g)
PARQUET_URL=phase4g.PARQUET_URL
CACHE=Path(".cache_v80_phase5"); OUT=Path("artifacts/v80_phase5")
CROSSWALK=Path("artifacts/v80_phase4g/full_six_season_exact_score_crosswalk.json")

def classify_ats(home_score,away_score,home_point):
 margin=float(home_score)-float(away_score)+float(home_point)
 return "HOME_COVER" if margin>0 else "AWAY_COVER" if margin<0 else "PUSH"

def classify_total(home_score,away_score,line):
 actual=float(home_score)+float(away_score)
 return "OVER" if actual>float(line) else "UNDER" if actual<float(line) else "PUSH"

def split_for_season(season):
 if season in ("2020-21","2021-22","2022-23"): return "TRAIN"
 if season=="2023-24": return "VALIDATION"
 if season=="2024-25": return "TEST"
 if season=="2025-26": return "FINAL_HOLDOUT"
 return "EXCLUDED"

def main():
 CACHE.mkdir(exist_ok=True); OUT.mkdir(parents=True,exist_ok=True)
 if not CROSSWALK.exists(): raise RuntimeError("Missing Phase 4G crosswalk artifact; run the full workflow first")
 cross=json.loads(CROSSWALK.read_text(encoding="utf-8"))
 if cross.get("mode")!="READ_ONLY_FULL_SIX_SEASON_EXACT_SCORE_CROSSWALK":
  raise RuntimeError("Unexpected Phase 4G crosswalk report mode")
 if cross.get("scoreboard_query_failures"): raise RuntimeError("Phase 4G scoreboard query failures; refusing dataset build")
 parquet=CACHE/"closing_lines_odds_api.parquet"
 if not parquet.exists():
  import requests
  r=requests.get(PARQUET_URL,timeout=180); r.raise_for_status(); parquet.write_bytes(r.content)
 con=duckdb.connect()
 raw=con.execute("""
  SELECT CAST(game_id AS VARCHAR) AS event_id, home_point, over_under,
         n_books, home_favorite, commence_time, snapshot, spread_source
  FROM read_parquet(?)
 """,[str(parquet)]).fetchall()
 cols=["event_id","home_point","over_under","n_books","home_favorite","commence_time","snapshot","spread_source"]
 lines={str(row[0]):dict(zip(cols,row)) for row in raw}
 if len(lines)!=len(raw): raise RuntimeError("Duplicate Parquet event IDs; refusing one-to-many join")
 db=phase4g.db_rows()
 db_by_id={str(g["game_id"]):g for g in db}
 if len(db_by_id)!=len(db): raise RuntimeError("Duplicate NBA game IDs in isolated DB")
 rows=[]; counts=Counter(); season_counts=defaultdict(Counter); split_counts=defaultdict(Counter)
 for match in cross.get("resolved_rows",[]):
  if match.get("status")!="EXACT_SCORE_AND_SOURCE_ID_PRESENT": continue
  nba_id=str(match["nba_game_id"]); event_id=str(match["espn_event_id"])
  g=db_by_id.get(nba_id); line=lines.get(event_id)
  if g is None or line is None: counts["JOIN_INTEGRITY_FAILURE"]+=1; continue
  if line["home_point"] is None or line["over_under"] is None or line["n_books"] is None:
   counts["INCOMPLETE_LINE"]+=1; continue
  if abs(float(line["home_point"]))>40 or not 150<=float(line["over_under"])<=300 or int(line["n_books"])<1:
   counts["INVALID_LINE"]+=1; continue
  if int(g["home_score"])!=int(match["score"][0]) or int(g["away_score"])!=int(match["score"][1]):
   counts["SCORE_RECHECK_FAILURE"]+=1; continue
  season=str(g["season"]); split=split_for_season(season)
  if split=="EXCLUDED": counts["UNEXPECTED_SEASON"]+=1; continue
  ats=classify_ats(g["home_score"],g["away_score"],line["home_point"])
  ou=classify_total(g["home_score"],g["away_score"],line["over_under"])
  row={
   "nba_game_id":nba_id,"espn_event_id":event_id,"season":season,
   "split":split,"game_date":str(g["game_date"]),
   "commence_time_utc":g["commence_time_utc"].isoformat(),
   "home_team":g["home_team"],"away_team":g["away_team"],
   "home_score":int(g["home_score"]),"away_score":int(g["away_score"]),
   "home_point":float(line["home_point"]),
   "home_team_spread":-float(line["home_point"]),
   "over_under":float(line["over_under"]),
   "actual_total":int(g["home_score"])+int(g["away_score"]),
   "bookmaker_count":int(line["n_books"]),
   "home_favorite":bool(line["home_favorite"]),
   "spread_source":line["spread_source"],
   "closing_snapshot":line["snapshot"],
   "ats_result":ats,"total_result":ou,
   "spread_two_way_prices_available":False,
   "total_two_way_prices_available":False,
   "moneyline_prices_available":False
  }
  rows.append(row); counts["INCLUDED"]+=1
  season_counts[season][ats]+=1; season_counts[season][ou]+=1
  split_counts[split]["games"]+=1; split_counts[split]["home_cover"]+=ats=="HOME_COVER"
  split_counts[split]["away_cover"]+=ats=="AWAY_COVER"; split_counts[split]["spread_push"]+=ats=="PUSH"
  split_counts[split]["over"]+=ou=="OVER"; split_counts[split]["under"]+=ou=="UNDER"; split_counts[split]["total_push"]+=ou=="PUSH"
 # Ensure one-to-one output and chronological split order.
 ids=[r["nba_game_id"] for r in rows]
 if len(ids)!=len(set(ids)): raise RuntimeError("Duplicate NBA game IDs in benchmark dataset")
 rows.sort(key=lambda r:(r["commence_time_utc"],r["nba_game_id"]))
 report={
  "phase":"V8.0_PHASE5","mode":"READ_ONLY_CHRONOLOGICAL_MARKET_BENCHMARK_DATASET",
  "source_revision":"7be25dae2ebe5f6027f5343a4ab3195caa61aee5",
  "input_crosswalk_games":len(cross.get("resolved_rows",[])),
  "input_crosswalk_exact_id_matches":sum(r.get("status")=="EXACT_SCORE_AND_SOURCE_ID_PRESENT" for r in cross.get("resolved_rows",[])),
  "dataset_rows":len(rows),"row_counts":dict(counts),
  "by_split":{k:dict(v) for k,v in split_counts.items()},
  "by_season":{k:dict(v) for k,v in season_counts.items()},
  "splits":{"TRAIN":["2020-21","2021-22","2022-23"],"VALIDATION":["2023-24"],"TEST":["2024-25"],"FINAL_HOLDOUT":["2025-26"]},
  "feature_policy":"Only pregame closing consensus lines, teams, schedule metadata and historical final scores are included. Model features are not yet assembled.",
  "settlement_policy":{"spread":"home_score - away_score + home_point; positive=HOME_COVER, negative=AWAY_COVER, zero=PUSH","total":"home_score + away_score compared with over_under; equality=PUSH"},
  "price_availability":{"two_way_spread_prices":False,"two_way_total_prices":False,"moneyline_prices":False,"roi_calculable":False,"clv_calculable":False},
  "source_license":"NOASSERTION — no persistent import or redistribution until legal clearance",
  "database_writes":0,
  "acceptance":"DATASET_CANDIDATE_FOR_BENCHMARK_ONLY" if rows and not counts["JOIN_INTEGRITY_FAILURE"] and not counts["SCORE_RECHECK_FAILURE"] else "REJECTED"
 }
 (OUT/"market_benchmark_dataset.json").write_text(json.dumps({"report":report,"rows":rows},indent=2,default=str),encoding="utf-8")
 # CSV for inspection/analysis; output is ephemeral workflow artifact only.
 import csv
 with (OUT/"market_benchmark_dataset.csv").open("w",newline="",encoding="utf-8") as f:
  writer=csv.DictWriter(f,fieldnames=list(rows[0]) if rows else ["nba_game_id"])
  writer.writeheader(); writer.writerows(rows)
 print(json.dumps(report,indent=2,default=str))
 print(f"RESULT: PHASE 5 DATASET BUILD COMPLETE; rows={len(rows)}")
if __name__=="__main__": main()
