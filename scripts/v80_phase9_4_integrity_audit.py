#!/usr/bin/env python3
"""Phase 9.4 offline integrity audit for paired historical NBA odds.

No network access, no paid endpoints and no production writes. The validator
accepts only normalized paired quote rows and reports whether a single
bookmaker/snapshot contains all three markets for each event.
"""
from __future__ import annotations
import json, math, sys
from collections import defaultdict
from pathlib import Path
from datetime import datetime

MARKETS=("h2h","spreads","totals")

def _valid_ts(value):
 if not isinstance(value,str) or not value.strip(): return False
 try: dt=datetime.fromisoformat(value.replace("Z","+00:00"))
 except ValueError: return False
 return dt.tzinfo is not None and dt.utcoffset() is not None

def _prob_pair(a,b):
 return (isinstance(a,(int,float)) and isinstance(b,(int,float))
  and math.isfinite(a) and math.isfinite(b)
  and 0 < a < 1 and 0 < b < 1 and abs(a+b-1.0)<=1e-8)

def _price_pair(a,b):
 return (isinstance(a,(int,float)) and isinstance(b,(int,float))
  and math.isfinite(a) and math.isfinite(b) and a>1 and b>1)

def validate_row(row):
 if not isinstance(row,dict): return "ROW_NOT_OBJECT"
 if row.get("provider")!="the-odds-api": return "PROVIDER_INVALID"
 if row.get("sport_key")!="basketball_nba": return "SPORT_INVALID"
 for key in ("event_id","bookmaker","home_team","away_team"):
  if not isinstance(row.get(key),str) or not row[key].strip(): return "IDENTITY_MISSING"
 if row["home_team"]==row["away_team"]: return "TEAM_IDENTITY_COLLISION"
 if not _valid_ts(row.get("snapshot_timestamp")) or not _valid_ts(row.get("commence_time")):
  return "TIMESTAMP_INVALID"
 market=row.get("market")
 if market not in MARKETS: return "MARKET_INVALID"
 if market=="h2h":
  if not _price_pair(row.get("home_price_decimal"),row.get("away_price_decimal")): return "H2H_PRICE_PAIR_INVALID"
  if not _prob_pair(row.get("home_no_vig_probability"),row.get("away_no_vig_probability")): return "H2H_PROBABILITY_PAIR_INVALID"
 elif market=="spreads":
  if not _price_pair(row.get("home_price_decimal"),row.get("away_price_decimal")): return "SPREAD_PRICE_PAIR_INVALID"
  hp,ap=row.get("home_point"),row.get("away_point")
  if not all(isinstance(x,(int,float)) and math.isfinite(x) for x in (hp,ap)) or abs(hp+ap)>0.01:
   return "SPREAD_LINE_PAIR_INVALID"
  if not _prob_pair(row.get("home_no_vig_probability"),row.get("away_no_vig_probability")): return "SPREAD_PROBABILITY_PAIR_INVALID"
 else:
  if not _price_pair(row.get("over_price_decimal"),row.get("under_price_decimal")): return "TOTAL_PRICE_PAIR_INVALID"
  op,up=row.get("over_no_vig_probability"),row.get("under_no_vig_probability")
  if not _prob_pair(op,up): return "TOTAL_PROBABILITY_PAIR_INVALID"
  ol,ul=row.get("total_point"),row.get("under_point",row.get("total_point"))
  if not isinstance(ol,(int,float)) or not isinstance(ul,(int,float)) or not math.isfinite(ol) or not math.isfinite(ul) or abs(ol-ul)>0.01:
   return "TOTAL_LINE_PAIR_INVALID"
 return None

def audit_rows(rows):
 errors=[]; seen=set(); groups=defaultdict(set); counts={m:0 for m in MARKETS}
 for i,row in enumerate(rows):
  err=validate_row(row)
  if err:
   errors.append({"row_index":i,"error":err}); continue
  key=(row["event_id"],row["bookmaker"],row["snapshot_timestamp"],row["market"])
  if key in seen:
   errors.append({"row_index":i,"error":"DUPLICATE_MARKET_SNAPSHOT"})
   continue
  seen.add(key); groups[key[:3]].add(key[3]); counts[key[3]]+=1
 complete=sum(1 for markets in groups.values() if set(MARKETS).issubset(markets))
 return {
  "input_rows":len(rows),"valid_unique_rows":len(seen),"invalid_rows":len(errors),
  "market_row_counts":counts,"event_bookmaker_snapshot_groups":len(groups),
  "complete_three_market_groups":complete,
  "partial_groups":len(groups)-complete,
  "errors":errors,
  "integrity_status":"PASS" if rows and not errors else "FAIL",
  "roi_clv_status":"NOT_CALCULABLE_WITHOUT_SETTLEMENTS_AND_COMPARABLE_OPEN_CLOSE_QUOTES",
  "historical_prices_downloaded_by_this_audit":False,
  "paid_api_called_by_this_audit":False,
  "production_database_writes":0
 }

def main():
 source=Path(sys.argv[1]) if len(sys.argv)>1 else Path("artifacts/v80_phase9/normalized_historical_quotes.json")
 target=Path(sys.argv[2]) if len(sys.argv)>2 else Path("artifacts/v80_phase9/phase9_4_integrity_report.json")
 payload=json.loads(source.read_text(encoding="utf-8"))
 rows=payload.get("rows") if isinstance(payload,dict) else None
 if not isinstance(rows,list): raise RuntimeError("Input must be a JSON object with a rows array")
 report=audit_rows(rows)
 target.parent.mkdir(parents=True,exist_ok=True)
 target.write_text(json.dumps(report,indent=2),encoding="utf-8")
 print(json.dumps(report,indent=2))
 if report["integrity_status"]!="PASS": raise SystemExit("Phase 9.4 integrity audit failed")
 print(f"RESULT: PHASE 9.4 OFFLINE INTEGRITY AUDIT PASS; report={target}")
if __name__=="__main__": main()
