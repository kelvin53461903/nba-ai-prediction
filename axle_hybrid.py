"""Experimental score baseline; advanced snapshots require verified provenance."""
from axle_elo import Elo
from collections import defaultdict
from itertools import groupby
from datetime import datetime
import math

def advanced_score(home, away, tip):
    for row in (home, away):
        if row.get("source") != "NBA.com" or row.get("is_reconstructed") is not False:
            raise ValueError("Unverified advanced snapshot")
        available=datetime.fromisoformat(row["available_at_utc"])
        captured=datetime.fromisoformat(row["captured_at_utc"])
        if not captured <= available < tip or row["cutoff_date"] >= tip.date().isoformat():
            raise ValueError("Snapshot not available before game")
        if not all(math.isfinite(float(row[k])) and float(row[k])>0 for k in ("offensive_rating","defensive_rating","pace")):
            raise ValueError("Invalid advanced values")
    if home["team_id"] == away["team_id"] or home["season"] != away["season"]:
        raise ValueError("Invalid matchup snapshots")
    pace=(float(home["pace"])+float(away["pace"]))/2
    return tuple(pace*(float(a["offensive_rating"])+float(b["defensive_rating"]))/200 for a,b in ((home,away),(away,home)))

def evaluate(games):
    elo=Elo()
    hist=defaultdict(list)
    errors=[[],[]]
    def avg(team,k):
        rows=hist[team][-10:]
        return sum(r[k] for r in rows)/len(rows) if rows else 114
    for day,group in groupby(sorted(games,key=lambda g:g["date"]),key=lambda g:g["date"]):
        batch=list(group)
        season=batch[0]["season"]
        if elo.season is not None and elo.season != season: hist.clear()
        elo.start_season(season)
        predictions=[]
        for g in batch:
            h,a=g["home"],g["away"]
            hp=(avg(h,0)+avg(a,1))/2+1.5
            ap=(avg(a,0)+avg(h,1))/2-1.5
            diff=elo.ratings[h]-elo.ratings[a]+65
            p=elo.predict(h,a)
            predictions.append((g,p))
            if day >= "2026-01-01":
                total=hp+ap
                for k,m in enumerate((hp-ap,0.5*(hp-ap)+0.5*diff*.04)):
                    errors[k].append((abs((total+m)/2-g["hp"]),abs((total-m)/2-g["ap"]),abs(m-g["hp"]+g["ap"]),abs(total-g["hp"]-g["ap"])))
        for g,p in predictions:
            h,a=g["home"],g["away"]
            elo.update(h,a,g["hp"],g["ap"],p)
            hist[h].append((g["hp"],g["ap"]))
            hist[a].append((g["ap"],g["hp"]))
    return [dict(n=len(e),**dict(zip(("home_mae","away_mae","margin_mae","total_mae"),(sum(col)/len(e) for col in zip(*e))))) for e in errors]
