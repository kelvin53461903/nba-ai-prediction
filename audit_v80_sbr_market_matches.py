"""Match MIT SBR NBA closing lines to verified V8.0 game results; read-only audit."""
import json,sys,urllib.request,datetime as dt,re,collections,os,certifi,psycopg
from urllib.parse import urlsplit,unquote
from psycopg.rows import dict_row
URL="https://raw.githubusercontent.com/flancast90/sportsbookreview-scraper/main/data/nba_archive_10Y.json"
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
def norm_team(s):
 x=re.sub(r"[^a-z0-9]","",str(s).lower())
 if x in ALIASES:return ALIASES[x]
 # full-name variants are compared against DB names after normalizing.
 return str(s).strip()
def game_date(v):
 n=int(float(v)); return dt.datetime.strptime(str(n),"%Y%m%d").date()
def connect():
 raw=os.environ.get("V80_HISTORICAL_IMPORT_DATABASE_URL","").strip()
 if not raw: raise RuntimeError("Missing isolated Neon secret")
 u=urlsplit(raw); db=u.path.lstrip("/"); user=unquote(u.username or "")
 if db!="nba_v80" or user!="v80_historical_import" or not (u.hostname or "").endswith("neon.tech"): raise RuntimeError("Wrong database role")
 c=psycopg.connect(host=u.hostname,port=u.port or 5432,dbname=db,user=user,password=unquote(u.password or ""),
  sslmode="verify-full",sslrootcert=certifi.where(),channel_binding="require",connect_timeout=15,row_factory=dict_row)
 if not c.pgconn.ssl_in_use:c.close();raise RuntimeError("TLS not active")
 return c
def main():
 req=urllib.request.Request(URL,headers={"User-Agent":"NBA-AI-V8.0-SBR-Match-Audit/1.0"})
 with urllib.request.urlopen(req,timeout=90) as r: archive=json.loads(r.read())
 source=[x for x in archive if isinstance(x,dict) and int(x.get("season",0)) in (2020,2021)]
 counts=collections.Counter(int(x["season"]) for x in source)
 c=connect()
 try:
  with c.cursor() as cur:
   cur.execute("SET TRANSACTION READ ONLY");cur.execute("SET LOCAL TIME ZONE 'UTC'")
   cur.execute("""SELECT game_id,season,home_team,away_team,commence_time_utc,home_score,away_score
    FROM public.nba_game_results WHERE season IN ('2020-21','2021-22') AND game_status='Final'
    ORDER BY commence_time_utc""")
   games=cur.fetchall()
 finally:c.rollback();c.close()
 index=collections.defaultdict(list)
 for g in games:
  key=(norm_team(g["home_team"]),norm_team(g["away_team"]))
  index[key].append(g)
 matched={}; unmatched=collections.Counter(); invalid=collections.Counter(); examples=[]
 for r in source:
  try:
   home,away=norm_team(r["home_team"]),norm_team(r["away_team"])
   date=game_date(r["date"])
   hs,ascore=int(float(r["home_final"])),int(float(r["away_final"]))
   candidates=[]
   for g in index.get((home,away),[]):
    gd=g["commence_time_utc"].date()
    if abs((gd-date).days)<=1 and int(g["home_score"])==hs and int(g["away_score"])==ascore:
     candidates.append(g)
   if len(candidates)!=1:
    unmatched[int(r["season"])]+=1
    if len(examples)<15:examples.append({"season":r["season"],"date":date.isoformat(),"home":r["home_team"],"away":r["away_team"],"score":[hs,ascore],"candidate_count":len(candidates)})
    continue
   g=candidates[0]
   if g["game_id"] in matched: raise RuntimeError(f"duplicate matched game {g['game_id']}")
   spread=float(r["home_close_spread"]);total=float(r["close_over_under"])
   # Source repository documents that ~7% of SBR rows have close spread and total swapped.
   if 150<=spread<=300 and abs(total)<=40:
    spread,total=total,spread
   hm=int(float(r["home_close_ml"]));am=int(float(r["away_close_ml"]))
   if abs(spread)>40 or not 150<=total<=300 or hm==0 or am==0:
    invalid[int(r["season"])]+=1;continue
   matched[g["game_id"]]={"season":g["season"],"home":g["home_team"],"away":g["away_team"],"date":g["commence_time_utc"].isoformat(),"spread":spread,"total":total,"home_ml":hm,"away_ml":am}
  except Exception as e:
   invalid[int(r.get("season",0))]+=1
 report={"status":"READ_ONLY_MATCH_AUDIT","source":"flancast90/sportsbookreview-scraper","license":"MIT (LICENSE.md in source repository)","source_rows_by_archive_season":dict(counts),
  "matched_unique_games":len(matched),"matched_by_season":dict(collections.Counter(x["season"] for x in matched.values())),
  "unmatched_by_archive_season":dict(unmatched),"invalid_by_archive_season":dict(invalid),
  "sample_matches":list(matched.items())[:5],"sample_unmatched":examples,
  "note":"SBR archive provider is an archived market source, not a named single sportsbook. Lines/prices are kept under provider_id=sbr; never relabel as Pinnacle or DraftKings. No database writes performed."}
 print(json.dumps(report,indent=2,default=str))
 print("PASS: SBR archive matching audit complete; no writes")
if __name__=="__main__":
 try:main()
 except Exception as e:
  print(f"SBR MATCH AUDIT FAILED: {type(e).__name__}: {e}",file=sys.stderr);sys.exit(1)
