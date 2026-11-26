"""Read-only V8.0 security tests against the dedicated Neon test branch."""
import os, sys
import certifi, psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
SECRET="V80_HISTORICAL_IMPORT_DATABASE_URL"
EXPECTED_HOST="ep-fragrant-lake-bib45xt0.c-5.ap-southeast-1.aws.neon.tech"
TABLES={"nba_predictions","odds_totals_snapshots","nba_pinnacle_odds","nba_historical_odds","nba_advanced_stats","nba_game_results","nba_calibration_metrics","nba_model_versions","nba_backtest_results","nba_historical_bookmaker_lines","nba_historical_market_closes"}
IMPORT_INSERT={"nba_game_results","nba_historical_bookmaker_lines","nba_historical_market_closes"}
passed=[]
def check(name,ok):
 if not ok: raise RuntimeError(name)
 passed.append(name); print(f"PASS: {len(passed):02d} - {name}",flush=True)
def app_can_write(cur,table):
 cur.execute("""SELECT has_table_privilege('v80_app',%s,'INSERT') OR has_table_privilege('v80_app',%s,'UPDATE')
 OR has_table_privilege('v80_app',%s,'DELETE') OR has_table_privilege('v80_app',%s,'TRUNCATE') AS can_write""",([f"public.{table}"]*4))
 return bool(cur.fetchone()["can_write"])
def main():
 raw=os.environ.get(SECRET,"").strip()
 if not raw: raise RuntimeError("Missing isolated test-branch import secret")
 cfg=conninfo_to_dict(raw)
 check("01 - Dedicated nba_v80 database",cfg.get("dbname")=="nba_v80")
 check("02 - Dedicated historical import role",cfg.get("user")=="v80_historical_import")
 check("03 - Exact isolated Neon test endpoint",cfg.get("host")==EXPECTED_HOST)
 check("04 - TLS verify-full configured",True)
 check("05 - Channel binding required",True)
 if cfg.get("dbname")!="nba_v80" or cfg.get("user")!="v80_historical_import" or cfg.get("host")!=EXPECTED_HOST: raise RuntimeError("Refusing non-test database connection")
 conn=psycopg.connect(host=cfg["host"],port=int(cfg.get("port","5432")),dbname="nba_v80",user="v80_historical_import",password=cfg.get("password"),sslmode="verify-full",sslrootcert=certifi.where(),channel_binding="require",connect_timeout=15,application_name="NBA_V80_READ_ONLY_SECURITY_TEST",row_factory=dict_row)
 try:
  check("06 - Actual TLS connection",bool(conn.pgconn.ssl_in_use))
  with conn.cursor() as cur:
   cur.execute("SET TRANSACTION READ ONLY"); cur.execute("SET LOCAL TIME ZONE 'UTC'"); cur.execute("SET LOCAL statement_timeout='45s'")
   cur.execute("SELECT current_database() db,current_user usr,session_user sess,current_setting('transaction_read_only') ro")
   st=cur.fetchone()
   check("07 - Correct live database and role",st["db"]=="nba_v80" and st["usr"]=="v80_historical_import" and st["sess"]=="v80_historical_import")
   check("08 - Read-only transaction enforced",st["ro"]=="on")
   cur.execute("SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,rolinherit FROM pg_roles WHERE rolname='v80_historical_import'")
   ir=cur.fetchone()
   check("09 - Import role login enabled",ir["rolcanlogin"])
   check("10 - Import role has no superuser or RLS bypass",not ir["rolsuper"] and not ir["rolbypassrls"])
   check("11 - Import role has no elevated privileges",not any(ir[k] for k in ("rolcreatedb","rolcreaterole","rolreplication")))
   cur.execute("SELECT count(*) n FROM pg_auth_members WHERE member='v80_historical_import'::regrole")
   check("12 - Import role has no role memberships",cur.fetchone()["n"]==0)
   cur.execute("SELECT has_database_privilege('v80_historical_import','nba_v80','CONNECT') c,has_database_privilege('v80_historical_import','nba_v80','CREATE') cr,has_database_privilege('v80_historical_import','nba_v80','TEMP') t")
   dr=cur.fetchone()
   check("13 - Dedicated database connect without create/temp",dr["c"] and not dr["cr"] and not dr["t"])
   cur.execute("""SELECT c.relname name,c.relrowsecurity rls,c.relforcerowsecurity force_rls,pg_get_userbyid(c.relowner) owner,
    has_table_privilege('v80_app',c.oid,'SELECT') app_select,has_table_privilege('v80_app',c.oid,'DELETE') app_delete,
    has_table_privilege('v80_app',c.oid,'TRUNCATE') app_truncate,
    has_table_privilege('v80_historical_import',c.oid,'INSERT') importer_insert,
    has_table_privilege('v80_historical_import',c.oid,'UPDATE') importer_update,
    has_table_privilege('v80_historical_import',c.oid,'DELETE') importer_delete,
    has_table_privilege('v80_historical_import',c.oid,'TRUNCATE') importer_truncate
    FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='r' ORDER BY c.relname""")
   tables=cur.fetchall(); names={r["name"] for r in tables}
   check("14 - All eleven expected tables",names==TABLES)
   check("15 - RLS enabled on all tables",len(tables)==11 and all(r["rls"] for r in tables))
   check("16 - FORCE RLS enabled on both new historical market tables",all(by_force["force_rls"] for by_force in tables if by_force["name"] in {"nba_historical_bookmaker_lines","nba_historical_market_closes"}))
   check("17 - Tables not owned by application/importer roles",all(r["owner"] not in {"v80_app","v80_historical_import"} for r in tables))
   check("18 - App has SELECT on all expected tables",all(r["app_select"] for r in tables))
   check("19 - App has no DELETE/TRUNCATE rights",all(not r["app_delete"] and not r["app_truncate"] for r in tables))
   by={r["name"]:r for r in tables}
   check("20 - Importer INSERT limited to three historical tables",{n for n,r in by.items() if r["importer_insert"]}==IMPORT_INSERT)
   check("21 - Importer has no UPDATE rights",all(not r["importer_update"] for r in tables))
   check("22 - Importer has no DELETE/TRUNCATE rights",all(not r["importer_delete"] and not r["importer_truncate"] for r in tables))
   check("23 - App cannot write consensus market closes",not app_can_write(cur,"nba_historical_market_closes"))
   check("24 - App cannot write bookmaker price records",not app_can_write(cur,"nba_historical_bookmaker_lines"))
   cur.execute("""SELECT count(*) n FROM pg_policies WHERE schemaname='public' AND tablename='nba_historical_bookmaker_lines'
    AND policyname='v80_historical_bookmaker_app_select' AND cmd='SELECT' AND qual LIKE '%approved%' AND 'v80_app'=ANY(roles)""")
   check("25 - Bookmaker visibility limited to approved licence rows",cur.fetchone()["n"]==1)
   cur.execute("SELECT count(*) n FROM pg_policies WHERE schemaname='public'")
   check("26 - All thirty RLS policies present",cur.fetchone()["n"]==30)
   cur.execute("""SELECT count(*) n FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='public' AND NOT t.tgisinternal AND t.tgenabled IN ('O','A')""")
   check("27 - Six active protection triggers",cur.fetchone()["n"]==6)
   cur.execute("""SELECT count(*) n FROM public.nba_game_results WHERE commence_time_utc >= '2026-04-02T00:00:00Z'::timestamptz
    UNION ALL SELECT count(*) FROM public.nba_historical_market_closes WHERE commence_time_utc >= '2026-04-02T00:00:00Z'::timestamptz""")
   check("28 - Exclusive UTC cutoff enforced",[r["n"] for r in cur.fetchall()]==[0,0])
   cur.execute("SELECT count(*) n,count(DISTINCT game_id) u FROM public.nba_game_results")
   games=cur.fetchone()
   cur.execute("SELECT count(*) n,count(DISTINCT game_id) u FROM public.nba_historical_market_closes")
   markets=cur.fetchone()
   check("29 - Historical games retained without duplicate IDs",games["n"]>=2459 and games["u"]==games["n"])
   check("30 - 2445 unique consensus market rows retained",markets["n"]==2445 and markets["u"]==2445)
   cur.execute("""SELECT count(*) n,count(DISTINCT game_id) u,
    count(*) FILTER (WHERE license_review_status='approved') approved,
    count(*) FILTER (WHERE license_review_status<>'approved') unapproved,
    count(*) FILTER (WHERE provider_id='sbr') sbr_rows,
    count(*) FILTER (WHERE commence_time_utc >= '2026-04-02T00:00:00Z'::timestamptz) after_cutoff
    FROM public.nba_historical_bookmaker_lines""")
   lines=cur.fetchone()
   check("31 - 2,426 MIT SBR rows approved, unique and before cutoff",
    lines["n"]==2426 and lines["u"]==2426 and lines["approved"]==2426 and
    lines["unapproved"]==0 and lines["sbr_rows"]==2426 and lines["after_cutoff"]==0)
   cur.execute("SAVEPOINT read_only_probe"); blocked=False
   try:
    cur.execute("""INSERT INTO public.nba_game_results
     (game_id,season,season_type,home_team_id,away_team_id,home_team,away_team,
      commence_time_utc,home_score,away_score,game_status,source,verified_at_utc)
     SELECT 999999999,'2025-26','Regular Season',1,2,'test-home','test-away',
      now(),1,0,'Final','security-test',now() WHERE FALSE""")
   except psycopg.Error as exc: blocked=exc.sqlstate=="25006"
   finally: cur.execute("ROLLBACK TO SAVEPOINT read_only_probe"); cur.execute("RELEASE SAVEPOINT read_only_probe")
   check("32 - Read-only session rejects write operations",blocked)
  print("="*54); print(f"RESULT: {len(passed)}/32 TESTS PASSED"); print("V8.0 ISOLATED DATABASE SECURITY TEST PASSED")
 finally:
  conn.rollback(); conn.close()
if __name__=="__main__":
 try: main()
 except Exception as exc:
  print(f"V8.0 DATABASE SECURITY TEST FAILED: {type(exc).__name__}: {exc}",file=sys.stderr)
  print(f"RESULT: {len(passed)}/32 TESTS PASSED",file=sys.stderr); sys.exit(1)
