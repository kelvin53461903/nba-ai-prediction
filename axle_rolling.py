from collections import defaultdict
from itertools import groupby
from datetime import datetime,timedelta
import math

def evaluate(games):
    hist=defaultdict(list)
    errors=defaultdict(list)
    for day,batch in groupby(sorted(games,key=lambda g:g["tip"]),lambda g:datetime.fromisoformat(g["tip"]).date()):
        batch=list(batch)
        for g in batch:
            h,a=g["home"],g["away"]
            if day.isoformat()<"2026-01-01": continue
            # Conservative two-day embargo; no same-day or previous-day results.
            hs=[v for d,v in hist[g["season"],h] if d<=day-timedelta(days=2)]
            aws=[v for d,v in hist[g["season"],a] if d<=day-timedelta(days=2)]
            if min(len(hs),len(aws))<20: continue
            for n in (5,10,20):
                x,z=[[sum(v[k] for v in s[-n:])/n for k in range(3)] for s in (hs,aws)]
                pace=(x[2]+z[2])/2
                advantage=0 if g["neutral"] else 1.5
                hp=pace*(x[0]+z[1])/200+advantage
                ap=pace*(z[0]+x[1])/200-advantage
                margin=hp-ap
                p=1/(1+math.exp(-margin/7))
                y=int(g["hp"]>g["ap"])
                errors[n].append((int((p>=.5)==bool(y)),(p-y)**2,abs(hp-g["hp"]),abs(ap-g["ap"]),abs(margin-g["hp"]+g["ap"]),abs(hp+ap-g["hp"]-g["ap"])))
        for g in batch:
            for team,v in ((g["home"],g["archive_values"][:3]),(g["away"],g["archive_values"][3:])):
                hist[g["season"],team].append((day,v))
    return {"research_only":True,"point_in_time_verified":False,"incomplete_input":len(games)!=2459,"embargo_days":2,"metrics":{str(n):dict(n=len(e),**dict(zip(("accuracy","brier","home_mae","away_mae","margin_mae","total_mae"),[sum(c)/len(e) for c in zip(*e)]))) for n,e in errors.items()}}
