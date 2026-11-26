#!/usr/bin/env python3
"""Phase 9: free historical-coverage probe for The Odds API.

This deliberately does NOT call the paid historical odds endpoint or download
bookmaker prices. It uses only historical events and historical event markets
coverage endpoints (documented as 1 credit/request and available on free plans).
The optional paid endpoint is excluded from this workflow and requires separate
explicit approval before implementation.
"""
from __future__ import annotations
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path
import requests

BASE="https://api.the-odds-api.com/v4/historical/sports/basketball_nba"
SAMPLES=[
 "2021-02-02T00:10:00Z",
 "2023-02-01T23:40:00Z",
 "2025-02-01T21:40:00Z",
 "2026-02-01T20:10:00Z",
]
OUT=Path("artifacts/v80_phase9")
TIMEOUT=25

def get_json(session,url,params):
 response=session.get(url,params=params,timeout=TIMEOUT)
 remaining=response.headers.get("x-requests-remaining")
 used=response.headers.get("x-requests-used")
 if response.status_code!=200:
  # Never echo request URL: it contains the API key query parameter.
  return {"ok":False,"http_status":response.status_code,
          "error_excerpt":response.text[:300],"credits_remaining":remaining,
          "credits_used":used}
 try: data=response.json()
 except ValueError: return {"ok":False,"http_status":response.status_code,"error":"Non-JSON response"}
 return {"ok":True,"http_status":response.status_code,"data":data,
         "credits_remaining":remaining,"credits_used":used}

def unwrap_data(payload):
 if isinstance(payload,dict) and "data" in payload: return payload["data"]
 if isinstance(payload,list): return payload
 return []

def summarize_markets(payload):
 root=unwrap_data(payload)
 books=root.get("bookmakers",[]) if isinstance(root,dict) else root if isinstance(root,list) else []
 by_book=[]
 union=set()
 for book in books:
  keys=sorted({str(m.get("key")) for m in book.get("markets",[]) if isinstance(m,dict) and m.get("key")})
  union.update(keys)
  by_book.append({"bookmaker_key":book.get("key"),"market_keys":keys})
 return {"bookmaker_count":len(by_book),"market_keys_union":sorted(union),
         "has_h2h":"h2h" in union,"has_spreads":"spreads" in union,
         "has_totals":"totals" in union,"bookmakers":by_book}

def run_probe(api_key,session=None):
 if not api_key or not api_key.strip():
  raise RuntimeError("Missing THE_ODDS_API_KEY secret")
 session=session or requests.Session()
 results=[]
 for stamp in SAMPLES:
  event_resp=get_json(session,BASE+"/events",{"apiKey":api_key,"date":stamp})
  item={"requested_snapshot_utc":stamp,"historical_events_ok":event_resp["ok"],
        "historical_events_http_status":event_resp.get("http_status"),
        "credits_remaining_after_events":event_resp.get("credits_remaining")}
  if not event_resp["ok"]:
   item["coverage_status"]="EVENT_COVERAGE_UNAVAILABLE"
   item["error_excerpt"]=event_resp.get("error_excerpt",event_resp.get("error"))
   results.append(item); continue
  events=unwrap_data(event_resp["data"])
  if not isinstance(events,list):
   item["coverage_status"]="UNEXPECTED_EVENTS_SCHEMA"; results.append(item); continue
  item["event_count"]=len(events)
  item["historical_events_response_keys"]=sorted(event_resp["data"].keys()) if isinstance(event_resp["data"],dict) else []
  if not events:
   item["coverage_status"]="NO_EVENTS_AT_SNAPSHOT"; results.append(item); continue
  # One representative event only: keep the free coverage probe inexpensive.
  event=events[0]
  item["sample_event"]={"id":event.get("id"),"home_team":event.get("home_team"),
                        "away_team":event.get("away_team"),"commence_time":event.get("commence_time")}
  market_resp=get_json(session,BASE+f"/events/{event.get('id')}/markets",
    {"apiKey":api_key,"regions":"us","date":stamp})
  item["historical_markets_ok"]=market_resp["ok"]
  item["historical_markets_http_status"]=market_resp.get("http_status")
  item["credits_remaining_after_markets"]=market_resp.get("credits_remaining")
  if market_resp["ok"]:
   summary=summarize_markets(market_resp["data"])
   item["market_coverage_response_shape"]={"type":type(market_resp["data"]).__name__, "keys":sorted(market_resp["data"].keys()) if isinstance(market_resp["data"],dict) else [], "inner_data_keys":sorted(market_resp["data"].get("data",{}).keys()) if isinstance(market_resp["data"],dict) and isinstance(market_resp["data"].get("data"),dict) else [], "data_type":type(market_resp["data"].get("data")).__name__ if isinstance(market_resp["data"],dict) else None}
   item["market_coverage"]=summary
   item["coverage_status"]="MARKET_KEYS_AVAILABLE" if summary["market_keys_union"] else "NO_MARKET_KEYS"
  else:
   item["coverage_status"]="MARKET_COVERAGE_UNAVAILABLE"
   item["market_error_excerpt"]=market_resp.get("error_excerpt",market_resp.get("error"))
  results.append(item)
 return {
  "phase":"V8.0_PHASE9","mode":"FREE_HISTORICAL_COVERAGE_ONLY",
  "provider":"The Odds API","sport":"basketball_nba","regions":"us",
  "checked_at_utc":datetime.now(timezone.utc).isoformat(),
  "sample_snapshots":results,
  "historical_prices_downloaded":False,
  "paid_historical_odds_endpoint_called":False,
  "credits_policy":"Only documented free historical events/markets coverage calls; no paid odds snapshots requested.",
  "release_note":"Coverage discovery is not proof that historical price snapshots can be downloaded on this subscription. Do not infer prices from market-key coverage.",
  "database_writes":0,
  "overall_coverage":"AVAILABLE" if any(x.get("coverage_status")=="MARKET_KEYS_AVAILABLE" for x in results) else "INCONCLUSIVE_OR_UNAVAILABLE"
 }

def main():
 OUT.mkdir(parents=True,exist_ok=True)
 report=run_probe(os.environ.get("THE_ODDS_API_KEY",""))
 path=OUT/"historical_price_coverage_probe.json"
 path.write_text(json.dumps(report,indent=2),encoding="utf-8")
 print(json.dumps(report,indent=2))
 print(f"RESULT: PHASE 9 FREE COVERAGE PROBE COMPLETE; report={path}")
if __name__=="__main__":
 try: main()
 except Exception as exc:
  print(f"PHASE 9 PROBE FAILED: {type(exc).__name__}: {exc}",file=sys.stderr)
  raise
