import csv, json, re, math, hashlib, argparse
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen, Request

BASE="https://cdn.nba.com/static/json/"
def utc(s):
    d=datetime.fromisoformat(s.replace("Z","+00:00"))
    if d.tzinfo is None: raise ValueError("Missing timezone")
    return d.astimezone(timezone.utc)

def fetch(path):
    with urlopen(Request(BASE+path, headers={"User-Agent":"NBA research pilot","Accept":"application/json"}),timeout=25) as response:
        raw=response.read()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()

def key(t,h,a,hp,ap):
    return (utc(t).date(),h,a,int(hp),int(ap))

def historical_key(r):
    return key(r["commence_time_utc"],r["home_team"],r["away_team"],r["home_score"],r["away_score"])

def team_name(t):
    return t["teamCity"]+" "+t["teamName"]

def box_key(g):
    h,a=g["homeTeam"],g["awayTeam"]
    return key(g["gameTimeUTC"],team_name(h),team_name(a),h["score"],a["score"])

def possessions(t):
    s=t["statistics"]
    vals=[float(s[k]) for k in ("fieldGoalsAttempted","freeThrowsAttempted","reboundsOffensive","turnoversTotal")]
    if any(not math.isfinite(v) or v<0 for v in vals): raise ValueError("Invalid counts")
    fga,fta,orb,tov=vals
    p=fga+.44*fta-orb+tov
    if not 40<=p<=180: raise ValueError("Invalid possessions")
    return p

def validate(g,r,game_id,captured):
    if not re.fullmatch(r"\d{10}",game_id) or g["gameId"]!=game_id or g["gameStatus"]!=3: raise ValueError("Invalid final game")
    if box_key(g)!=historical_key(r): raise ValueError("Historical mismatch")
    tip=utc(g["gameTimeUTC"])
    if tip>=captured or tip>=utc("2026-04-02T00:00:00Z"): raise ValueError("Cutoff violation")
    h,a=g["homeTeam"],g["awayTeam"]
    if h["teamId"]==a["teamId"] or any(not 1610612737<=int(t["teamId"])<=1610612766 for t in (h,a)): raise ValueError("Invalid teams")
    period=int(g["period"])
    if not 4<=period<=10: raise ValueError("Invalid period")
    ph,pa=possessions(h),possessions(a)
    pace=48*(ph+pa)/(2*(48+5*(period-4)))
    return dict(nba_game_id=game_id, historical_id=r["game_id"],home_team_id=h["teamId"],away_team_id=a["teamId"],home_possessions=ph,away_possessions=pa,home_ortg=100*h["score"]/ph,away_ortg=100*a["score"]/pa,home_drtg=100*a["score"]/pa,away_drtg=100*h["score"]/ph,pace=pace,source="cdn.nba.com",is_reconstructed=True,captured_at_utc=captured.isoformat(),available_at_utc=captured.isoformat(),tip_utc=tip.isoformat())

def main():
    p=argparse.ArgumentParser()
    p.add_argument("csv"); p.add_argument("--output",default="cdn_pilot.json")
    args=p.parse_args()
    with open(args.csv,newline="") as f: rows=list(csv.DictReader(f))
    if len(rows)!=2459 or len({r["game_id"] for r in rows})!=2459: raise ValueError("Unexpected history")
    index={}
    for r in rows:
        k=historical_key(r)
        if k in index: raise ValueError("Ambiguous historical match")
        index[k]=r
    schedule,sha=fetch("staticData/scheduleLeagueV2.json")
    candidates=[]
    for day in schedule["leagueSchedule"]["gameDates"]:
        for g in day["games"]:
            if g.get("gameStatus")!=3: continue
            try: k=box_key(g)
            except (ValueError,KeyError,TypeError): continue
            if k in index: candidates.append((g["gameId"],index[k]))
    if not candidates: raise ValueError("No historical matches in current CDN schedule; archived schedule required")
    out=[]; seen=set()
    for gid,r in candidates[:3]:
        if gid in seen or not re.fullmatch(r"\d{10}",gid): raise ValueError("Invalid candidate ID")
        seen.add(gid)
        raw,digest=fetch("liveData/boxscore/boxscore_"+gid+".json")
        result=validate(raw["game"],r,gid,datetime.now(timezone.utc))
        out.append(dict(result=result,sha256=digest,raw=raw))
    Path(args.output).write_text(json.dumps(dict(schedule_sha256=sha,matched_candidates=len(candidates),rows=out),indent=2))
    print("Validated historical CDN games:",len(out),"of",len(rows),"; reconstruction only")
if __name__=="__main__": main()
