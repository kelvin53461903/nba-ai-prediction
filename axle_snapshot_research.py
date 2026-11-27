from collections import defaultdict, Counter
from datetime import datetime, timedelta
from pathlib import Path
import math
import pyarrow.parquet as pq

def timestamp(x):
    d=datetime.fromisoformat(x.replace("Z","+00:00"))
    if d.utcoffset() is None: raise ValueError("naive timestamp")
    return d

def eligible(row,g,line):
    try:
        snap=timestamp(row["snapshot"])
        start=timestamp(row["commence_time"])
        tip=timestamp(g["tip"])
        return (snap<min(start,tip) and abs((start-tip).total_seconds())<=300
            and row["spread_source"]=="odds_api_consensus_close"
            and int(row["n_books"])>=1
            and str(row["game_id"])==str(line["espn_event_id"])
            and line["game_id"]==g["nba_id"]
            and line["home_team_id"]==g["home"] and line["away_team_id"]==g["away"]
            and all(math.isfinite(float(v)) for v in (row["home_point"],row["over_under"],line["close_spread"],line["close_total"]))
            and abs(row["home_point"])<=40 and 150<=row["over_under"]<=300
            and abs(row["home_point"]-line["close_spread"])<1e-8
            and abs(row["over_under"]-line["close_total"])<1e-8)
    except (TypeError,ValueError,KeyError,AttributeError): return False

def grade(pred,actual):
    if pred==0: return "no_prediction"
    if actual==0: return "push"
    return "win" if pred*actual>0 else "loss"

def evaluate(games):
    originals=defaultdict(list)
    for r in pq.read_table("original_consensus.parquet").to_pylist():
        originals[str(r["game_id"])].append(r)
    lines=defaultdict(list)
    for y in (2025,2026):
        for r in pq.read_table(f"lines_{y}.parquet").to_pylist():
            if r["provider_id"]=="odds_api_consensus": lines[r["game_id"]].append(r)
    hist=defaultdict(list); counts=defaultdict(Counter); rejected=Counter(); verified=0
    for g in sorted(games,key=lambda g:g["tip"]):
        tip=timestamp(g["tip"]); day=tip.date()
        ls=lines[g["nba_id"]]
        rs=originals[str(ls[0]["espn_event_id"])] if len(ls)==1 else []
        ok=len(rs)==1 and eligible(rs[0],g,ls[0])
        if ok: verified+=1
        else: rejected["missing_ambiguous_or_invalid_snapshot"]+=1
        if ok and day.isoformat()>="2026-01-01":
            h,a=[[v for d,v in hist[g["season"],team] if d<=day-timedelta(days=2)] for team in (g["home"],g["away"])]
            if min(len(h),len(a))>=20:
                for n in (10,20):
                    x,z=[[sum(v[k] for v in s[-n:])/n for k in range(3)] for s in (h,a)]
                    pace=(x[2]+z[2])/2
                    adv=0 if g["neutral"] else 1.5
                    hp=pace*(x[0]+z[1])/200+adv
                    ap=pace*(z[0]+x[1])/200-adv
                    spread=rs[0]["home_point"]; total=rs[0]["over_under"]
                    if n==10: counts["spread"].update([grade(hp-ap+spread,g["hp"]-g["ap"]+spread)])
                    if n==20: counts["total"].update([grade(hp+ap-total,g["hp"]+g["ap"]-total)])
        for team,v in ((g["home"],g["archive_values"][:3]),(g["away"],g["archive_values"][3:])):
            hist[g["season"],team].append((day,v))
    return {"snapshot_checks_passed":verified,"rejected":dict(rejected),"research_metrics":{k:dict(v) for k,v in counts.items()},"research_only":True,"independent_holdout":False,"formal_market":{"n":0,"status":"blocked_feature_vintage_and_license"},"roi":None}

if __name__=="__main__":
    assert grade(1,0)=="push" and grade(-1,-2)=="win" and grade(0,2)=="no_prediction"
    g=dict(tip="2026-01-01T00:00:00Z",nba_id="x",home="h",away="a")
    l=dict(espn_event_id="1",game_id="x",home_team_id="h",away_team_id="a",close_spread=-3,close_total=220)
    r=dict(game_id=1,snapshot="2025-12-31T23:59:00Z",commence_time=g["tip"],spread_source="odds_api_consensus_close",n_books=9,home_point=-3,over_under=220)
    assert eligible(r,g,l)
    for bad in (g["tip"],"2026-01-01T00:01:00Z","2025-12-31T23:59:00",None):
        assert not eligible(dict(r,snapshot=bad),g,l)
    assert not eligible(dict(r,home_point=3),g,l)
    print("Synthetic snapshot and settlement tests PASS")
