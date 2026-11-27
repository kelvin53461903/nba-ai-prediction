import json, math, hashlib
from collections import Counter, defaultdict
from pathlib import Path
from axle_holdout_capture import utc

def settle(record, result):
    if result["game_id"]!=record["game_id"] or result["status"]!="Final": return None
    if utc(result["observed_at"])<=utc(record["tip"]): return None
    if result["home"]!=record["home"] or result["away"]!=record["away"]: return None
    h,a=result["home_score"],result["away_score"]
    if type(h)!=int or type(a)!=int or min(h,a)<=0 or h==a: return None
    if not utc(record["prediction_at"])<=utc(record["captured_at"])<utc(record["tip"]): return None
    p=float(record["prediction"])
    if not math.isfinite(p): return None
    m=record["market"]
    if m=="moneyline":
        if not 0<=p<=1: return None
        predicted=p-.5; actual=h-a
    elif m=="spread":
        predicted=p+float(record["line"]); actual=h-a+float(record["line"])
    elif m=="total":
        predicted=p-float(record["line"]); actual=h+a-float(record["line"])
    else: return None
    outcome="no_prediction" if predicted==0 else "push" if actual==0 else "win" if predicted*actual>0 else "loss"
    return dict(game_id=record["game_id"],market=m,outcome=outcome,research_only=True)

def summarize(records, results):
    by_id={}
    for r in results:
        if r["game_id"] in by_id: raise ValueError("duplicate result")
        by_id[r["game_id"]]=r
    seen=set(); counts=defaultdict(Counter)
    for r in records:
        key=(r["game_id"],r["market"])
        if key in seen: raise ValueError("duplicate prediction")
        seen.add(key)
        s=settle(r,by_id[key[0]]) if key[0] in by_id else None
        counts[key[1]][s["outcome"] if s else "pending_or_invalid"]+=1
    return {m:dict(counts=dict(c),accuracy=c["win"]/(c["win"]+c["loss"]) if c["win"]+c["loss"] else None,roi=None,research_only=True) for m,c in counts.items()}

if __name__=="__main__":
    r=dict(game_id="synthetic",market="spread",home="H",away="A",prediction=5,line=-3,tip="2026-12-01T01:00:00Z",prediction_at="2026-12-01T00:00:00Z",captured_at="2026-12-01T00:01:00Z")
    g=dict(game_id="synthetic",status="Final",home="H",away="A",home_score=103,away_score=100,observed_at="2026-12-01T04:00:00Z")
    assert settle(r,g)["outcome"]=="push"
    assert settle(r,dict(g,home_score=104))["outcome"]=="win"
    assert settle(r,dict(g,home_score=102))["outcome"]=="loss"
    assert settle(r,dict(g,status="Live")) is None
    assert summarize([r],[g])["spread"]["accuracy"] is None
    print("Synthetic settlement tests PASS")
