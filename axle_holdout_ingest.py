import json
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen
from axle_holdout_capture import utc

URL="https://raw.githubusercontent.com/kelvin53461903/nba-ai-prediction/main/data/odds_latest.json"

def audit(payload, now):
    if payload.get("source")!="The Odds API": raise ValueError("unexpected source")
    retrieved=utc(payload["retrieved_at_utc"])
    if not now-timedelta(hours=12)<=retrieved<=now:
        return {"status":"stale_or_future","eligible_events":0}
    count=0
    for e in payload["events"]:
        try:
            if utc(e["commence_time"])<=now: continue
            if any(utc(b["last_update"])<=retrieved and utc(b["last_update"])>=now-timedelta(hours=12) for b in e["bookmakers"]):
                count+=1
        except (KeyError,ValueError,TypeError): continue
    return {"status":"research_input_only","eligible_events":count,"retrieved_at":retrieved.isoformat(),"predictions_written":0}

if __name__=="__main__":
    with urlopen(URL,timeout=20) as response:
        payload=json.load(response)
    print(json.dumps(audit(payload,datetime.now(timezone.utc))))
