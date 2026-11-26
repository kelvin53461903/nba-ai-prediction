"""Collect historical NBA games from BALLDONTLIE's Free Games endpoint.

Only final games with valid non-tied scores are exported. No database writes.
The Free plan is limited to 5 requests/minute, so requests are paced.
"""
import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import pathlib
import sys
import time
import requests
from zoneinfo import ZoneInfo

BASE = "https://api.balldontlie.io/v1/games"
FIELDS = [
    "game_id", "season", "season_type", "home_team_id", "away_team_id",
    "home_team", "away_team", "commence_time_utc", "home_score",
    "away_score", "total_score", "score_margin", "home_win",
    "overtime_periods", "game_status", "source", "verified_at_utc",
]


def season_label(year):
    return f"{year}-{(year + 1) % 100:02d}"


def parse_datetime(game):
    value = game.get("datetime") or game.get("date")
    if not value:
        raise ValueError("game missing datetime")
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def fetch_season(session, year, min_interval, max_pages):
    rows = []
    cursor = None
    page = 0
    last_request = 0.0
    while True:
        page += 1
        if page > max_pages:
            raise RuntimeError(f"pagination safety cap reached for {year}")
        wait = min_interval - (time.monotonic() - last_request)
        if wait > 0:
            time.sleep(wait)
        params = {"seasons[]": year, "per_page": 100}
        if cursor is not None:
            params["cursor"] = cursor
        response = session.get(BASE, params=params, timeout=45)
        last_request = time.monotonic()
        if response.status_code == 429:
            retry = int(response.headers.get("Retry-After", "60"))
            print(f"Rate limited; waiting {max(60, retry)} seconds", flush=True)
            time.sleep(max(60, retry))
            continue
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data")
        if not isinstance(data, list):
            raise ValueError("Unexpected BALLDONTLIE response: data is not a list")
        verified = dt.datetime.now(dt.timezone.utc).isoformat()
        for game in data:
            status = str(game.get("status", "")).strip().lower()
            hs, aws = game.get("home_team_score"), game.get("visitor_team_score")
            if status != "final" or hs is None or aws is None:
                continue
            hs, aws = int(hs), int(aws)
            if hs == aws or hs < 0 or aws < 0:
                continue
            home, away = game.get("home_team") or {}, game.get("visitor_team") or {}
            if not home.get("id") or not away.get("id") or home.get("id") == away.get("id"):
                continue
            commence = parse_datetime(game)
            if commence >= dt.datetime.now(dt.timezone.utc):
                continue
            raw_type = str(game.get("season_type") or "").strip().lower()
            type_map = {"regular": "Regular Season", "regular season": "Regular Season",
                        "playoffs": "Playoffs", "playoff": "Playoffs"}
            if raw_type:
                season_type = type_map.get(raw_type)
                if season_type not in {"Regular Season", "Playoffs"}:
                    continue
            else:
                # BALLDONTLIE's games endpoint may expose only a postseason boolean.
                # Apply official season calendar bounds so preseason is never mislabeled regular season.
                season_windows = {
                    2020: ("2020-12-22", "2021-05-16", "2021-07-21"),
                    2021: ("2021-10-19", "2022-04-10", "2022-06-16"),
                    2022: ("2022-10-18", "2023-04-09", "2023-06-12"),
                    2023: ("2023-10-24", "2024-04-14", "2024-06-17"),
                }
                # NBA schedule dates are local to the arena; use Eastern time for the official season calendar.
                game_day = commence.astimezone(ZoneInfo("America/New_York")).date().isoformat()
                start_day, regular_end_day, end_day = season_windows[year]
                if not (start_day <= game_day <= end_day):
                    continue
                if year == 2023 and game_day == "2023-12-09" and {home.get("full_name"), away.get("full_name")} == {"Los Angeles Lakers", "Indiana Pacers"}:
                    season_type = "In-Season Tournament Final"
                else:
                    season_type = "Regular Season" if game_day <= regular_end_day else "Playoffs"
            rows.append({
                "game_id": int(game["id"]),
                "season": season_label(int(game.get("season", year))),
                "season_type": season_type,
                "home_team_id": int(home["id"]),
                "away_team_id": int(away["id"]),
                "home_team": str(home.get("full_name") or home.get("name") or home.get("abbreviation") or home["id"]),
                "away_team": str(away.get("full_name") or away.get("name") or away.get("abbreviation") or away["id"]),
                "commence_time_utc": commence.isoformat(),
                "home_score": hs,
                "away_score": aws,
                "total_score": hs + aws,
                "score_margin": hs - aws,
                "home_win": str(hs > aws).lower(),
                "overtime_periods": None,
                "game_status": "Final",
                "source": "BALLDONTLIE Games API",
                "verified_at_utc": verified,
            })
        print(f"Season {year}: page {page}, received {len(data)}, valid finals so far {len(rows)}", flush=True)
        meta = payload.get("meta") or {}
        cursor = meta.get("next_cursor")
        if not cursor:
            break
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-season", type=int, default=2024)
    parser.add_argument("--end-season", type=int, default=2025)
    parser.add_argument("--out", default="data/v80_historical_games")
    parser.add_argument("--min-interval", type=float, default=12.5)
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.start_season > args.end_season or args.start_season < 1946 or args.end_season > dt.datetime.now().year:
        parser.error("Invalid season range")
    key = os.environ.get("BDL_API_KEY", "").strip()
    if not args.dry_run and not key:
        print("ERROR: BDL_API_KEY secret is missing", file=sys.stderr)
        sys.exit(2)
    if args.dry_run:
        print(f"DRY RUN: would request seasons {args.start_season}-{args.end_season}; no API calls or files written.")
        return
    session = requests.Session()
    session.headers.update({"Authorization": key, "Accept": "application/json"})
    all_rows = []
    for year in range(args.start_season, args.end_season + 1):
        all_rows.extend(fetch_season(session, year, args.min_interval, args.max_pages))
    unique = {row["game_id"]: row for row in all_rows}
    rows = sorted(unique.values(), key=lambda r: (r["commence_time_utc"], r["game_id"]))
    if not rows:
        raise RuntimeError("No valid final games returned; refusing to create an empty placeholder CSV")
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"nba_games_{args.start_season}_{args.end_season}.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    print(f"SUCCESS: saved {path}; rows={len(rows)}; unique_games={len(unique)}; sha256={digest}")
    print("NOTE: BALLDONTLIE Games endpoint does not supply ORtg/DRtg/Pace. Those columns are not fabricated.")


if __name__ == "__main__":
    main()
