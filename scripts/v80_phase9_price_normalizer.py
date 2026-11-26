#!/usr/bin/env python3
"""Strict normalizer for The Odds API historical NBA featured-market snapshots.

This module does not make network calls. It accepts a paid historical snapshot
response only after a separately approved data-acquisition step. Quotes are
kept paired within one bookmaker and one market; no cross-book or cross-time
price stitching is allowed.
"""
from __future__ import annotations
import math

def _decimal_price(value):
 try: x=float(value)
 except (TypeError,ValueError): return None
 return x if math.isfinite(x) and x>1.0 else None

def _point(value):
 try: x=float(value)
 except (TypeError,ValueError): return None
 return x if math.isfinite(x) else None

def devig_decimal(price_a,price_b):
 a=_decimal_price(price_a); b=_decimal_price(price_b)
 if a is None or b is None: raise ValueError("Both decimal prices must be finite and > 1")
 ia,ib=1.0/a,1.0/b; total=ia+ib
 return ia/total,ib/total

def _two_outcomes(market):
 if not isinstance(market,dict): return None
 outcomes=market.get("outcomes")
 if not isinstance(outcomes,list) or len(outcomes)!=2: return None
 return outcomes

def normalize_bookmaker_event(event,bookmaker,snapshot_timestamp):
 """Return validated h2h/spreads/totals pairs for one bookmaker/event."""
 if not isinstance(event,dict) or not isinstance(bookmaker,dict): return []
 home=event.get("home_team"); away=event.get("away_team")
 book_key=bookmaker.get("key")
 if not home or not away or not book_key: return []
 markets={m.get("key"):m for m in bookmaker.get("markets",[]) if isinstance(m,dict)}
 records=[]
 # Moneyline: exact home/away pair.
 outcomes=_two_outcomes(markets.get("h2h"))
 if outcomes:
  by_name={o.get("name"):o for o in outcomes if isinstance(o,dict)}
  h=by_name.get(home); a=by_name.get(away)
  hp=_decimal_price(h.get("price")) if h else None
  ap=_decimal_price(a.get("price")) if a else None
  if hp and ap:
   hn,an=devig_decimal(hp,ap)
   records.append({"market":"h2h","bookmaker":book_key,"event_id":event.get("id"),
    "home_team":home,"away_team":away,"snapshot_timestamp":snapshot_timestamp,
    "market_last_update":markets["h2h"].get("last_update"),
    "home_price_decimal":hp,"away_price_decimal":ap,
    "home_no_vig_probability":hn,"away_no_vig_probability":an})
 # Spread: exactly two team outcomes with equal-and-opposite points.
 outcomes=_two_outcomes(markets.get("spreads"))
 if outcomes:
  by_name={o.get("name"):o for o in outcomes if isinstance(o,dict)}
  h=by_name.get(home); a=by_name.get(away)
  hp=_decimal_price(h.get("price")) if h else None
  ap=_decimal_price(a.get("price")) if a else None
  hl=_point(h.get("point")) if h else None
  al=_point(a.get("point")) if a else None
  if hp and ap and hl is not None and al is not None and abs(hl+al)<=0.01:
   hn,an=devig_decimal(hp,ap)
   records.append({"market":"spreads","bookmaker":book_key,"event_id":event.get("id"),
    "home_team":home,"away_team":away,"snapshot_timestamp":snapshot_timestamp,
    "market_last_update":markets["spreads"].get("last_update"),
    "home_point":hl,"away_point":al,"home_price_decimal":hp,"away_price_decimal":ap,
    "home_no_vig_probability":hn,"away_no_vig_probability":an})
 # Total: exact Over/Under pair at the same total line.
 outcomes=_two_outcomes(markets.get("totals"))
 if outcomes:
  by_name={str(o.get("name","")).casefold():o for o in outcomes if isinstance(o,dict)}
  over=by_name.get("over"); under=by_name.get("under")
  op=_decimal_price(over.get("price")) if over else None
  up=_decimal_price(under.get("price")) if under else None
  ol=_point(over.get("point")) if over else None
  ul=_point(under.get("point")) if under else None
  if op and up and ol is not None and ul is not None and abs(ol-ul)<=0.01:
   on,un=devig_decimal(op,up)
   records.append({"market":"totals","bookmaker":book_key,"event_id":event.get("id"),
    "home_team":home,"away_team":away,"snapshot_timestamp":snapshot_timestamp,
    "market_last_update":markets["totals"].get("last_update"),
    "total_point":ol,"over_price_decimal":op,"under_price_decimal":up,
    "over_no_vig_probability":on,"under_no_vig_probability":un})
 return records

def normalize_historical_response(response):
 """Normalize a wrapped historical event odds response into strict paired rows."""
 if not isinstance(response,dict) or not isinstance(response.get("data"),dict):
  raise ValueError("Expected historical event odds wrapper with object data")
 event=response["data"]; snapshot=response.get("timestamp")
 if not snapshot: raise ValueError("Missing historical snapshot timestamp")
 bookmakers=event.get("bookmakers")
 if not isinstance(bookmakers,list): raise ValueError("Missing bookmaker list")
 rows=[]
 for bookmaker in bookmakers:
  rows.extend(normalize_bookmaker_event(event,bookmaker,snapshot))
 return rows
