#!/usr/bin/env python3
"""Import verified free consensus closing lines into isolated V8.0 Neon test DB."""
from __future__ import annotations
import csv, os, re, sys, urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import certifi
import psycopg
from psycopg.conninfo import conninfo_to_dict

DB_NAME="nba_v80"
DB_ROLE="v80_historical_import"
SECRET_NAME="V80_HISTORICAL_IMPORT_DATABASE_URL"
CUTOFF=datetime(2026,4,2,tzinfo=timezone.utc)
GAMES=Path("data/nba_v80_historical_games_cutoff_2026-04-01.csv")
SOURCES={
 "2024-25":("minmaxxxer/nba-closing-lines-ats-2024-25","https://huggingface.co/datasets/minmaxxxer/nba-closing-lines-ats-2024-25/resolve/main/nba_2024_25_closing_lines_ats.csv"),
 "2025-26":("Cameronkelly92/nba-closing-lines-ats-2025-26","https://huggingface.co/datasets/Cameronkelly92/nba-closing-lines-ats-2025-26/resolve/main/nba_2025_26_closing_lines_ats.csv"),
}
INSERT="""
INSERT INTO public.nba_historical_market_closes (
 game_id,season,home_team,away_team,commence_time_utc,source_dataset,source_url,license,
 bookmaker_count,open_home_win_prob,close_home_win_prob,close_fair_home_odds,
 close_fair_away_odds,open_spread_home,close_spread_home,close_home_cover_prob,
 open_total,close_total,close_over_prob,moneyline_winner,ats_result,total_result,home_score,away_score
) VALUES (
 %(game_id)s,%(season)s,%(home_team)s,%(away_team)s,%(commence_time_utc)s,%(source_dataset)s,%(source_url)s,%(license)s,
 %(bookmaker_count)s,%(open_home_win_prob)s,%(close_home_win_prob)s,%(close_fair_home_odds)s,
 %(close_fair_away_odds)s,%(open_spread_home)s,%(close_spread_home)s,%(close_home_cover_prob)s,
 %(open_total)s,%(close_total)s,%(close_over_prob)s,%(moneyline_winner)s,%(ats_result)s,%(total_result)s,%(home_score)s,%(away_score)s
) ON CONFLICT (game_id,source_dataset) DO NOTHING
"""
def norm(s):
 return re.sub(r"[^a-z]", "", s.lower().replace("la ","los angeles ").replace("ny ","new york "))
def parse_dt(s):
 d=datetime.fromisoformat(s.replace("Z","+00:00"))
 if d.tzinfo is None: raise ValueError("timezone missing")
 return d.astimezone(timezone.utc)
def download(url):
 req=urllib.request.Request(url,headers={"User-Agent":"NBA-AI-V8.0-Historical-Market-Import/1.0"})
 with urllib.request.urlopen(req,timeout=60) as response: return response.read().decode("utf-8-sig")
def load_games():
 if not GAMES.is_file(): raise RuntimeError("Approved historical games CSV is missing")
 with GAMES.open(newline="",encoding="utf-8-sig") as f: rows=list(csv.DictReader(f))
 if len(rows)!=2459: raise RuntimeError(f"Expected 2459 verified games; got {len(rows)}")
 return rows
def load_market_rows():
 games=load_games()
 exact={}
 by_teams={}
 for g in games:
  tip=parse_dt(g["commence_time_utc"])
  key=(tip.isoformat(),norm(g["home_team"]),norm(g["away_team"]))
  exact[key]=g
  by_teams.setdefault(key[1:],[]).append((tip,g))
 output=[]
 counts=Counter()
 for season,(source_name,url) in SOURCES.items():
  rows=list(csv.DictReader(download(url).splitlines()))
  required={"game_id","start_time_utc","season","season_type","home_team","away_team","home_score","away_score","bookmakers","open_home_win_prob","close_home_win_prob","close_fair_home_odds","close_fair_away_odds","open_spread_home","close_spread_home","close_home_cover_prob","open_total","close_total","close_over_prob","moneyline_winner","ats_result","total_result"}
  if not rows or required-set(rows[0]): raise RuntimeError(f"{season}: missing expected source fields")
  seen=set()
  for r in rows:
   tip=parse_dt(r["start_time_utc"])
   if tip>=CUTOFF or r["season"]!=season: continue
   key=(tip.isoformat(),norm(r["home_team"]),norm(r["away_team"]))
   g=exact.get(key)
   if g is None:
    candidates=[x for t,x in by_teams.get(key[1:],[]) if abs((t-tip).total_seconds())<=86400 and int(x["home_score"])==int(r["home_score"]) and int(x["away_score"])==int(r["away_score"])]
    if len(candidates)!=1: continue
    g=candidates[0]
   if int(g["home_score"])!=int(r["home_score"]) or int(g["away_score"])!=int(r["away_score"]):
    raise RuntimeError(f"{season}: final score mismatch for {r['home_team']} vs {r['away_team']}")
   gid=int(g["game_id"])
   if gid in seen: raise RuntimeError(f"{season}: duplicate matched game id {gid}")
   seen.add(gid)
   values={k:float(r[k]) for k in ("open_home_win_prob","close_home_win_prob","close_fair_home_odds","close_fair_away_odds","open_spread_home","close_spread_home","close_home_cover_prob","open_total","close_total","close_over_prob")}
   if not (0<values["open_home_win_prob"]<1 and 0<values["close_home_win_prob"]<1 and values["close_fair_home_odds"]>1 and values["close_fair_away_odds"]>1 and abs(values["open_spread_home"])<=40 and abs(values["close_spread_home"])<=40 and 0<values["close_home_cover_prob"]<1 and 150<=values["open_total"]<=300 and 150<=values["close_total"]<=300 and 0<values["close_over_prob"]<1):
    raise RuntimeError(f"{season}: invalid market values for game {gid}")
   if int(r["bookmakers"])<1 or r["moneyline_winner"] not in ("home","away") or r["ats_result"] not in ("home","away","push") or r["total_result"] not in ("over","under","push"):
    raise RuntimeError(f"{season}: invalid bookmaker count or market outcome for game {gid}")
   output.append({
    "game_id":gid,"season":season,"home_team":g["home_team"],"away_team":g["away_team"],
    "commence_time_utc":tip,"source_dataset":source_name,"source_url":url,"license":"CC-BY-4.0",
    "bookmaker_count":int(r["bookmakers"]),**values,
    "moneyline_winner":r["moneyline_winner"],"ats_result":r["ats_result"],"total_result":r["total_result"],
    "home_score":int(g["home_score"]),"away_score":int(g["away_score"])
   })
   counts[season]+=1
 expected={"2024-25":1314,"2025-26":1131}
 if dict(counts)!=expected or len(output)!=2445: raise RuntimeError(f"Expected 2445 matched market rows ({expected}); got {dict(counts)}")
 if len({(x["game_id"],x["source_dataset"]) for x in output})!=len(output): raise RuntimeError("Duplicate source/game keys")
 return output,counts
def connect():
 raw=os.environ.get(SECRET_NAME,"").strip()
 if not raw: raise RuntimeError(f"Missing environment secret {SECRET_NAME}")
 cfg=conninfo_to_dict(raw)
 if cfg.get("dbname")!=DB_NAME or cfg.get("user")!=DB_ROLE or not cfg.get("host","").endswith("neon.tech"):
  raise RuntimeError("Connection must use isolated nba_v80 / v80_historical_import Neon role")
 conn=psycopg.connect(host=cfg["host"],port=int(cfg.get("port","5432")),dbname=DB_NAME,user=DB_ROLE,password=cfg.get("password"),sslmode="verify-full",sslrootcert=certifi.where(),channel_binding="require",connect_timeout=15,application_name="NBA_AI_V80_MARKET_IMPORT")
 if not conn.pgconn.ssl_in_use: conn.close(); raise RuntimeError("TLS verification failed")
 return conn
def main():
 if os.environ.get("CONFIRM_MARKET_IMPORT")!="YES": raise RuntimeError("Explicit workflow confirmation required")
 mode=os.environ.get("IMPORT_MODE","dry-run").strip().lower()
 if mode not in {"dry-run","commit"}: raise RuntimeError("IMPORT_MODE must be dry-run or commit")
 rows,counts=load_market_rows()
 print(f"PASS: validated {len(rows)} matched closing-line rows; seasons={dict(counts)}; cutoff exclusive={CUTOFF.isoformat()}",flush=True)
 conn=connect()
 try:
  with conn.cursor() as cur:
   cur.execute("SET TRANSACTION READ WRITE")
   cur.execute("SET LOCAL TIME ZONE 'UTC'")
   cur.execute("SET LOCAL row_security=on")
   cur.execute("SET LOCAL statement_timeout='180s'")
   cur.execute("SET LOCAL lock_timeout='10s'")
   cur.execute("""SELECT current_database(),current_user,session_user,current_setting('transaction_read_only'),
    (SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user),
    has_table_privilege(current_user,'public.nba_historical_market_closes','INSERT'),
    has_table_privilege(current_user,'public.nba_historical_market_closes','UPDATE'),
    has_table_privilege(current_user,'public.nba_historical_market_closes','DELETE'),
    has_table_privilege(current_user,'public.nba_historical_market_closes','TRUNCATE'),
    (SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid='public.nba_historical_market_closes'::regclass),
    (SELECT relowner::regrole::text FROM pg_class WHERE oid='public.nba_historical_market_closes'::regclass)""")
   state=cur.fetchone()
   expected=(DB_NAME,DB_ROLE,DB_ROLE,"off",False,True,False,False,False,True,"neondb_owner")
   if tuple(state)!=expected: raise RuntimeError(f"Role/RLS/least-privilege check failed: {tuple(state)}")
   cur.execute("SELECT count(*) FROM pg_policies WHERE schemaname='public' AND tablename='nba_historical_market_closes' AND cmd='INSERT' AND policyname='v80_historical_market_closes_import_insert' AND 'v80_historical_import'=ANY(roles) AND with_check LIKE '%2026-04-02%'")
   if cur.fetchone()[0]!=1: raise RuntimeError("Import cutoff RLS policy missing")
   print("PASS: dedicated role, TLS, forced RLS, cutoff policy, insert-only table rights",flush=True)
   cur.executemany(INSERT,rows)
   cur.execute("""SELECT count(*),count(DISTINCT game_id),
    count(*) FILTER (WHERE commence_time_utc >= %s::timestamptz),
    count(*) FILTER (WHERE season='2024-25'),count(*) FILTER (WHERE season='2025-26')
    FROM public.nba_historical_market_closes""",(CUTOFF,))
   totals=cur.fetchone()
   if tuple(totals)!=(2445,2445,0,1314,1131): raise RuntimeError(f"Post-insert verification failed: {tuple(totals)}")
  if mode=="dry-run":
   conn.rollback()
   print("RESULT: DRY RUN PASSED; 2445 rows validated and rolled back; database unchanged",flush=True)
  else:
   conn.commit()
   print("RESULT: 2445/2445 verified market-close rows committed",flush=True)
 except Exception:
  conn.rollback(); raise
 finally: conn.close()
if __name__=="__main__":
 try: main()
 except Exception as e:
  print(f"MARKET IMPORT FAILED: {type(e).__name__}: {e}",file=sys.stderr); sys.exit(1)
