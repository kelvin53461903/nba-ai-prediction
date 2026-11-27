"""Offline intake for prospective research. No API or production database access."""
import json, hashlib, math, sys
from pathlib import Path
from datetime import datetime, timezone

def utc(s):
    d=datetime.fromisoformat(s.replace("Z","+00:00"))
    if d.utcoffset() is None: raise ValueError("timezone required")
    return d.astimezone(timezone.utc)

def capture(record, directory, now=None):
    now=now or datetime.now(timezone.utc)
    tip=utc(record["tip"])
    quote=utc(record["quote_at"])
    feature=utc(record["feature_available_at"])
    prediction=utc(record["prediction_at"])
    if not utc("2026-11-29T00:00:00Z")<=tip<utc("2027-04-01T00:00:00Z"):
        raise ValueError("outside holdout")
    if not max(quote,feature)<=prediction<=now<tip:
        raise ValueError("not prospective")
    models={"moneyline":"Elo","spread":"Rolling 10","total":"Rolling 20"}
    market=record["market"]
    if record["model"]!=models[market]: raise ValueError("model not frozen")
    for k in ("game_id","provider","quote_source","feature_source","model_commit"):
        if not isinstance(record[k],str) or not record[k].strip(): raise ValueError(k)
    if not math.isfinite(float(record["prediction"])): raise ValueError("prediction")
    if market!="moneyline" and not math.isfinite(float(record["line"])): raise ValueError("line")
    if "price" in record and record["price"] is not None:
        price=float(record["price"])
        fmt=record.get("price_format")
        if not math.isfinite(price) or not ((fmt=="decimal" and price>1) or (fmt=="american" and abs(price)>=100)): raise ValueError("price")
    payload=dict(record,captured_at=now.isoformat(),source_independently_verified=False,research_only=True)
    raw=json.dumps(payload,sort_keys=True,allow_nan=False).encode()
    key=hashlib.sha256((record["game_id"]+"|"+market).encode()).hexdigest()
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    with (directory/(key+".json")).open("xb") as f: f.write(raw)
    return hashlib.sha256(raw).hexdigest()

if __name__=="__main__":
    print(capture(json.loads(Path(sys.argv[1]).read_text()),sys.argv[2]))
