import csv, json, math, re, hashlib
from collections import defaultdict, Counter
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
import pyarrow.parquet as pq

# NBA franchise IDs in NBA's canonical franchise ordering, mapped by name.
names="Atlanta Hawks|Boston Celtics|Brooklyn Nets|Charlotte Hornets|Chicago Bulls|Cleveland Cavaliers|Dallas Mavericks|Denver Nuggets|Detroit Pistons|Golden State Warriors|Houston Rockets|Indiana Pacers|LA Clippers|Los Angeles Lakers|Memphis Grizzlies|Miami Heat|Milwaukee Bucks|Minnesota Timberwolves|New Orleans Pelicans|New York Knicks|Oklahoma City Thunder|Orlando Magic|Philadelphia 76ers|Phoenix Suns|Portland Trail Blazers|Sacramento Kings|San Antonio Spurs|Toronto Raptors|Utah Jazz|Washington Wizards".split("|")
ids=[2737,2738,2751,2766,2741,2739,2742,2743,2765,2744,2745,2754,2746,2747,2763,2748,2749,2750,2740,2752,2760,2753,2755,2756,2757,2758,2759,2761,2762,2764]
def norm(s): return re.sub(r"[^a-z0-9]","",s.lower()).replace("losangelesclippers","laclippers")
mapping={norm(n):str(1610610000+i) for n,i in zip(names,ids)}
cutoff=datetime(2026,4,2,tzinfo=timezone.utc)
def read(p): return pq.ParquetFile(p).read().to_pylist()
def key(y,d,a,b): return (y,d,tuple(sorted((a,b))))
def main():
    hist=Path("historical-source/data/nba_v80_historical_games_cutoff_2026-04-01.csv")
    rows=list(csv.DictReader(hist.open()))
    assert len(rows)==2459 and len({r["game_id"] for r in rows})==2459
    idx=defaultdict(list)
    for y in (2025,2026):
        games=read(f"games_{y}.parquet")
        logs=read(f"team_game_logs_{y}.parquet")
        t={(x["game_id"],x["team_id"]):x for x in logs}
        assert len(t)==len(logs)
        for g in games:
            if g["game_type"] not in ("regular_season","playoffs","play_in","cup_final"): continue
            gid=g["game_id"]
            assert re.fullmatch(r"\d{10}",gid)
            h,a=g["home_team_id"],g["away_team_id"]
            x,z=t.get((gid,h)),t.get((gid,a))
            if x is None or z is None: continue
            if x["opp_team_id"]!=a or z["opp_team_id"]!=h: continue
            if x["game_date"]!=g["game_date"] or z["game_date"]!=g["game_date"]: continue
            idx[key(y,g["game_date"],(h,x["pts"]),(a,z["pts"]))].append((g,x,z))
    matched=[]; issues=[]; used=set()
    for r in rows:
        tip=datetime.fromisoformat(r["commence_time_utc"])
        assert tip.tzinfo and tip<cutoff and r["game_status"]=="Final"
        h,a=(mapping[norm(r[k])] for k in ("home_team","away_team"))
        hp,ap=int(r["home_score"]),int(r["away_score"])
        y=int(r["season"][:4])+1
        candidates=idx[key(y,tip.astimezone(ZoneInfo("America/New_York")).date(),(h,hp),(a,ap))]
        if len(candidates)!=1:
            nearby=[(str(d),g["game_id"],g["game_type"],g["neutral_site"]) for offset in (-1,1) for d in [tip.astimezone(ZoneInfo("America/New_York")).date()+timedelta(days=offset)] for g,x,z in idx[key(y,d,(h,hp),(a,ap))]]
            issues.append((r["game_id"],"candidate_count",len(candidates),nearby)); continue
        g,x,z=candidates[0]; gid=g["game_id"]
        if gid in used or (g["home_team_id"]!=h and g["neutral_site"] is not True):
            issues.append((r["game_id"],"orientation_or_duplicate")); continue
        if x["team_id"]!=h: x,z=z,x
        try:
            def poss(v):
                vals=[float(v[k]) for k in ("fga","fta","oreb","tov")]
                assert all(math.isfinite(n) and 0<=n<300 for n in vals)
                p=vals[0]+.44*vals[1]-vals[2]+vals[3]
                assert 40<=p<=180
                return p
            ph,pa=poss(x),poss(z)
            minutes=float(x["min"])
            if minutes>100: minutes/=5
            other=float(z["min"])
            if other>100: other/=5
            duration=48+5*round((minutes-48)/5)
            assert 48<=duration<=78 and abs(minutes-duration)<=0.5 and abs(other-duration)<=0.5 and abs(minutes-other)<=0.1, "duration"
            minutes=duration
            raw=[float(v[k]) for v in (x,z) for k in ("off_rating","def_rating","pace")]
            assert all(math.isfinite(n) and n>0 for n in raw)
            est=[100*hp/ph,100*ap/pa,48*(ph+pa)/(2*minutes),100*ap/pa,100*hp/ph,48*(ph+pa)/(2*minutes)]
        except (ValueError,TypeError,AssertionError,KeyError) as exc:
            issues.append((r["game_id"],"invalid_stats",str(exc),{k:x.get(k) for k in ("min","off_rating","def_rating","pace","fga","fta","oreb","tov")},{k:z.get(k) for k in ("min","off_rating","def_rating","pace","fga","fta","oreb","tov")})); continue
        used.add(gid)
        matched.append(dict(historical_id=r["game_id"],nba_id=gid,home=h,away=a,tip=tip.isoformat(),season=y,hp=hp,ap=ap,neutral=g["neutral_site"],game_type=g["game_type"],archive_values=raw,estimated_values=est,is_reconstructed=True))
    report=dict(matched=len(matched),unmatched=len(issues),issues=issues[:50],teams=len({v[k] for v in matched for k in ("home","away")}),types=Counter(v["game_type"] for v in matched),neutral=sum(v["neutral"] is True for v in matched),research_only=True,point_in_time_verified=False,cutoff=cutoff.isoformat(),sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [hist,*Path(".").glob("*.parquet")]})
    # No raw archive rows uploaded; only aggregate audit.
    Path("nbadata_match_audit.json").write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
    from axle_rolling import evaluate
    report["rolling_research"]=evaluate(matched)
    Path("nbadata_match_audit.json").write_text(json.dumps(report,indent=2))
    print(json.dumps(report["rolling_research"]))
    if len(matched)!=2459 or report["teams"]!=30: raise ValueError("Incomplete reconciliation")
if __name__=="__main__": main()
