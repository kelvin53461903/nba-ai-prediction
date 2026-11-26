#!/usr/bin/env python3
"""Phase 4G: full six-season exact-score ESPN crosswalk and market-ID coverage.

For each isolated NBA result, query ESPN scoreboard for the DB Eastern date
plus/minus two calendar days. Accept a game identity only when exactly one
event has exact home team, away team and both final scores. Then test whether
its ESPN event ID is present in the pinned consensus closing-lines Parquet.
No line is joined by date alone; no database writes.
"""
from __future__ import annotations
import json, os, time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import certifi, duckdb, psycopg, requests

PARQUET_URL=(
 "https://raw.githubusercontent.com/sportsdataverse/hoopR-nba-data/"
 "7be25dae2ebe5f6027f5343a4ab3195caa61aee5/"
 "nba/betting_lines/closing_lines_odds_api.parquet"
)
API="https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
CACHE=Path(".cache_v80_phase4g"); OUT=Path("artifacts/v80_phase4g")
ALIASES={"LA Clippers":"Los Angeles Clippers","LA Lakers":"Los Angeles Lakers"}
def canon(s):
 s=" ".join(str(s or "").strip().split()); return ALIASES.get(s,s)

def parse_events(payload):
 out=[]
 for ev in payload.get("events",[]) or []:
  comps=ev.get("competitions") or []
  if not comps: continue
  sides={}
  for t in comps[0].get("competitors",[]) or []:
   side=t.get("homeAway"); team=t.get("team") or {}; score=t.get("score")
   if side in ("home","away"):
    sides[side]={"name":canon(team.get("displayName") or team.get("name")),
     "score":int(score) if str(score or "").isdigit() else None}
  out.append({"event_id":str(ev.get("id") or ""),
   "home":sides.get("home",{}).get("name"),"away":sides.get("away",{}).get("name"),
   "home_score":sides.get("home",{}).get("score"),"away_score":sides.get("away",{}).get("score"),
   "utc_date":ev.get("date")})
 return out

def exact_candidates(game, events):
 return [e for e in events if canon(e.get("home"))==canon(game.get("home_team"))
  and canon(e.get("away"))==canon(game.get("away_team"))
  and e.get("home_score") is not None and e.get("away_score") is not None
  and int(e["home_score"])==int(game["home_score"])
  and int(e["away_score"])==int(game["away_score"])]

def db_rows():
 url=os.environ.get("V80_HISTORICAL_IMPORT_DATABASE_URL","").strip()
 if not url: raise RuntimeError("Missing isolated V80_HISTORICAL_IMPORT_DATABASE_URL")
 with psycopg.connect(url,sslmode="verify-full",sslrootcert=certifi.where(),
  options="-c default_transaction_read_only=on",connect_timeout=20,
  application_name="NBA_AI_V80_PHASE4G_FULL_CROSSWALK") as conn:
  with conn.cursor() as cur:
   cur.execute("""
    SELECT game_id::text,season,home_team,away_team,
      (commence_time_utc AT TIME ZONE 'America/New_York')::date AS game_date,
      commence_time_utc,home_score,away_score
    FROM public.nba_game_results
    WHERE season IN ('2020-21','2021-22','2022-23','2023-24','2024-25','2025-26')
    ORDER BY commence_time_utc
   """)
   names=[d.name for d in cur.description]
   return [dict(zip(names,row)) for row in cur.fetchall()]

def fetch_one(day):
 s=requests.Session(); s.headers["User-Agent"]="NBA-AI-V8.0-Phase4G/1.0"
 try:
  r=s.get(API,params={"dates":day.replace("-",""),"limit":500},timeout=35)
  r.raise_for_status(); return day,parse_events(r.json()),None
 except Exception as e: return day,[],f"{type(e).__name__}: {e}"
 finally: s.close()

def main():
 CACHE.mkdir(exist_ok=True); OUT.mkdir(parents=True,exist_ok=True)
 p=CACHE/"closing_lines_odds_api.parquet"
 if not p.exists():
  r=requests.get(PARQUET_URL,timeout=180); r.raise_for_status(); p.write_bytes(r.content)
 con=duckdb.connect()
 src=con.execute("SELECT CAST(game_id AS VARCHAR),commence_time FROM read_parquet(?)",[str(p)]).fetchall()
 source_ids={str(x[0]) for x in src}
 source_dupes=con.execute("SELECT COUNT(*) FROM (SELECT game_id FROM read_parquet(?) GROUP BY game_id HAVING COUNT(*)>1)",[str(p)]).fetchone()[0]
 games=db_rows()
 query_dates=set()
 for g in games:
  for off in range(-2,3): query_dates.add((g["game_date"]+timedelta(days=off)).isoformat())
 events_by_id={}; failed=[]
 with ThreadPoolExecutor(max_workers=8) as pool:
  futures=[pool.submit(fetch_one,d) for d in sorted(query_dates)]
  for i,f in enumerate(as_completed(futures),1):
   day,events,error=f.result()
   if error: failed.append({"date":day,"error":error})
   for e in events:
    if e["event_id"]: events_by_id[e["event_id"]]=e
   if i%100==0: print(f"ESPN date queries {i}/{len(query_dates)}")
 rows=[]
 for g in games:
  pool=[]
  for off in range(-2,3):
   pool.extend(events_by_id.values()) if False else None
  # Event timestamp is used to narrow candidate pool to UTC calendar date
  # within +/- 2 days; exact teams and scores remain mandatory.
  from datetime import datetime
  candidates=[]
  for e in events_by_id.values():
   try: event_day=datetime.fromisoformat(e["utc_date"].replace("Z","+00:00")).date()
   except Exception: continue
   if abs((event_day-g["game_date"]).days)<=2: candidates.append(e)
  matches=exact_candidates(g,candidates)
  if len(matches)==1:
   e=matches[0]; present=e["event_id"] in source_ids
   status="EXACT_SCORE_AND_SOURCE_ID_PRESENT" if present else "EXACT_SCORE_SOURCE_ID_MISSING"
   try: offset=(datetime.fromisoformat(e["utc_date"].replace("Z","+00:00")).date()-g["game_date"]).days
   except Exception: offset=None
   rows.append({"nba_game_id":g["game_id"],"season":g["season"],"db_date":g["game_date"].isoformat(),
    "home":g["home_team"],"away":g["away_team"],"score":[g["home_score"],g["away_score"]],
    "espn_event_id":e["event_id"],"espn_utc_date":e["utc_date"],"utc_calendar_offset_days":offset,
    "market_parquet_event_id_present":present,"status":status})
  else:
   rows.append({"nba_game_id":g["game_id"],"season":g["season"],"db_date":g["game_date"].isoformat(),
    "home":g["home_team"],"away":g["away_team"],"candidate_count":len(matches),
    "status":"NO_EXACT_SCORE_MATCH" if not matches else "AMBIGUOUS_EXACT_SCORE_MATCH"})
 counts=Counter(r["status"] for r in rows)
 report={"phase":"V8.0_PHASE4G","mode":"READ_ONLY_FULL_SIX_SEASON_EXACT_SCORE_CROSSWALK",
  "database_games":len(games),"unique_db_dates":len({g["game_date"] for g in games}),
  "espn_scoreboard_dates_queried":len(query_dates),"espn_events_loaded":len(events_by_id),
  "scoreboard_query_failures":failed,"source_parquet_rows":len(src),"source_duplicate_event_ids":source_dupes,
  "status_counts":dict(counts),
  "by_season":{s:dict(Counter(r["status"] for r in rows if r["season"]==s)) for s in sorted({r["season"] for r in rows})},
  "market_line_link_eligible_count":counts["EXACT_SCORE_AND_SOURCE_ID_PRESENT"],
  "resolved_rows":rows,
  "unresolved_or_ambiguous":[r for r in rows if r["status"] not in ("EXACT_SCORE_AND_SOURCE_ID_PRESENT","EXACT_SCORE_SOURCE_ID_MISSING")],
  "source_id_missing":[r for r in rows if r["status"]=="EXACT_SCORE_SOURCE_ID_MISSING"],
  "database_writes":0,
  "acceptance":"REQUIRES_REVIEW" if failed or counts["AMBIGUOUS_EXACT_SCORE_MATCH"] or counts["NO_EXACT_SCORE_MATCH"] else "ALL_DB_GAMES_SCORE_CROSSWALKED",
  "limitations":["Consensus Parquet contains consensus spread/total lines, not two-sided prices.","No moneyline prices in this source.","Source repository licence metadata is NOASSERTION; legal clearance required.","A source ID presence is a candidate market-line join, not proof of two-way price availability or ROI."]}
 out=OUT/"full_six_season_exact_score_crosswalk.json"
 out.write_text(json.dumps(report,indent=2,default=str),encoding="utf-8")
 print(json.dumps({k:v for k,v in report.items() if k not in ("unresolved_or_ambiguous","source_id_missing")},indent=2,default=str))
 print(f"RESULT: PHASE 4G FULL EXACT-SCORE CROSSWALK COMPLETE; report={out}")
if __name__=="__main__": main()
