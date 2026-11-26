"""Collect additional 2020-21 through 2023-24 NBA results for V8.0 market backtests.
Audit-only: creates a CSV artifact and never writes to Neon.
"""
import csv, datetime as dt, hashlib, os, pathlib, sys
import requests
from collect_bdl_historical_games import fetch_season, FIELDS

START_SEASON=2020
END_SEASON=2023
CUTOFF=dt.datetime(2026,4,2,tzinfo=dt.timezone.utc)
OUT=pathlib.Path("data/nba_v80_historical_games_2020_2023.csv")

def main():
    key=os.environ.get("BDL_API_KEY","").strip()
    if not key: raise RuntimeError("BDL_API_KEY GitHub secret is missing")
    session=requests.Session()
    session.headers.update({"Authorization":key,"Accept":"application/json"})
    rows=[]
    for year in range(START_SEASON,END_SEASON+1):
        season_rows=fetch_season(session,year,min_interval=12.5,max_pages=100)
        # Match the existing V8.0 evaluation scope: regular season and playoffs only.
        season_rows=[r for r in season_rows if r["season_type"] in {"Regular Season","Playoffs","In-Season Tournament Final"}
          and dt.datetime.fromisoformat(r["commence_time_utc"].replace("Z","+00:00"))<CUTOFF]
        print(f"SEASON {year}: eligible regular/playoff finals={len(season_rows)}",flush=True)
        rows.extend(season_rows)
    unique={}
    for row in rows:
        gid=int(row["game_id"])
        if gid in unique and unique[gid]!=row: raise RuntimeError(f"Conflicting duplicate NBA game ID {gid}")
        unique[gid]=row
    final=sorted(unique.values(),key=lambda r:(r["commence_time_utc"],int(r["game_id"])))
    if len(final)<3500: raise RuntimeError(f"Too few eligible historical games: {len(final)}")
    counts={}
    for row in final: counts[row["season"]]=counts.get(row["season"],0)+1
    OUT.parent.mkdir(parents=True,exist_ok=True)
    with OUT.open("w",newline="",encoding="utf-8-sig") as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS); writer.writeheader(); writer.writerows(final)
    digest=hashlib.sha256(OUT.read_bytes()).hexdigest()
    print(f"PASS: {len(final)} unique historical finals; seasons={counts}; sha256={digest}",flush=True)
    print("AUDIT ONLY: no database writes; CSV retained as a GitHub Actions artifact.",flush=True)
if __name__=="__main__":
    try: main()
    except Exception as exc:
        print(f"EARLY-SEASON GAME COLLECTION FAILED: {type(exc).__name__}: {exc}",file=sys.stderr); sys.exit(1)
