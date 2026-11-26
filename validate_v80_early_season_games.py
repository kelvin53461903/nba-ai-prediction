"""Validate the expanded 2020-21 to 2023-24 NBA CSV before any database import."""
import csv, hashlib, json, sys
from collections import Counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

PATH=Path("data/nba_v80_historical_games_2020_2023.csv")
EXPECTED={"2020-21","2021-22","2022-23","2023-24"}
EXPECTED_REGULAR={"2020-21":1080,"2021-22":1230,"2022-23":1230,"2023-24":1230}
REGULAR_END={"2020-21":"2021-05-16","2021-22":"2022-04-10","2022-23":"2023-04-09","2023-24":"2024-04-14"}
CUTOFF=datetime(2026,4,2,tzinfo=timezone.utc)
REQUIRED={"game_id","season","season_type","home_team_id","away_team_id","home_team","away_team",
 "commence_time_utc","home_score","away_score","total_score","score_margin","home_win",
 "game_status","source","verified_at_utc"}

def parse(value):
 d=datetime.fromisoformat(value.replace("Z","+00:00"))
 if d.tzinfo is None: raise ValueError("timestamp missing timezone")
 return d.astimezone(timezone.utc)

def main():
 if not PATH.is_file(): raise RuntimeError(f"Missing collector output: {PATH}")
 with PATH.open(newline="",encoding="utf-8-sig") as f:
  reader=csv.DictReader(f)
  if not reader.fieldnames or not REQUIRED.issubset(reader.fieldnames):
   raise RuntimeError("Historical CSV header is incomplete")
  rows=list(reader)
 if not rows: raise RuntimeError("Historical CSV is empty")
 ids=set(); seasons=Counter(); types=Counter()
 for n,r in enumerate(rows,start=2):
  gid=int(r["game_id"])
  if gid<=0 or gid in ids: raise RuntimeError(f"Invalid/duplicate game ID at CSV line {n}")
  ids.add(gid)
  season=r["season"].strip()
  if season not in EXPECTED: raise RuntimeError(f"Unexpected season {season} at line {n}")
  seasons[season]+=1
  if r["season_type"] not in {"Regular Season","Playoffs","In-Season Tournament Final"}: raise RuntimeError(f"Unexpected season type at line {n}")
  types[r["season_type"]]+=1
  tip=parse(r["commence_time_utc"]); verified=parse(r["verified_at_utc"])
  game_day=tip.astimezone(ZoneInfo("America/New_York")).date().isoformat()
  if season=="2023-24" and game_day=="2023-12-09" and {r["home_team"],r["away_team"]}=={"Los Angeles Lakers","Indiana Pacers"}:
   expected_type="In-Season Tournament Final"
  else:
   expected_type="Regular Season" if game_day<=REGULAR_END[season] else "Playoffs"
  if r["season_type"]!=expected_type: raise RuntimeError(f"Season type does not match official calendar at line {n}")
  if tip>=CUTOFF or verified<=tip: raise RuntimeError(f"Cutoff/verification timestamp failure at line {n}")
  hs=int(r["home_score"]); aws=int(r["away_score"])
  if hs<0 or aws<0 or hs==aws: raise RuntimeError(f"Invalid final score at line {n}")
  if int(r["total_score"])!=hs+aws or int(r["score_margin"])!=hs-aws: raise RuntimeError(f"Derived score mismatch at line {n}")
  if r["home_win"].lower() != str(hs>aws).lower(): raise RuntimeError(f"Winner mismatch at line {n}")
  if r["game_status"]!="Final" or int(r["home_team_id"])==int(r["away_team_id"]): raise RuntimeError(f"Status/team mismatch at line {n}")
 for season in sorted(EXPECTED):
  if seasons[season]<EXPECTED_REGULAR[season]: raise RuntimeError(f"Season count below regular-season minimum for {season}: {seasons[season]}")
  regular=sum(1 for r in rows if r["season"]==season and r["season_type"]=="Regular Season")
  playoffs=sum(1 for r in rows if r["season"]==season and r["season_type"]=="Playoffs")
  cup_final=sum(1 for r in rows if r["season"]==season and r["season_type"]=="In-Season Tournament Final")
  expected_cup=1 if season=="2023-24" else 0
  if regular!=EXPECTED_REGULAR[season] or playoffs<70 or cup_final!=expected_cup:
   raise RuntimeError(f"Official season coverage mismatch for {season}: regular={regular}, playoffs={playoffs}, cup_final={cup_final}")
 digest=hashlib.sha256(PATH.read_bytes()).hexdigest()
 result={"status":"PASS","rows":len(rows),"unique_game_ids":len(ids),"season_counts":dict(sorted(seasons.items())),
  "season_type_counts":dict(types),"cutoff_exclusive_utc":CUTOFF.isoformat(),"sha256":digest,
  "note":"Validated CSV only. No Neon writes have occurred."}
 Path("v80_early_seasons_validation.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
 print(json.dumps(result,indent=2))
 print("PASS: expanded historical CSV integrity checks")
if __name__=="__main__":
 try: main()
 except Exception as exc:
  print(f"EARLY-SEASON CSV VALIDATION FAILED: {type(exc).__name__}: {exc}",file=sys.stderr); sys.exit(1)
