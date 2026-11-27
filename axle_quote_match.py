import json,unicodedata
from datetime import datetime,timezone,timedelta
from urllib.request import urlopen
from collections import Counter
from axle_public_archive import load
from axle_holdout_ingest import URL
from axle_holdout_capture import utc

def name(s):
    n="".join(c for c in unicodedata.normalize("NFKD",s.casefold()) if c.isalnum())
    return {"laclippers":"losangelesclippers","lakers":"losangeleslakers"}.get(n,n)

def match(schedule,teams,payload,now):
    names={str(t["team_id"]):name(t["full_name"]) for t in teams}
    retrieved=utc(payload["retrieved_at_utc"])
    if payload["source"]!="The Odds API" or not now-timedelta(hours=12)<=retrieved<=now: raise ValueError("snapshot provenance")
    counts=Counter()
    for g in schedule:
        tip=g["start_time"]
        if g["status"]!="scheduled" or not tip or not now<tip<=now+timedelta(hours=24): continue
        h,a=names.get(str(g["home_team_id"])),names.get(str(g["away_team_id"]))
        if not h or not a: counts["missing_team"]+=1; continue
        events=[e for e in payload["events"] if name(e["home_team"])==h and name(e["away_team"])==a and abs((utc(e["commence_time"])-tip).total_seconds())<=300]
        if len(events)!=1:
            counts["unmatched_or_ambiguous"]+=1
            pairs=[e for e in payload["events"] if name(e["home_team"])==h and name(e["away_team"])==a]
            reverse=[e for e in payload["events"] if name(e["home_team"])==a and name(e["away_team"])==h]
            print("MATCH_DIAGNOSTIC",json.dumps(dict(game_id=g["game_id"],home=h,away=a,tip=tip.isoformat(),pair_offsets_seconds=[(utc(e["commence_time"])-tip).total_seconds() for e in pairs],reverse_count=len(reverse),strict_candidates=len(events))))
            continue
        counts["matched"]+=1
        markets=set()
        for b in events[0]["bookmakers"]:
            if not now-timedelta(hours=12)<=utc(b["last_update"])<=retrieved: continue
            for m in b["markets"]:
                k=m["key"]; outcomes=m["outcomes"]
                if k not in ("h2h","spreads","totals") or len(outcomes)!=2: continue
                if not m.get("last_update") or not now-timedelta(hours=12)<=utc(m["last_update"])<=retrieved: continue
                if not all(isinstance(o["price"],(float,int)) and 1<o["price"]<1000 for o in outcomes): continue
                if k in ("h2h","spreads") and {name(o["name"]) for o in outcomes}!={h,a}: continue
                if k=="spreads" and abs(sum(o["point"] for o in outcomes))>1e-8: continue
                if k=="totals" and ({o["name"] for o in outcomes}!={"Over","Under"} or outcomes[0]["point"]!=outcomes[1]["point"]): continue
                markets.add(k)
        counts.update(markets)
    return dict(counts)
if __name__=="__main__":
    schedule,_=load("schedule")
    teams,_=load("team_seasons")
    with urlopen(URL,timeout=20) as r: payload=json.load(r)
    print("QUOTE_MATCH",json.dumps(match(schedule,teams,payload,datetime.now(timezone.utc))))
