import pandas as pd
import json, hashlib, re
from pathlib import Path
from datetime import datetime, timezone
import sys

def main():
    hist, schedule, *boxes = map(Path,sys.argv[1:])
    h=pd.read_csv(hist,dtype={"game_id":str})
    assert len(h)==2459 and h.game_id.is_unique
    s=pd.read_parquet(schedule)
    s=s[(s.season.isin([2025,2026])) & (s.game_status==3)].copy()
    s["day"]=pd.to_datetime(s.game_date_time_utc,utc=True,format="mixed").dt.date
    h["day"]=pd.to_datetime(h.commence_time_utc,utc=True).dt.date
    assert s.game_id.is_unique
    def norm(x): return re.sub(r"[^a-z0-9]","",str(x).lower()).replace("losangelesclippers","laclippers")
    for side in ("home","away"):
        h[side+"key"]=h[side+"_team"].map(norm)
        s[side+"key"]=(s[side+"_team_city"]+" "+s[side+"_team_name"]).map(norm)
        s[side+"_score"]=s[side+"_team_score"]
    keys=["day","homekey","awaykey","home_score","away_score"]
    m=h.merge(s[keys+["game_id","home_team_id","away_team_id"]],on=keys,suffixes=("_historical","_nba"),validate="one_to_one")
    t=pd.concat([pd.read_parquet(p) for p in boxes],ignore_index=True)
    assert not t.duplicated(["game_id","side"]).any()
    t=t.set_index(["game_id","side"])
    out=[]; missing=[]
    for _,r in m.iterrows():
        gid=r.game_id_nba
        assert re.fullmatch(r"\d{10}",gid)
        if any((gid,side) not in t.index for side in ("home","away")):
            missing.append(gid); continue
        a,b=[t.loc[(gid,side)] for side in ("home","away")]
        for side,x in zip(("home","away"),(a,b)):
            assert int(x.team_id)==int(r[side+"_team_id_nba"]) and int(x.points)==int(r[side+"_score"])
        def poss(x):
            v=[float(x[k]) for k in ("field_goals_attempted","free_throws_attempted","rebounds_offensive","turnovers")]
            assert all(0<=z<300 for z in v)
            p=v[0]+.44*v[1]-v[2]+v[3]
            assert 40<=p<=180
            return p
        ph,pa=poss(a),poss(b)
        ot=int(r.overtime_periods)
        assert 0<=ot<=6
        out.append(dict(game_id=gid,historical_id=r.game_id_historical,home_team=int(a.team_id),away_team=int(b.team_id),home_ortg=100*int(a.points)/ph,away_ortg=100*int(b.points)/pa,home_drtg=100*int(b.points)/pa,away_drtg=100*int(a.points)/ph,pace=48*(ph+pa)/(2*(48+5*ot)),is_reconstructed=True))
    report=dict(matched=len(m),validated=len(out),missing_boxes=len(missing),unmatched=2459-len(m),teams=len({x[k] for x in out for k in ("home_team","away_team")}),captured_at_utc=datetime.now(timezone.utc).isoformat(),source="sportsdataverse/hoopR-nba-stats-data",sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [hist,schedule,*boxes]},research_only=True)
    print(json.dumps(report))
    Path("archive_audit.json").write_text(json.dumps(report,indent=2))
    if len(out)!=2459 or report["teams"]!=30: raise ValueError("Incomplete archive coverage")
if __name__=="__main__": main()
