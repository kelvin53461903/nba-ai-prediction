#!/usr/bin/env python3
"""Phase 6B: leak-safe rolling team form features for historical backtests.

Features for a game are computed only from games on strictly earlier dates.
All games on a date are scored before any same-date results are added to
team history. Dataset is ephemeral and never written to the production DB.
"""
from __future__ import annotations
import json
from collections import defaultdict, deque
from datetime import date
from pathlib import Path
import numpy as np

SOURCE=Path("artifacts/v80_phase5/market_benchmark_dataset.json")
OUT=Path("artifacts/v80_phase6b")
WINDOW=10

def enrich_rows(rows):
 ordered=sorted(rows,key=lambda r:(r["game_date"],r["commence_time_utc"],r["nba_game_id"]))
 history=defaultdict(lambda:deque(maxlen=WINDOW))
 enriched=[]
 i=0
 while i<len(ordered):
  day=ordered[i]["game_date"]; batch=[]
  while i<len(ordered) and ordered[i]["game_date"]==day:
   g=ordered[i]; h=history[g["home_team"]]; a=history[g["away_team"]]
   def stats(q):
    if not q: return {"games":0,"win_rate":None,"points_for_avg":None,"points_against_avg":None,"net_points_avg":None,"rest_days":None}
    return {"games":len(q),"win_rate":sum(x["win"] for x in q)/len(q),
     "points_for_avg":sum(x["pf"] for x in q)/len(q),
     "points_against_avg":sum(x["pa"] for x in q)/len(q),
     "net_points_avg":sum(x["pf"]-x["pa"] for x in q)/len(q),
     "rest_days":min(14,max(0,(date.fromisoformat(day)-date.fromisoformat(q[-1]["date"])).days))}
   hs=stats(h); as_=stats(a)
   row=dict(g)
   for k,v in hs.items(): row["home_prev_"+k]=v
   for k,v in as_.items(): row["away_prev_"+k]=v
   row["pregame_net_form_diff"]=(hs["net_points_avg"]-as_["net_points_avg"]) if hs["net_points_avg"] is not None and as_["net_points_avg"] is not None else None
   row["pregame_win_rate_diff"]=(hs["win_rate"]-as_["win_rate"]) if hs["win_rate"] is not None and as_["win_rate"] is not None else None
   row["pregame_rest_diff"]=(hs["rest_days"]-as_["rest_days"]) if hs["rest_days"] is not None and as_["rest_days"] is not None else None
   batch.append((row,g))
   i+=1
  # Update histories only after all same-day features are calculated.
  for row,g in batch:
   hs=history[g["home_team"]]; aw=history[g["away_team"]]
   hp=int(g["home_score"]); ap=int(g["away_score"])
   hs.append({"date":day,"pf":hp,"pa":ap,"win":int(hp>ap)})
   aw.append({"date":day,"pf":ap,"pa":hp,"win":int(ap>hp)})
  enriched.extend(x[0] for x in batch)
 return enriched

def main():
 OUT.mkdir(parents=True,exist_ok=True)
 if not SOURCE.exists(): raise RuntimeError("Missing Phase 5 dataset")
 obj=json.loads(SOURCE.read_text(encoding="utf-8"))
 if obj.get("report",{}).get("acceptance")!="DATASET_CANDIDATE_FOR_BENCHMARK_ONLY" or not obj.get("rows"):
  raise RuntimeError("Phase 5 dataset is not accepted")
 rows=enrich_rows(obj["rows"])
 if len(rows)!=len(obj["rows"]): raise RuntimeError("Row count changed during feature engineering")
 if len({r["nba_game_id"] for r in rows})!=len(rows): raise RuntimeError("Duplicate game IDs")
 out={"phase":"V8.0_PHASE6B","mode":"LEAK_SAFE_ROLLING_TEAM_FORM_FEATURES",
  "window_games":WINDOW,"rows":len(rows),"same_date_results_excluded":True,
  "features":["home/away previous-10-game win rate","points for/against averages","net points average","rest days","home-away form differences"],
  "source_dataset_rows":len(obj["rows"]),"database_writes":0,
  "limitations":["Features use prior final scores only; no player injuries or roster availability.","Historical team names are taken from source rows.","This is research feature engineering, not a live prediction model."]}
 (OUT/"leak_safe_team_form_dataset.json").write_text(json.dumps(out,indent=2),encoding="utf-8")
 print(json.dumps({k:v for k,v in out.items() if k!="rows"},indent=2))
 print("RESULT: PHASE 6B LEAK-SAFE FEATURE ENGINEERING COMPLETE")
if __name__=="__main__": main()
