#!/usr/bin/env python3
"""Phase 6C: leak-safe rolling market-residual and Elo features.

All features for a calendar date are computed before any result from that
date is added to team histories/Elo. Uses historical scores and closing
consensus lines only; no player/injury data or bookmaker prices.
"""
from __future__ import annotations
import json
from collections import defaultdict, deque
from datetime import date
from pathlib import Path
import math

SOURCE=Path("artifacts/v80_phase5/market_benchmark_dataset.json")
OUT=Path("artifacts/v80_phase6c")
WINDOWS=(5,10,20)
K_FACTOR=20.0
HOME_ADVANTAGE=65.0

def _mean(values):
 return sum(values)/len(values) if values else None

def _rate(values):
 return sum(values)/len(values) if values else None

def enrich_rows(rows):
 ordered=sorted(rows,key=lambda r:(r["game_date"],r["commence_time_utc"],r["nba_game_id"]))
 hist=defaultdict(lambda:deque(maxlen=max(WINDOWS)))
 elo=defaultdict(lambda:1500.0)
 out=[]; i=0
 while i<len(ordered):
  day=ordered[i]["game_date"]; batch=[]
  while i<len(ordered) and ordered[i]["game_date"]==day:
   g=ordered[i]; home=g["home_team"]; away=g["away_team"]
   def team_features(team):
    q=list(hist[team]); result={}
    result["elo"]=elo[team]
    result["rest_days"]=min(14,max(0,(date.fromisoformat(day)-date.fromisoformat(q[-1]["date"])).days)) if q else None
    for w in WINDOWS:
     v=q[-w:]
     prefix=f"prev{w}_"
     result[prefix+"win_rate"]=_rate([x["win"] for x in v])
     result[prefix+"points_for_avg"]=_mean([x["pf"] for x in v])
     result[prefix+"points_against_avg"]=_mean([x["pa"] for x in v])
     result[prefix+"net_points_avg"]=_mean([x["pf"]-x["pa"] for x in v])
     result[prefix+"ats_cover_rate"]=_rate([x["ats_cover"] for x in v if x["ats_cover"] is not None])
     result[prefix+"ats_margin_avg"]=_mean([x["ats_margin"] for x in v])
     result[prefix+"over_rate"]=_rate([x["over"] for x in v if x["over"] is not None])
     result[prefix+"total_residual_avg"]=_mean([x["total_residual"] for x in v])
    return result
   hf=team_features(home); af=team_features(away); row=dict(g)
   for k,v in hf.items(): row["home_"+k]=v
   for k,v in af.items(): row["away_"+k]=v
   for key in ["elo","rest_days"]:
    hv=hf[key]; av=af[key]
    row["pregame_"+key+"_diff"]=(hv-av) if hv is not None and av is not None else None
   for key in ["win_rate","net_points_avg","ats_cover_rate","ats_margin_avg","over_rate","total_residual_avg"]:
    for w in WINDOWS:
     k=f"prev{w}_{key}"; hv=hf[k]; av=af[k]
     row[f"pregame_{k}_diff"]=(hv-av) if hv is not None and av is not None else None
   batch.append((row,g))
   i+=1
  # Same-date outcomes are appended only after every game that date is featured.
  elo_updates=[]
  for row,g in batch:
   home=g["home_team"]; away=g["away_team"]
   margin=int(g["home_score"])-int(g["away_score"])
   total=int(g["home_score"])+int(g["away_score"])
   spread_margin=margin+float(g["home_point"])
   total_residual=total-float(g["over_under"])
   home_ats=1.0 if spread_margin>0 else (0.0 if spread_margin<0 else None)
   away_ats=1.0 if spread_margin<0 else (0.0 if spread_margin>0 else None)
   over=1.0 if total_residual>0 else (0.0 if total_residual<0 else None)
   hist[home].append({"date":day,"pf":int(g["home_score"]),"pa":int(g["away_score"]),
    "win":1.0 if margin>0 else (0.0 if margin<0 else .5),"ats_cover":home_ats,
    "ats_margin":spread_margin,"over":over,"total_residual":total_residual})
   hist[away].append({"date":day,"pf":int(g["away_score"]),"pa":int(g["home_score"]),
    "win":1.0 if margin<0 else (0.0 if margin>0 else .5),"ats_cover":away_ats,
    "ats_margin":-spread_margin,"over":over,"total_residual":total_residual})
   eh=elo[home]; ea=elo[away]
   expected=1.0/(1.0+10.0**((ea-(eh+HOME_ADVANTAGE))/400.0))
   actual=1.0 if margin>0 else (0.0 if margin<0 else .5)
   elo_updates.append((home,away,eh+K_FACTOR*(actual-expected),ea-K_FACTOR*(actual-expected)))
  for home,away,new_h,new_a in elo_updates:
   elo[home]=new_h; elo[away]=new_a
  out.extend(row for row,_ in batch)
 return out

def main():
 OUT.mkdir(parents=True,exist_ok=True)
 if not SOURCE.exists(): raise RuntimeError("Missing Phase 5 benchmark dataset")
 obj=json.loads(SOURCE.read_text(encoding="utf-8"))
 if obj.get("report",{}).get("acceptance")!="DATASET_CANDIDATE_FOR_BENCHMARK_ONLY" or not obj.get("rows"):
  raise RuntimeError("Phase 5 dataset not accepted")
 rows=enrich_rows(obj["rows"])
 if len(rows)!=len(obj["rows"]) or len({r["nba_game_id"] for r in rows})!=len(rows):
  raise RuntimeError("Row count or game ID integrity failure")
 report={"phase":"V8.0_PHASE6C","mode":"LEAK_SAFE_ROLLING_MARKET_RESIDUAL_AND_ELO",
  "row_count":len(rows),"same_date_results_excluded":True,"windows":list(WINDOWS),
  "features":["rolling 5/10/20 win rates","rolling points for/against/net points",
   "rolling ATS cover rate and ATS margin","rolling Over rate and total residual",
   "pregame Elo ratings and differences","rest days"],
  "database_writes":0,
  "limitations":["No player injury, availability, roster or individual player metrics.",
   "Closing consensus lines are features, not two-way prices.",
   "No ROI/CLV can be calculated; source licence remains unresolved."]}
 (OUT/"rolling_market_elo_features.json").write_text(json.dumps({**report,"rows":rows},indent=2),encoding="utf-8")
 print(json.dumps(report,indent=2))
 print("RESULT: PHASE 6C LEAK-SAFE MARKET RESIDUAL AND ELO FEATURES COMPLETE")
if __name__=="__main__": main()
