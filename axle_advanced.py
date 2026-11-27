"""Experimental Elo feature ablation; not a production predictor."""
from axle_elo import Elo
from collections import defaultdict
from datetime import date
from itertools import groupby
import math

def evaluate(games, home=65, rest=0, form=0):
    model=Elo(home_advantage=home)
    hist=defaultdict(list)
    metrics=[[],[]]
    seen=set()
    def gap(t,d):
        return min(3,max(0,(date.fromisoformat(d)-date.fromisoformat(hist[t][-1][0])).days-1)) if hist[t] else 1
    def avg(t):
        a=hist[t][-10:]
        return sum(x[1] for x in a)/len(a) if a else 0
    for d, group in groupby(sorted(games,key=lambda g:g["date"]),key=lambda g:g["date"]):
        batch=list(group)
        if len({g["season"] for g in batch})!=1: raise ValueError("Mixed seasons")
        season=batch[0]["season"]
        if model.season is not None and model.season!=season: hist.clear()
        model.start_season(season)
        preds=[]
        for g in batch:
            h,a=g["home"],g["away"]
            if g["id"] in seen or h==a or min(g["hp"],g["ap"])<=0 or g["hp"]==g["ap"]: raise ValueError("Invalid game")
            seen.add(g["id"])
            diff=model.ratings[h]-model.ratings[a]+(0 if g.get("neutral") else home)+rest*(gap(h,d)-gap(a,d))+form*(avg(h)-avg(a))
            p=1/(1+10**(-max(-2000,min(2000,diff))/400))
            preds.append((g,p))
            if season=="2025-26": metrics[int(d>="2026-01-01")].append((p,int(g["hp"]>g["ap"])))
        for g,p in preds:
            h,a=g["home"],g["away"]
            model.update(h,a,g["hp"],g["ap"],p)
            margin=g["hp"]-g["ap"]
            hist[h].append((d,margin))
            hist[a].append((d,-margin))
    def score(rows):
        n=len(rows)
        if not n: raise ValueError("Empty evaluation period")
        return dict(n=n,accuracy=sum((p>=.5)==bool(y) for p,y in rows)/n,brier=sum((p-y)**2 for p,y in rows)/n,log_loss=-sum(y*math.log(p)+(1-y)*math.log1p(-p) for p,y in rows)/n)
    return [score(rows) for rows in metrics]

CONFIGS={"baseline":(65,0,0),"home45":(45,0,0),"home85":(85,0,0),"rest":(65,15,0),"form":(65,0,4),"rest_form":(65,15,4)}
