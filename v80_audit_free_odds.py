#!/usr/bin/env python3
"""Audit free CC-BY-4.0 NBA consensus closing-lines datasets before any DB import.

This stage is deliberately read-only: it downloads the published 2024-25 and
2025-26 CSVs, validates market fields and cutoff, and matches rows to the
isolated 2,459-game BDL results CSV by UTC tipoff + normalized home/away teams.
It never fabricates bookmaker prices; moneyline fields are fair no-vig odds /
probabilities as labelled by the upstream dataset.
"""
from __future__ import annotations
import csv, json, re, urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

CUTOFF = datetime(2026, 4, 2, tzinfo=timezone.utc)
GAMES_CSV = Path("data/nba_v80_historical_games_cutoff_2026-04-01.csv")
SOURCES = {
 "2024-25": "https://huggingface.co/datasets/minmaxxxer/nba-closing-lines-ats-2024-25/resolve/main/nba_2024_25_closing_lines_ats.csv",
 "2025-26": "https://huggingface.co/datasets/Cameronkelly92/nba-closing-lines-ats-2025-26/resolve/main/nba_2025_26_closing_lines_ats.csv",
}
REQUIRED = {
 "game_id","start_time_utc","season","season_type","home_team","away_team",
 "home_score","away_score","bookmakers","open_home_win_prob","close_home_win_prob",
 "close_fair_home_odds","close_fair_away_odds","open_spread_home","close_spread_home",
 "close_home_cover_prob","open_total","close_total","close_over_prob",
 "moneyline_winner","ats_result","total_result"
}
def norm(s):
 return re.sub(r"[^a-z]", "", s.lower().replace("la ", "los angeles ").replace("ny ", "new york "))
def dt(s):
 return datetime.fromisoformat(s.replace("Z","+00:00")).astimezone(timezone.utc)
def download(url):
 req=urllib.request.Request(url,headers={"User-Agent":"NBA-AI-V8.0-research-audit/1.0"})
 with urllib.request.urlopen(req,timeout=45) as r: return r.read().decode("utf-8-sig")
def main():
 if not GAMES_CSV.exists(): raise SystemExit("Missing approved 2,459-game results CSV")
 games={}
 with GAMES_CSV.open(newline="",encoding="utf-8-sig") as f:
  for r in csv.DictReader(f):
   key=(dt(r["commence_time_utc"]).isoformat(),norm(r["home_team"]),norm(r["away_team"]))
   games[key]=r
 report={"cutoff_exclusive_utc":CUTOFF.isoformat(),"sources":{},"matched_to_2459_games":0,"unmatched_examples":[]}
 seen_global=set()
 for season,url in SOURCES.items():
  raw=download(url)
  rows=list(csv.DictReader(raw.splitlines()))
  if not rows: raise SystemExit(f"{season}: empty dataset")
  missing=REQUIRED-set(rows[0])
  if missing: raise SystemExit(f"{season}: missing columns {sorted(missing)}")
  eligible=[]; matched=0; unmatched=[]; invalid=Counter(); keys=set(); exact_matches=0; fallback_matches=0; score_mismatches=0
  for r in rows:
   try:
    tip=dt(r["start_time_utc"])
    if tip>=CUTOFF: continue
    if r["season"]!=season: invalid["season_mismatch"]+=1; continue
    nums=[float(r[k]) for k in ("open_home_win_prob","close_home_win_prob","close_fair_home_odds","close_fair_away_odds","open_spread_home","close_spread_home","close_home_cover_prob","open_total","close_total","close_over_prob")]
    if not all(x==x for x in nums): raise ValueError()
    if not (0<nums[0]<1 and 0<nums[1]<1 and nums[2]>1 and nums[3]>1 and 150<=nums[7]<=300 and 150<=nums[8]<=300 and 0<nums[5+1]<1 and 0<nums[9]<1):
     raise ValueError()
    if int(r["bookmakers"])<1: raise ValueError()
    if r["moneyline_winner"] not in ("home","away") or r["ats_result"] not in ("home","away","push") or r["total_result"] not in ("over","under","push"): raise ValueError()
    key=(tip.isoformat(),norm(r["home_team"]),norm(r["away_team"]))
    if key in keys: invalid["duplicate_match_key"]+=1; continue
    keys.add(key); eligible.append(r)
    if key in games:
     g=games[key]
     if int(g["home_score"])!=int(r["home_score"]) or int(g["away_score"])!=int(r["away_score"]):
      invalid["score_mismatch"]+=1; score_mismatches+=1
     else:
      matched+=1; exact_matches+=1; seen_global.add((season,key))
    else:
     # Unique team + score match within 24h handles source tip-time rounding.
     candidates=[]
     for gkey,g in games.items():
      if gkey[1:]==(norm(r["home_team"]),norm(r["away_team"])) and abs((dt(g["commence_time_utc"])-tip).total_seconds())<=86400:
       if int(g["home_score"])==int(r["home_score"]) and int(g["away_score"])==int(r["away_score"]): candidates.append((gkey,g))
     if len(candidates)==1:
      matched+=1; fallback_matches+=1; seen_global.add((season,candidates[0][0]))
     else:
      if len(unmatched)<10: unmatched.append({"tip":tip.isoformat(),"home":r["home_team"],"away":r["away_team"],"candidate_count":len(candidates)})
   except Exception: invalid["invalid_market_or_row"]+=1
  report["sources"][season]={"url":url,"license":"CC-BY-4.0 (dataset card)","published_rows":len(rows),"eligible_before_cutoff":len(eligible),"matched_to_verified_game_and_score":matched,"exact_matches":exact_matches,"unique_team_score_date_fallback_matches":fallback_matches,"unmatched_count":len(eligible)-matched,"score_mismatch_count":score_mismatches,"unmatched_examples":unmatched,"rejected":dict(invalid),"markets":["moneyline fair probabilities/odds","spread line + no-vig home-cover probability","total line + no-vig over probability"]}
 report["matched_to_2459_games"]=len(seen_global)
 report["note"]="Audit only; no DB writes. Market probabilities/lines are consensus closes, not executable bookmaker prices. Verify source methodology and preserve attribution."
 Path("v80_free_odds_audit.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
 print(json.dumps(report,indent=2))
 if report["matched_to_2459_games"]<1000: raise SystemExit("FAIL: insufficient matched games; refuse database import")
 print("PASS: free historical odds audit threshold")
if __name__=="__main__": main()
