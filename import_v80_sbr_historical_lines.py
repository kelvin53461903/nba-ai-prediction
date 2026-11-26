"""Import verified MIT SBR closing lines into isolated V8.0 test DB only."""
import os,sys,json,urllib.request,datetime as dt,re,collections,hashlib
import certifi,psycopg
from urllib.parse import urlsplit,unquote
from psycopg.rows import dict_row

REV="1a820e50c6fbd0276cde073c22bfffae78930868"
URL=f"https://raw.githubusercontent.com/flancast90/sportsbookreview-scraper/{REV}/data/nba_archive_10Y.json"
LICENSE_URL=f"https://github.com/flancast90/sportsbookreview-scraper/blob/{REV}/LICENSE.md"
ALIASES={
"knicks":"New York Knicks","celtics":"Boston Celtics","nets":"Brooklyn Nets","warriors":"Golden State Warriors",
"76ers":"Philadelphia 76ers","sixers":"Philadelphia 76ers","seventysixers":"Philadelphia 76ers","lakers":"Los Angeles Lakers","clippers":"LA Clippers",
"trailblazers":"Portland Trail Blazers","blazers":"Portland Trail Blazers","pelicans":"New Orleans Pelicans",
"thunder":"Oklahoma City Thunder","jazz":"Utah Jazz","spurs":"San Antonio Spurs","rockets":"Houston Rockets",
"mavericks":"Dallas Mavericks","nuggets":"Denver Nuggets","grizzlies":"Memphis Grizzlies","timberwolves":"Minnesota Timberwolves","wolves":"Minnesota Timberwolves",
"hawks":"Atlanta Hawks","magic":"Orlando Magic","heat":"Miami Heat","bulls":"Chicago Bulls",
"cavaliers":"Cleveland Cavaliers","cavs":"Cleveland Cavaliers","pistons":"Detroit Pistons","pacers":"Indiana Pacers",
"bucks":"Milwaukee Bucks","raptors":"Toronto Raptors","suns":"Phoenix Suns","kings":"Sacramento Kings",
"hornets":"Charlotte Hornets","wizards":"Washington Wizards"}
CUTOFF=dt.datetime(2026,4,2,tzinfo=dt.timezone.utc)
EXPECTED={"2020-21":1146,"2021-22":1280}
def norm_team(s):
 x=re.sub(r"[^a-z0-9]","",str(s).lower())
 return ALIASES.get(x,str(s).strip())
def game_date(v):
 n=int(float(v));return dt.datetime.strptime(str(n),"%Y%m%d").date()
def connect():
 raw=os.environ.get("V80_HISTORICAL_IMPORT_DATABASE_URL","").strip()
 if not raw:raise RuntimeError("Missing isolated Neon secret")
 u=urlsplit(raw);db=u.path.lstrip("/");user=unquote(u.username or "")
 if db!="nba_v80" or user!="v80_historical_import" or not (u.hostname or "").endswith("neon.tech"):raise RuntimeError("Wrong database or role")
 c=psycopg.connect(host=u.hostname,port=u.port or 5432,dbname=db,user=user,password=unquote(u.password or ""),
  sslmode="verify-full",sslrootcert=certifi.where(),channel_binding="require",connect_timeout=15,row_factory=dict_row)
 if not c.pgconn.ssl_in_use:c.close();raise RuntimeError("TLS not active")
 return c
def build_rows(games):
 req=urllib.request.Request(URL,headers={"User-Agent":"NBA-AI-V8.0-SBR-Import/1.0"})
 with urllib.request.urlopen(req,timeout=90) as r: payload=r.read()
 archive=json.loads(payload)
 source=[x for x in archive if isinstance(x,dict) and int(x.get("season",0)) in (2020,2021)]
 index=collections.defaultdict(list)
 for g in games:index[(norm_team(g["home_team"]),norm_team(g["away_team"]))].append(g)
 output=[];unmatched=collections.Counter();invalid=collections.Counter();seen=set()
 for r in source:
  home,away=norm_team(r["home_team"]),norm_team(r["away_team"])
  date=game_date(r["date"]);hs,ascore=int(float(r["home_final"])),int(float(r["away_final"]))
  candidates=[g for g in index.get((home,away),[]) if abs((g["commence_time_utc"].date()-date).days)<=1 and int(g["home_score"])==hs and int(g["away_score"])==ascore]
  if len(candidates)!=1:unmatched[int(r["season"])]+=1;continue
  g=candidates[0]
  if g["game_id"] in seen:raise RuntimeError(f"Duplicate matched game {g['game_id']}")
  spread=float(r["home_close_spread"]);total=float(r["close_over_under"])
  # SBR source notes that roughly 7% of archive rows have closing spread/total swapped.
  if 150<=spread<=300 and abs(total)<=40:spread,total=total,spread
  open_spread=float(r["home_open_spread"]);open_total=float(r["open_over_under"])
  hm=int(float(r["home_close_ml"]));am=int(float(r["away_close_ml"]))
  if not (-40<=spread<=40 and 150<=total<=300 and -40<=open_spread<=40 and 150<=open_total<=300 and hm!=0 and am!=0 and abs(hm)<=10000 and abs(am)<=10000):
   invalid[int(r["season"])]+=1;continue
  season=g["season"]
  output.append({"game_id":g["game_id"],"season":season,"provider_id":"sbr",
   "provider":"SportsbookReview historical archive (bookmaker not individually identified)",
   "home_team_id":str(g["home_team_id"]),"away_team_id":str(g["away_team_id"]),
   "commence_time_utc":g["commence_time_utc"],"open_spread":open_spread,"close_spread":spread,
   "open_total":open_total,"close_total":total,"close_home_moneyline":hm,"close_away_moneyline":am,
   "source_project":"flancast90/sportsbookreview-scraper","source_url":URL,"source_revision":REV,
   "license_review_status":"approved"})
  seen.add(g["game_id"])
 counts=dict(collections.Counter(x["season"] for x in output))
 if len(output)!=2426 or counts!=EXPECTED:raise RuntimeError(f"Expected 2426 SBR rows {EXPECTED}; got {len(output)} {counts}; unmatched={dict(unmatched)} invalid={dict(invalid)}")
 return output,hashlib.sha256(payload).hexdigest(),dict(unmatched),dict(invalid)
def main():
 if os.environ.get("CONFIRM_SBR_IMPORT")!="YES":raise RuntimeError("Explicit isolated-import confirmation missing")
 mode=os.environ.get("IMPORT_MODE","dry-run").lower()
 if mode not in ("dry-run","commit"):raise RuntimeError("Invalid import mode")
 c=connect()
 try:
  with c.cursor() as cur:
   cur.execute("SET TRANSACTION READ WRITE");cur.execute("SET LOCAL TIME ZONE 'UTC'");cur.execute("SET LOCAL row_security=on")
   cur.execute("SET LOCAL statement_timeout='180s'");cur.execute("SET LOCAL lock_timeout='10s'")
   cur.execute("""SELECT current_database(),current_user,session_user,current_setting('transaction_read_only'),
    (SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user),
    has_table_privilege(current_user,'public.nba_historical_bookmaker_lines','INSERT'),
    has_table_privilege(current_user,'public.nba_historical_bookmaker_lines','UPDATE'),
    has_table_privilege(current_user,'public.nba_historical_bookmaker_lines','DELETE'),
    has_table_privilege(current_user,'public.nba_historical_bookmaker_lines','TRUNCATE'),
    (SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid='public.nba_historical_bookmaker_lines'::regclass)""")
   state=cur.fetchone()
   if tuple(state)!=("nba_v80","v80_historical_import","v80_historical_import","off",False,True,False,False,False,True):
    raise RuntimeError(f"Least-privilege/RLS checks failed: {tuple(state)}")
   cur.execute("""SELECT count(*) FROM pg_policies WHERE schemaname='public' AND tablename='nba_historical_bookmaker_lines'
    AND policyname='v80_historical_bookmaker_import_insert' AND cmd='INSERT'
    AND 'v80_historical_import'=ANY(roles) AND with_check LIKE '%2026-04-02%'""")
   if cur.fetchone()["count"]!=1:raise RuntimeError("Cutoff RLS insert policy missing")
   cur.execute("""SELECT game_id,season,home_team,away_team,commence_time_utc,home_score,away_score
    FROM public.nba_game_results WHERE season IN ('2020-21','2021-22') AND game_status='Final' AND commence_time_utc<%s
    ORDER BY commence_time_utc""",(CUTOFF,))
   games=cur.fetchall()
  rows,digest,unmatched,invalid=build_rows(games)
  print(f"PASS: {len(rows)} MIT-licensed SBR lines matched; seasons={EXPECTED}; archive_sha256={digest}; unmatched={unmatched}; invalid={invalid}",flush=True)
  with c.cursor() as cur:
   cur.executemany("""INSERT INTO public.nba_historical_bookmaker_lines
    (game_id,season,provider_id,provider,home_team_id,away_team_id,commence_time_utc,
     open_spread,close_spread,open_total,close_total,close_home_moneyline,close_away_moneyline,
     source_project,source_url,source_revision,license_review_status)
    VALUES (%(game_id)s,%(season)s,%(provider_id)s,%(provider)s,%(home_team_id)s,%(away_team_id)s,%(commence_time_utc)s,
     %(open_spread)s,%(close_spread)s,%(open_total)s,%(close_total)s,%(close_home_moneyline)s,%(close_away_moneyline)s,
     %(source_project)s,%(source_url)s,%(source_revision)s,%(license_review_status)s)
    ON CONFLICT (game_id,provider_id) DO NOTHING""",rows)
   cur.execute("""SELECT count(*) AS total,count(DISTINCT game_id) AS unique_games,
    count(*) FILTER (WHERE license_review_status='approved') AS approved,
    count(*) FILTER (WHERE commence_time_utc>=%s::timestamptz) AS after_cutoff,
    count(*) FILTER (WHERE close_spread IS NULL OR close_total IS NULL OR close_home_moneyline=0 OR close_away_moneyline=0) AS incomplete
    FROM public.nba_historical_bookmaker_lines WHERE provider_id='sbr'""",(CUTOFF,))
   result=cur.fetchone()
   if result["total"]!=2426 or result["unique_games"]!=2426 or result["approved"]!=2426 or result["after_cutoff"]!=0 or result["incomplete"]!=0:
    raise RuntimeError(f"Post-insert verification failed: {result}")
  if mode=="dry-run":
   c.rollback();print("RESULT: SBR DRY RUN PASSED; 2,426 rows rolled back; database unchanged",flush=True)
  else:
   c.commit();print("RESULT: 2,426 approved SBR historical market rows committed to isolated nba_v80 only",flush=True)
 finally:
  if not c.closed:c.rollback();c.close()
if __name__=="__main__":
 try:main()
 except Exception as e:print(f"SBR IMPORT FAILED: {type(e).__name__}: {e}",file=sys.stderr);sys.exit(1)
