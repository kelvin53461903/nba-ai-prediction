#!/usr/bin/env python3
"""Audit public NBA betting-line parquet coverage; never writes to Neon."""
from __future__ import annotations
import csv, hashlib, json, sys, urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import duckdb

CUTOFF=datetime(2026,4,2,tzinfo=timezone.utc)
GAMES=Path("data/nba_v80_historical_games_cutoff_2026-04-01.csv")
BASE="https://basketball-data.billmill.org/nba/betting_lines/season={season}/data.parquet"
SEASONS={2025:"2024-25",2026:"2025-26"}
EXPECTED_GAMES=2459
OUT=Path("v80_public_betting_lines_audit.json")

def download(season):
    url=BASE.format(season=season)
    req=urllib.request.Request(url,headers={"User-Agent":"NBA-AI-V8.0-Public-Lines-Audit/1.0"})
    with urllib.request.urlopen(req,timeout=120) as response:
        data=response.read()
        final_url=response.geturl()
    if len(data)<1000: raise RuntimeError(f"Season {season}: unexpectedly small parquet file")
    path=Path(f"/tmp/nba_betting_lines_{season}.parquet")
    path.write_bytes(data)
    return path,url,final_url,hashlib.sha256(data).hexdigest(),len(data)

def main():
    if not GAMES.is_file(): raise RuntimeError("Verified NBA games CSV is missing")
    with GAMES.open(newline="",encoding="utf-8-sig") as f:
        games=list(csv.DictReader(f))
    if len(games)!=EXPECTED_GAMES: raise RuntimeError(f"Expected {EXPECTED_GAMES} NBA games; got {len(games)}")
    valid_game_ids={str(int(g["game_id"])) for g in games}
    con=duckdb.connect()
    reports=[]
    all_provider_counts=Counter()
    all_matches=set()
    for season,label in SEASONS.items():
        path,url,final_url,digest,size=download(season)
        desc=con.execute("DESCRIBE SELECT * FROM read_parquet(?)",[str(path)]).fetchall()
        columns={r[0] for r in desc}
        required={"season","game_id","provider_id","provider","home_team_id","away_team_id","close_spread","close_total",
          "close_home_moneyline","close_away_moneyline","close_home_spread_odds","close_away_spread_odds","close_over_odds","close_under_odds"}
        missing=sorted(required-columns)
        if missing: raise RuntimeError(f"{label}: parquet schema missing required columns: {missing}")
        rows=con.execute("""SELECT game_id::VARCHAR,season::INTEGER,provider_id::VARCHAR,provider::VARCHAR,
            home_team_id::VARCHAR,away_team_id::VARCHAR,open_spread,close_spread,open_total,close_total,
            open_home_moneyline,open_away_moneyline,close_home_moneyline,close_away_moneyline,
            open_home_spread_odds,open_away_spread_odds,close_home_spread_odds,close_away_spread_odds,
            open_over_odds,open_under_odds,close_over_odds,close_under_odds,espn_event_id
            FROM read_parquet(?) WHERE season=? ORDER BY game_id,provider_id""",[str(path),season]).fetchall()
        if not rows: raise RuntimeError(f"{label}: parquet returned no rows")
        provider_counts=Counter()
        provider_coverage=defaultdict(lambda:{"games":set(),"spread":0,"total":0,"moneyline":0,"spread_prices":0,"total_prices":0})
        duplicate_keys=set()
        matched_rows=0
        invalid=Counter()
        for r in rows:
            (gid,yr,pid,provider,home_id,away_id,open_spread,close_spread,open_total,close_total,
             ohm,oam,chm,cam,ohsp,oasp,chsp,casp,oo,ou,co,cu,event_id)=r
            gid=str(int(gid))
            if gid not in valid_game_ids: continue
            matched_rows+=1
            key=(gid,pid)
            if key in duplicate_keys: raise RuntimeError(f"{label}: duplicate game/provider key {key}")
            duplicate_keys.add(key)
            provider_counts[pid]+=1
            all_provider_counts[(label,pid,provider)]+=1
            p=provider_coverage[pid]
            p["games"].add(gid)
            if close_spread is not None and abs(float(close_spread))<=40: p["spread"]+=1
            elif close_spread is not None: invalid["close_spread_out_of_range"]+=1
            if close_total is not None and 150<=float(close_total)<=300: p["total"]+=1
            elif close_total is not None: invalid["close_total_out_of_range"]+=1
            if chm is not None and cam is not None and int(chm)!=0 and int(cam)!=0: p["moneyline"]+=1
            if chsp is not None and casp is not None: p["spread_prices"]+=1
            if co is not None and cu is not None: p["total_prices"]+=1
            if gid not in all_matches: all_matches.add(gid)
        providers=[]
        for pid,n in sorted(provider_counts.items()):
            p=provider_coverage[pid]
            provider_name=next(x[3] for x in rows if str(x[2])==pid)
            providers.append({"provider_id":pid,"provider":provider_name,"rows":n,"unique_games":len(p["games"]),
              "close_spread_rows":p["spread"],"close_total_rows":p["total"],"close_moneyline_rows":p["moneyline"],
              "close_spread_price_rows":p["spread_prices"],"close_total_price_rows":p["total_prices"]})
        reports.append({"season_end_year":season,"season_label":label,"source_url":url,"resolved_url":final_url,
          "file_bytes":size,"sha256":digest,"parquet_rows":len(rows),"matched_provider_rows":matched_rows,
          "unique_matched_games":len(set(str(int(r[0])) for r in rows if str(int(r[0])) in valid_game_ids)),
          "providers":providers,"invalid_values":dict(invalid)})
    con.close()
    result={"status":"AUDIT_ONLY_NO_DATABASE_WRITES","source_project":"https://github.com/llimllib/nba_data",
      "source_dictionary":"https://github.com/llimllib/nba_data/blob/main/docs/DATA_DICTIONARY.md",
      "source_note":"Provider rows are kept separate. odds_api_consensus is a median consensus line, not an executable sportsbook price. ESPN provider rows may contain actual book prices. Dataset license/redistribution rights must be reviewed separately; public availability is not treated as a license.",
      "cutoff_exclusive_utc":CUTOFF.isoformat(),"verified_nba_games":len(games),"unique_games_with_any_market_line":len(all_matches),
      "providers":[{"season":s,"provider_id":pid,"provider":name,"rows":n} for (s,pid,name),n in sorted(all_provider_counts.items())],
      "seasons":reports}
    OUT.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))
    print("PASS: public betting-line coverage audit complete; Neon unchanged")
if __name__=="__main__":
    try: main()
    except Exception as exc:
        print(f"PUBLIC BETTING-LINES AUDIT FAILED: {type(exc).__name__}: {exc}",file=sys.stderr); sys.exit(1)
