#!/usr/bin/env python3
"""Phase 4F: resolve known ESPN/NBA date-offset and event-ID gaps.

A candidate is accepted only when home/away teams AND both final scores match
exactly, and exactly one ESPN event exists across the DB date +/- one day.
The Parquet event ID must also exist before a market-line link is eligible.
Read-only; no database writes.
"""
from __future__ import annotations
import json, os
from collections import Counter
from datetime import date, timedelta, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import certifi, duckdb, psycopg, requests

PARQUET_URL=(
 "https://raw.githubusercontent.com/sportsdataverse/hoopR-nba-data/"
 "7be25dae2ebe5f6027f5343a4ab3195caa61aee5/"
 "nba/betting_lines/closing_lines_odds_api.parquet"
)
API="https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
CACHE=Path(".cache_v80_phase4f"); OUT=Path("artifacts/v80_phase4f")
GAP_IDS=("127530","127624","127639","157585","127681","127693","127707","127750","127826","264524","473871","857572")

def canon(s):
 return " ".join(str(s or "").strip().split())

def parse_events(payload):
 out=[]
 for ev in payload.get("events",[]) or []:
  comps=ev.get("competitions") or []
  if not comps: continue
  comp=comps[0]; sides={}
  for t in comp.get("competitors",[]) or []:
   side=t.get("homeAway"); team=t.get("team") or {}; score=t.get("score")
   if side in ("home","away"):
    sides[side]={"name":canon(team.get("displayName") or team.get("name")),
      "score":int(score) if str(score or "").isdigit() else None}
  out.append({"event_id":str(ev.get("id") or ""),
    "home":sides.get("home",{}).get("name"),"away":sides.get("away",{}).get("name"),
    "home_score":sides.get("home",{}).get("score"),"away_score":sides.get("away",{}).get("score"),
    "utc_date":ev.get("date")})
 return out

def candidate_match(game, events):
 return [e for e in events if
  canon(e.get("home"))==canon(game.get("home_team")) and
  canon(e.get("away"))==canon(game.get("away_team")) and
  e.get("home_score") is not None and e.get("away_score") is not None and
  int(e["home_score"])==int(game["home_score"]) and
  int(e["away_score"])==int(game["away_score"])]

def db_rows():
 url=os.environ.get("V80_HISTORICAL_IMPORT_DATABASE_URL","").strip()
 if not url: raise RuntimeError("Missing isolated V80_HISTORICAL_IMPORT_DATABASE_URL")
 with psycopg.connect(url,sslmode="verify-full",sslrootcert=certifi.where(),
  options="-c default_transaction_read_only=on",connect_timeout=20,
  application_name="NBA_AI_V80_PHASE4F_DATE_OFFSET_AUDIT") as conn:
  with conn.cursor() as cur:
   cur.execute("""
    SELECT game_id::text,season,home_team,away_team,
      (commence_time_utc AT TIME ZONE 'America/New_York')::date AS game_date,
      commence_time_utc,home_score,away_score
    FROM public.nba_game_results
    WHERE (commence_time_utc AT TIME ZONE 'America/New_York')::date='2022-12-01'
       OR game_id::text = ANY(%s)
    ORDER BY commence_time_utc
   """,(list(GAP_IDS),))
   names=[d.name for d in cur.description]
   return [dict(zip(names,row)) for row in cur.fetchall()]

def main():
 CACHE.mkdir(exist_ok=True); OUT.mkdir(parents=True,exist_ok=True)
 p=CACHE/"closing_lines_odds_api.parquet"
 if not p.exists():
  r=requests.get(PARQUET_URL,timeout=180); r.raise_for_status(); p.write_bytes(r.content)
 con=duckdb.connect()
 source_ids={str(x[0]) for x in con.execute(
  "SELECT CAST(game_id AS VARCHAR) FROM read_parquet(?)",[str(p)]).fetchall()}
 games=db_rows()
 dates=set()
 for g in games:
  d=g["game_date"]
  for off in (-1,0,1): dates.add((d+timedelta(days=off)).isoformat())
 session=requests.Session(); session.headers["User-Agent"]="NBA-AI-V8.0-Phase4F/1.0"
 events_by_day={}
 errors=[]
 for day in sorted(dates):
  try:
   r=session.get(API,params={"dates":day.replace("-",""),"limit":500},timeout=30)
   r.raise_for_status(); events_by_day[day]=parse_events(r.json())
  except Exception as e: errors.append({"date":day,"error":f"{type(e).__name__}: {e}"})
 rows=[]
 for g in games:
  d=g["game_date"]
  pool=[]
  for off in (-1,0,1): pool.extend(events_by_day.get((d+timedelta(days=off)).isoformat(),[]))
  # De-duplicate event IDs returned by overlapping date queries.
  unique={e["event_id"]:e for e in pool if e["event_id"]}
  matches=candidate_match(g,list(unique.values()))
  if len(matches)==1:
   ev=matches[0]; source_present=ev["event_id"] in source_ids
   status="EXACT_SCORE_TEAM_MATCH_SOURCE_ID_PRESENT" if source_present else "EXACT_SCORE_TEAM_MATCH_SOURCE_ID_MISSING"
   offset=None
   try:
    dt=datetime.fromisoformat(ev["utc_date"].replace("Z","+00:00"))
    offset=(dt.date()-d).days
   except Exception: pass
   rows.append({"nba_game_id":g["game_id"],"season":g["season"],"db_date":d.isoformat(),
    "commence_time_utc":g["commence_time_utc"].isoformat(),"home":g["home_team"],"away":g["away_team"],
    "database_score":[g["home_score"],g["away_score"]],"espn_score":[ev["home_score"],ev["away_score"]],
    "espn_event_id":ev["event_id"],"espn_utc_date":ev["utc_date"],"utc_calendar_date_offset_vs_db_date":offset,
    "source_parquet_has_event_id":source_present,"status":status})
  else:
   rows.append({"nba_game_id":g["game_id"],"season":g["season"],"db_date":d.isoformat(),
    "home":g["home_team"],"away":g["away_team"],"database_score":[g["home_score"],g["away_score"]],
    "candidate_count":len(matches),"status":"NO_EXACT_MATCH" if not matches else "AMBIGUOUS_EXACT_MATCH"})
 counts=Counter(x["status"] for x in rows)
 report={"phase":"V8.0_PHASE4F","mode":"READ_ONLY_TARGETED_EXACT_SCORE_CROSSWALK",
  "database_games_examined":len(games),"scoreboard_dates_requested":len(dates),
  "scoreboard_events_loaded":sum(len(x) for x in events_by_day.values()),
  "failed_scoreboard_dates":errors,"status_counts":dict(counts),
  "results_by_season":{s:dict(Counter(x["status"] for x in rows if x["season"]==s)) for s in sorted({x["season"] for x in rows})},
  "resolved_rows":rows,"market_line_link_eligible":[x for x in rows if x["status"]=="EXACT_SCORE_TEAM_MATCH_SOURCE_ID_PRESENT"],
  "database_writes":0,"acceptance":"REQUIRES_REVIEW" if errors or any(x["status"]!="EXACT_SCORE_TEAM_MATCH_SOURCE_ID_PRESENT" for x in rows) else "ALL_TARGETED_ROWS_EXACT_AND_SOURCE_ID_PRESENT",
  "guardrails":["Exact home and away team names and both scores required.","Exactly one ESPN event required across DB date +/- one day.","No date-only or team-only fallback.","No market line attached unless ESPN event ID exists in the pinned Parquet.","No Neon writes."]}
 out=OUT/"exact_score_date_offset_resolution.json"
 out.write_text(json.dumps(report,indent=2,default=str),encoding="utf-8")
 print(json.dumps({k:v for k,v in report.items() if k not in ("resolved_rows","market_line_link_eligible")},indent=2,default=str))
 print("DETAIL_ROWS",json.dumps(rows,default=str))
 print(f"RESULT: PHASE 4F EXACT-SCORE OFFSET AUDIT COMPLETE; report={out}")
if __name__=="__main__": main()
