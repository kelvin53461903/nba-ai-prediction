"""Import expanded 2020-21..2023-24 NBA results into isolated V8.0 Neon only."""
import csv, os, sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import certifi, psycopg
from psycopg.conninfo import conninfo_to_dict

CSV_PATH=Path("data/nba_v80_historical_games_2020_2023.csv")
DB_NAME="nba_v80"; DB_ROLE="v80_historical_import"
SECRET="V80_HISTORICAL_IMPORT_DATABASE_URL"
CUTOFF=datetime(2026,4,2,tzinfo=timezone.utc)
EXPECTED={"2020-21","2021-22","2022-23","2023-24"}
INSERT_SQL="""INSERT INTO public.nba_game_results
(game_id,season,season_type,home_team_id,away_team_id,home_team,away_team,
 commence_time_utc,home_score,away_score,overtime_periods,game_status,source,verified_at_utc)
VALUES (%(game_id)s,%(season)s,%(season_type)s,%(home_team_id)s,%(away_team_id)s,
 %(home_team)s,%(away_team)s,%(commence_time_utc)s,%(home_score)s,%(away_score)s,
 %(overtime_periods)s,%(game_status)s,%(source)s,%(verified_at_utc)s)
ON CONFLICT (game_id) DO NOTHING"""

def dt(s):
 x=datetime.fromisoformat(s.replace("Z","+00:00"))
 if x.tzinfo is None: raise ValueError("timezone missing")
 return x.astimezone(timezone.utc)

def load():
 if not CSV_PATH.is_file(): raise RuntimeError("Expanded historical CSV is missing")
 rows=[]
 with CSV_PATH.open(newline="",encoding="utf-8-sig") as f:
  reader=csv.DictReader(f)
  required={"game_id","season","season_type","home_team_id","away_team_id","home_team","away_team",
   "commence_time_utc","home_score","away_score","overtime_periods","game_status","source","verified_at_utc"}
  if not required.issubset(set(reader.fieldnames or [])): raise RuntimeError("CSV schema mismatch")
  for line,r in enumerate(reader,2):
   row={"game_id":int(r["game_id"]),"season":r["season"].strip(),"season_type":r["season_type"].strip(),
    "home_team_id":int(r["home_team_id"]),"away_team_id":int(r["away_team_id"]),
    "home_team":r["home_team"].strip(),"away_team":r["away_team"].strip(),
    "commence_time_utc":dt(r["commence_time_utc"]),"home_score":int(r["home_score"]),
    "away_score":int(r["away_score"]),"overtime_periods":int(r["overtime_periods"]) if r.get("overtime_periods","").strip() else None,
    "game_status":r["game_status"].strip(),"source":r["source"].strip(),"verified_at_utc":dt(r["verified_at_utc"])}
   if row["season"] not in EXPECTED or row["season_type"] not in {"Regular Season","Playoffs","In-Season Tournament Final"}: raise RuntimeError(f"Unexpected season/type at line {line}")
   if row["commence_time_utc"]>=CUTOFF or row["verified_at_utc"]<=row["commence_time_utc"]: raise RuntimeError(f"Invalid cutoff/verification at line {line}")
   if row["game_status"]!="Final" or row["home_score"]<0 or row["away_score"]<0 or row["home_score"]==row["away_score"]: raise RuntimeError(f"Invalid final score at line {line}")
   if row["home_team_id"]==row["away_team_id"] or not row["source"]: raise RuntimeError(f"Invalid team/source at line {line}")
   rows.append(row)
 ids=[r["game_id"] for r in rows]
 counts=Counter(r["season"] for r in rows)
 if not rows or len(ids)!=len(set(ids)) or set(counts)!=EXPECTED or min(counts.values())<900:
  raise RuntimeError(f"Historical CSV count/uniqueness check failed: rows={len(rows)} seasons={dict(counts)}")
 return rows,counts

def main():
 mode=os.environ.get("IMPORT_MODE","dry-run").lower()
 if mode not in {"dry-run","commit"}: raise RuntimeError("Invalid IMPORT_MODE")
 if os.environ.get("CONFIRM_EARLY_SEASON_IMPORT")!="YES": raise RuntimeError("Explicit test-database import confirmation missing")
 rows,counts=load()
 raw=os.environ.get(SECRET,"").strip()
 if not raw: raise RuntimeError("Missing isolated Neon import secret")
 cfg=conninfo_to_dict(raw)
 if cfg.get("dbname")!=DB_NAME or cfg.get("user")!=DB_ROLE or not cfg.get("host","").endswith("neon.tech"):
  raise RuntimeError("Refusing non-isolated Neon endpoint or role")
 conn=psycopg.connect(host=cfg["host"],port=int(cfg.get("port","5432")),dbname=DB_NAME,user=DB_ROLE,
  password=cfg.get("password"),sslmode="verify-full",sslrootcert=certifi.where(),channel_binding="require",
  connect_timeout=15,application_name="NBA_AI_V80_EARLY_SEASON_IMPORT")
 try:
  if not conn.pgconn.ssl_in_use: raise RuntimeError("TLS not active")
  with conn.cursor() as cur:
   cur.execute("SET TRANSACTION READ WRITE"); cur.execute("SET LOCAL TIME ZONE 'UTC'")
   cur.execute("SET LOCAL row_security=on"); cur.execute("SET LOCAL statement_timeout='180s'")
   cur.execute("""SELECT current_database(),current_user,session_user,current_setting('transaction_read_only'),
    (SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user),
    has_table_privilege(current_user,'public.nba_game_results','INSERT'),
    has_table_privilege(current_user,'public.nba_game_results','UPDATE'),
    has_table_privilege(current_user,'public.nba_game_results','DELETE'),
    has_table_privilege(current_user,'public.nba_game_results','TRUNCATE'),
    (SELECT relrowsecurity FROM pg_class WHERE oid='public.nba_game_results'::regclass),
    (SELECT relowner::regrole::text FROM pg_class WHERE oid='public.nba_game_results'::regclass)""")
   state=tuple(cur.fetchone())
   expected=(DB_NAME,DB_ROLE,DB_ROLE,"off",False,True,False,False,False,True,"neondb_owner")
   if state!=expected: raise RuntimeError(f"Least-privilege/RLS check failed: {state}")
   cur.execute("""SELECT count(*) FROM pg_policies WHERE schemaname='public' AND tablename='nba_game_results'
    AND cmd='INSERT' AND policyname='historical_import_cutoff' AND 'v80_historical_import'=ANY(roles)
    AND with_check LIKE '%2026-04-02%'""")
   if cur.fetchone()[0]!=1: raise RuntimeError("Cutoff RLS policy missing")
   cur.execute("SELECT count(*) FROM public.nba_game_results WHERE season = ANY(%s)",(list(EXPECTED),))
   preexisting=cur.fetchone()[0]
   if preexisting==0:
    cur.executemany(INSERT_SQL,rows)
    print(f"PASS: inserted {len(rows)} new early-season rows",flush=True)
   elif preexisting==len(rows):
    ids=[r["game_id"] for r in rows]
    cur.execute("""SELECT game_id,season,home_team_id,away_team_id,commence_time_utc,home_score,away_score
     FROM public.nba_game_results WHERE game_id = ANY(%s)""",(ids,))
    existing={r[0]:(r[1],r[2],r[3],r[4],r[5],r[6]) for r in cur.fetchall()}
    for r in rows:
     expected=(r["season"],r["home_team_id"],r["away_team_id"],r["commence_time_utc"],r["home_score"],r["away_score"])
     if existing.get(r["game_id"])!=expected: raise RuntimeError(f"Existing game row differs from validated source: {r['game_id']}")
    print(f"PASS: {len(rows)} matching early-season rows already present; verified and skipped duplicate insert",flush=True)
   else:
    raise RuntimeError(f"Partial early-season batch already exists ({preexisting}/{len(rows)}); refusing mixed import")
   cur.execute("SELECT season,count(*),count(DISTINCT game_id) FROM public.nba_game_results WHERE season = ANY(%s) GROUP BY season ORDER BY season",(list(EXPECTED),))
   after={r[0]:(r[1],r[2]) for r in cur.fetchall()}
   for s,n in counts.items():
    if after.get(s)!=(n,n): raise RuntimeError(f"Post-import count mismatch for {s}: expected {n}, got {after.get(s)}")
  if mode=="dry-run":
   conn.rollback()
   print(f"PASS: dry-run validated {len(rows)} rows, seasons={dict(counts)}; transaction rolled back")
  else:
   conn.commit()
   print(f"PASS: committed {len(rows)} early-season games to isolated nba_v80 test DB; seasons={dict(counts)}")
 finally: conn.close()
if __name__=="__main__":
 try: main()
 except Exception as e:
  print(f"EARLY-SEASON IMPORT FAILED: {type(e).__name__}: {e}",file=sys.stderr); sys.exit(1)
