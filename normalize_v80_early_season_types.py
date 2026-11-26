"""Normalize verified BALLDONTLIE season labels using official regular-season end dates."""
import csv, os, sys
from pathlib import Path
from datetime import datetime, timezone

PATH=Path("data/nba_v80_historical_games_2020_2023.csv")
REGULAR_END={"2020-21":"2021-05-16","2021-22":"2022-04-10","2022-23":"2023-04-09","2023-24":"2024-04-14"}
def main():
 if not PATH.is_file(): raise RuntimeError("Downloaded historical CSV is missing")
 with PATH.open(newline="",encoding="utf-8-sig") as f:
  reader=csv.DictReader(f); fields=reader.fieldnames; rows=list(reader)
 if not fields or not {"game_id","season","commence_time_utc","season_type"}.issubset(fields): raise RuntimeError("Historical CSV schema mismatch")
 changed=0
 for row in rows:
  season=row["season"]
  if season not in REGULAR_END: raise RuntimeError(f"Unexpected season: {season}")
  tip=datetime.fromisoformat(row["commence_time_utc"].replace("Z","+00:00"))
  expected="Regular Season" if tip.date().isoformat()<=REGULAR_END[season] else "Playoffs"
  if row["season_type"]!=expected:
   row["season_type"]=expected; changed+=1
 temp=PATH.with_suffix(".normalized.tmp")
 with temp.open("w",newline="",encoding="utf-8-sig") as f:
  writer=csv.DictWriter(f,fieldnames=fields); writer.writeheader(); writer.writerows(rows)
 os.replace(temp,PATH)
 print(f"PASS: normalized {changed} season-type labels using official regular-season end dates")
if __name__=="__main__":
 try: main()
 except Exception as exc:
  print(f"SEASON TYPE NORMALIZATION FAILED: {type(exc).__name__}: {exc}",file=sys.stderr); sys.exit(1)
