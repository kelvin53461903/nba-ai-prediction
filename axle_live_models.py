from axle_public_archive import load
from axle_elo import Elo
from collections import defaultdict
from itertools import groupby
from datetime import datetime, timezone, timedelta
import math,json,sqlite3

def run():
    elo=Elo()
    hist=defaultdict(list)
    hashes={}
    for season in (2025,2026,2027):
        schedule,sh=load("schedule",season)
        logs,lh=load("team_game_logs",season)
        hashes[str(season)]=[sh,lh]
        now=datetime.now(timezone.utc)
        grouped=defaultdict(list)
        for x in logs: grouped[x["game_id"]].append(x)
        elo.start_season(season)
        for day,batch in groupby(sorted((g for g in schedule if g["start_time"] and g["status"]=="final" and g["game_type"] in ("regular_season","cup_final","play_in","playoffs") and g["start_time"]<now-timedelta(days=2)),key=lambda g:g["start_time"]),key=lambda g:g["start_time"].date()):
            updates=[]
            for g in batch:
                rows=grouped[g["game_id"]]
                h,a=g["home_team_id"],g["away_team_id"]
                if len(rows)!=2 or {x["team_id"] for x in rows}!={h,a}: continue
                by={x["team_id"]:x for x in rows}
                hp,ap=by[h]["pts"],by[a]["pts"]
                if min(hp,ap)<=0 or hp==ap: continue
                updates.append((h,a,hp,ap,elo.predict(h,a,g["neutral_site"])))
                if season==2027:
                    for t in (h,a):
                        v=[by[t][k] for k in ("off_rating","def_rating","pace")]
                        if all(y is not None and math.isfinite(y) and y>0 for y in v): hist[t].append(v)
            for args in updates: elo.update(*args)
    counts=defaultdict(int)
    for g in schedule:
        if g["status"]!="scheduled" or not g["start_time"] or not now<g["start_time"]<=now+timedelta(hours=24): continue
        h,a=g["home_team_id"],g["away_team_id"]
        if h not in elo.ratings or a not in elo.ratings: continue
        p=elo.predict(h,a,g["neutral_site"])
        assert 0<p<1
        counts["Elo"]+=1
        for n in (10,20):
            if min(len(hist[h]),len(hist[a]))<n: continue
            x,z=[[sum(v[k] for v in hist[t][-n:])/n for k in range(3)] for t in (h,a)]
            pace=(x[2]+z[2])/2
            adv=0 if g["neutral_site"] else 1.5
            hp=pace*(x[0]+z[1])/200+adv
            ap=pace*(z[0]+x[1])/200-adv
            assert math.isfinite(hp-ap) and math.isfinite(hp+ap)
            counts["Rolling "+str(n)]+=1
    print("MODEL_PILOT",json.dumps(dict(counts=counts,source_hashes=hashes,research_only=True,predictions_written=0,reason="quote matching and source permission not verified")))
if __name__=="__main__": run()
