#!/usr/bin/env python3
"""Phase 4E targeted diagnostic for the 2022-12-01 ESPN gap and 12 source-ID gaps.

Read-only only. It probes adjacent ESPN scoreboard date parameters and emits
the exact database rows and source IDs that remain unresolved. It does not
auto-attach a line using date/team heuristics.
"""
from __future__ import annotations
import json, os
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import certifi, duckdb, psycopg, requests

PARQUET_URL = (
 "https://raw.githubusercontent.com/sportsdataverse/hoopR-nba-data/"
 "7be25dae2ebe5f6027f5343a4ab3195caa61aee5/"
 "nba/betting_lines/closing_lines_odds_api.parquet"
)
API = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
CACHE=Path(".cache_v80_phase4e"); OUT=Path("artifacts/v80_phase4e")
ET=ZoneInfo("America/New_York")

def get_events(payload):
 out=[]
 for ev in payload.get("events",[]) or []:
  comps=ev.get("competitions") or []
  if not comps: continue
  comp=comps[0]; sides={}
  for t in comp.get("competitors",[]) or []:
   side=t.get("homeAway"); team=t.get("team") or {}
   if side in ("home","away"):
    score=t.get("score")
    sides[side]={"team":team.get("displayName") or team.get("name"),
                 "score":int(score) if str(score or "").isdigit() else None}
  dt=datetime.fromisoformat(str(ev.get("date") or comp.get("date")).replace("Z","+00:00"))
  out.append({"event_id":str(ev.get("id")),"utc_date":ev.get("date"),
    "et_date":dt.astimezone(ET).date().isoformat(),
    "home":sides.get("home",{}).get("team"),"away":sides.get("away",{}).get("team"),
    "home_score":sides.get("home",{}).get("score"),"away_score":sides.get("away",{}).get("score")})
 return out

def db_rows():
 url=os.environ.get("V80_HISTORICAL_IMPORT_DATABASE_URL","").strip()
 if not url: raise RuntimeError("Missing V80_HISTORICAL_IMPORT_DATABASE_URL")
 with psycopg.connect(url,sslmode="verify-full",sslrootcert=certifi.where(),
  options="-c default_transaction_read_only=on",connect_timeout=20,
  application_name="NBA_AI_V80_PHASE4E_TARGETED_GAP_AUDIT") as conn:
  with conn.cursor() as cur:
   cur.execute("""
    SELECT game_id::text,season,home_team,away_team,
     (commence_time_utc AT TIME ZONE 'America/New_York')::date AS game_date,
     home_score,away_score
    FROM public.nba_game_results
    WHERE (commence_time_utc AT TIME ZONE 'America/New_York')::date='2022-12-01'
       OR game_id::text IN (
          '127530','127624','127639','157585','127681','127693',
          '127707','127750','127826','264524','473871','857572'
       )
    ORDER BY commence_time_utc
   """)
   names=[d.name for d in cur.description]
   return [dict(zip(names,row)) for row in cur.fetchall()]

def main():
 CACHE.mkdir(exist_ok=True); OUT.mkdir(parents=True,exist_ok=True)
 p=CACHE/"closing_lines_odds_api.parquet"
 if not p.exists():
  r=requests.get(PARQUET_URL,timeout=180); r.raise_for_status(); p.write_bytes(r.content)
 con=duckdb.connect()
 source=con.execute("SELECT CAST(game_id AS VARCHAR),commence_time FROM read_parquet(?)",[str(p)]).fetchall()
 source_ids={str(x[0]):x[1] for x in source}
 rows=db_rows()
 sess=requests.Session(); sess.headers["User-Agent"]="NBA-AI-V8.0-Phase4E/1.0"
 probes=[]
 for requested in ("20221130","20221201","20221202"):
  try:
   r=sess.get(API,params={"dates":requested,"limit":500},timeout=35); r.raise_for_status()
   events=get_events(r.json())
   probes.append({"requested_date":requested,"event_count":len(events),
     "events_for_et_dec1":[e for e in events if e["et_date"]=="2022-12-01"],
     "events_for_et_adjacent":[e for e in events if e["et_date"] in ("2022-11-30","2022-12-02")]})
  except Exception as e:
   probes.append({"requested_date":requested,"error":f"{type(e).__name__}: {e}"})
 # Explicitly include all 11 DB rows on the problematic date and report source-ID presence.
 gap_rows=[r for r in rows if str(r["game_date"])=="2022-12-01"]
 for row in gap_rows: row["source_event_id_match"] = None
 report={
  "phase":"V8.0_PHASE4E","mode":"READ_ONLY_TARGETED_DIAGNOSTIC",
  "scoreboard_date_probes":probes,
  "database_rows_on_2022_12_01":gap_rows,
  "database_rows_sample_for_early_season_id_gaps": [r for r in rows if str(r["game_date"])!="2022-12-01"],
  "source_parquet_event_id_count":len(source_ids),
  "source_event_id_examples":list(source_ids.items())[:10],
  "no_auto_join":True,"database_writes":0,
  "acceptance":"DIAGNOSTIC_ONLY_NO_MARKET_LINE_LINKS_CREATED",
  "next_gate":"Resolve ESPN date-feed gap and event-ID provenance before joining any market rows."
 }
 out=OUT/"targeted_espn_gap_diagnostic.json"
 out.write_text(json.dumps(report,indent=2,default=str),encoding="utf-8")
 print(json.dumps({k:v for k,v in report.items() if k not in ("database_rows_on_2022_12_01","database_rows_sample_for_early_season_id_gaps")},indent=2,default=str))
 print("GAP_DATABASE_ROWS",json.dumps(gap_rows,default=str))
 print(f"RESULT: PHASE 4E TARGETED DIAGNOSTIC COMPLETE; report={out}")
if __name__=="__main__": main()
