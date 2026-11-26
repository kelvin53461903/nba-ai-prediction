#!/usr/bin/env python3
"""Phase 4D: ESPN event-ID to isolated NBA results crosswalk, read-only."""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import certifi
import duckdb
import psycopg
import requests

PARQUET_URL = (
    "https://raw.githubusercontent.com/sportsdataverse/hoopR-nba-data/"
    "7be25dae2ebe5f6027f5343a4ab3195caa61aee5/"
    "nba/betting_lines/closing_lines_odds_api.parquet"
)
CACHE = Path(".cache_v80_phase4d")
OUT = Path("artifacts/v80_phase4d")
ET = ZoneInfo("America/New_York")
API = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
ALIASES = {
    "LA Clippers": "Los Angeles Clippers",
    "Los Angeles Clippers": "Los Angeles Clippers",
    "LA Lakers": "Los Angeles Lakers",
    "Los Angeles Lakers": "Los Angeles Lakers",
    "New York Knicks": "New York Knicks",
    "Golden State Warriors": "Golden State Warriors",
    "Brooklyn Nets": "Brooklyn Nets",
    "New Orleans Pelicans": "New Orleans Pelicans",
    "Oklahoma City Thunder": "Oklahoma City Thunder",
    "Portland Trail Blazers": "Portland Trail Blazers",
    "Philadelphia 76ers": "Philadelphia 76ers",
}

def canonical_team(value) -> str:
    value = " ".join(str(value or "").strip().split())
    return ALIASES.get(value, value)

def et_date(value) -> str:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt.astimezone(ET).date().isoformat()

def scoreboard_event_rows(payload: dict) -> list[dict]:
    out = []
    for event in payload.get("events", []) or []:
        competitions = event.get("competitions") or []
        if not competitions:
            continue
        comp = competitions[0]
        teams = {}
        for competitor in comp.get("competitors", []) or []:
            side = competitor.get("homeAway")
            team = competitor.get("team") or {}
            if side in ("home", "away"):
                teams[side] = {
                    "name": canonical_team(team.get("displayName") or team.get("name")),
                    "score": int(competitor["score"]) if str(competitor.get("score", "")).isdigit() else None,
                }
        out.append({
            "event_id": str(event.get("id") or ""),
            "date": et_date(event.get("date") or comp.get("date")),
            "home": teams.get("home", {}).get("name"),
            "away": teams.get("away", {}).get("name"),
            "home_score": teams.get("home", {}).get("score"),
            "away_score": teams.get("away", {}).get("score"),
            "status": ((comp.get("status") or {}).get("type") or {}).get("name"),
        })
    return out

def match_event(event: dict, db_games: list[dict]) -> dict:
    candidates = [
        g for g in db_games
        if str(g["game_date"]) == event["date"]
        and canonical_team(g["home_team"]) == event["home"]
        and canonical_team(g["away_team"]) == event["away"]
    ]
    if len(candidates) != 1:
        return {"status": "NO_MATCH" if not candidates else "AMBIGUOUS", "candidate_count": len(candidates)}
    game = candidates[0]
    if event["home_score"] is None or event["away_score"] is None:
        return {"status": "SCORE_MISSING", "game_id": str(game["game_id"])}
    exact = (int(game["home_score"]), int(game["away_score"])) == (event["home_score"], event["away_score"])
    return {
        "status": "EXACT_SCORE_MATCH" if exact else "SCORE_MISMATCH",
        "game_id": str(game["game_id"]),
        "database_score": [int(game["home_score"]), int(game["away_score"])],
        "espn_score": [event["home_score"], event["away_score"]],
    }

def load_db_games() -> list[dict]:
    url = os.environ.get("V80_HISTORICAL_IMPORT_DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("Missing V80_HISTORICAL_IMPORT_DATABASE_URL")
    with psycopg.connect(
        url, sslmode="verify-full", sslrootcert=certifi.where(),
        connect_timeout=20, options="-c default_transaction_read_only=on",
        application_name="NBA_AI_V80_PHASE4D_ESPN_CROSSWALK",
    ) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT game_id::text, season, home_team, away_team,
                       (commence_time_utc AT TIME ZONE 'America/New_York')::date AS game_date,
                       home_score, away_score
                FROM public.nba_game_results
                WHERE season IN ('2020-21','2021-22','2022-23','2023-24','2024-25','2025-26')
                ORDER BY commence_time_utc
            """)
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

def download_parquet(path: Path) -> None:
    if path.exists() and path.stat().st_size:
        return
    response = requests.get(PARQUET_URL, timeout=180)
    response.raise_for_status()
    if not response.content:
        raise RuntimeError("Empty consensus Parquet")
    path.write_bytes(response.content)

def fetch_scoreboard(day: str, session: requests.Session) -> list[dict]:
    stamp = day.replace("-", "")
    response = session.get(API, params={"dates": stamp, "limit": 500}, timeout=30)
    response.raise_for_status()
    return scoreboard_event_rows(response.json())

def main() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    parquet = CACHE / "closing_lines_odds_api.parquet"
    download_parquet(parquet)
    con = duckdb.connect()
    source_rows = con.execute(
        "SELECT CAST(game_id AS VARCHAR), commence_time FROM read_parquet(?)",
        [str(parquet)]
    ).fetchall()
    source_by_id = {str(event_id): commence for event_id, commence in source_rows}
    db_games = load_db_games()
    dates = sorted({str(g["game_date"]) for g in db_games})
    session = requests.Session()
    session.headers.update({"User-Agent": "NBA-AI-V8.0-historical-audit/1.0"})
    event_by_id = {}
    failed_dates = []
    for idx, day in enumerate(dates, 1):
        try:
            for event in fetch_scoreboard(day, session):
                event_by_id[event["event_id"]] = event
        except Exception as exc:
            failed_dates.append({"date": day, "error": f"{type(exc).__name__}: {exc}"})
        if idx % 20 == 0:
            print(f"ESPN scoreboard dates processed: {idx}/{len(dates)}")
        time.sleep(0.10)

    counts = Counter()
    rows = []
    for game in db_games:
        game_id = str(game["game_id"])
        # Crosswalk requires an ESPN event id. Match ESPN schedule event by ET
        # date + exact home/away team order; then independently compare scores.
        possible = [
            e for e in event_by_id.values()
            if e["date"] == str(game["game_date"])
            and e["home"] == canonical_team(game["home_team"])
            and e["away"] == canonical_team(game["away_team"])
        ]
        if len(possible) != 1:
            status = "NO_ESPN_EVENT" if not possible else "AMBIGUOUS_ESPN_EVENT"
            counts[status] += 1
            rows.append({"nba_game_id": game_id, "season": game["season"], "date": str(game["game_date"]), "home": game["home_team"], "away": game["away_team"], "status": status, "candidate_count": len(possible)})
            continue
        event = possible[0]
        source_commence = source_by_id.get(event["event_id"])
        source_id_present = source_commence is not None
        source_date_match = False
        if source_id_present:
            source_date_match = et_date(source_commence) == event["date"]
        result = match_event(event, [game])
        status = result["status"]
        if status == "EXACT_SCORE_MATCH" and not source_id_present:
            status = "ESPN_SCORE_VERIFIED_SOURCE_ID_MISSING"
        elif status == "EXACT_SCORE_MATCH" and not source_date_match:
            status = "ESPN_SCORE_VERIFIED_SOURCE_DATE_MISMATCH"
        elif status == "EXACT_SCORE_MATCH":
            status = "EXACT_SCORE_AND_SOURCE_ID_MATCH"
        counts[status] += 1
        rows.append({
            "nba_game_id": game_id, "espn_event_id": event["event_id"],
            "source_parquet_has_event_id": source_id_present,
            "source_event_date_matches": source_date_match if source_id_present else None,
            "season": game["season"], "date": str(game["game_date"]),
            "home": game["home_team"], "away": game["away_team"],
            "status": status, "database_score": result.get("database_score"),
            "espn_score": result.get("espn_score"),
        })

    report = {
        "phase": "V8.0_PHASE4D",
        "mode": "READ_ONLY",
        "source_revision": "7be25dae2ebe5f6027f5343a4ab3195caa61aee5",
        "database_games": len(db_games),
        "unique_database_dates": len(dates),
        "espn_events_loaded": len(event_by_id),
        "source_parquet_event_ids": len(source_by_id),
        "status_counts": dict(counts),
        "failed_scoreboard_dates": failed_dates,
        "results_by_season": {
            season: dict(Counter(r["status"] for r in rows if r["season"] == season))
            for season in sorted({r["season"] for r in rows})
        },
        "sample_non_exact": [r for r in rows if r["status"] != "EXACT_SCORE_AND_SOURCE_ID_MATCH"][:50],
        "matches": rows,
        "database_writes": 0,
        "acceptance": "REQUIRES_REVIEW" if failed_dates or any(k != "EXACT_SCORE_AND_SOURCE_ID_MATCH" for k in counts) else "ALL_DB_GAMES_EXACT_SCORE_AND_SOURCE_ID_MATCH",
        "limitations": [
            "A successful ESPN event/team/date/score crosswalk validates identity, not betting-price accuracy.",
            "The Parquet source licence remains NOASSERTION and needs legal review.",
            "The Parquet has consensus spread/total lines but not both-side prices; ROI remains unavailable.",
        ],
    }
    out = OUT / "espn_nba_game_crosswalk_audit.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k not in ("matches","sample_non_exact")}, indent=2))
    print(f"RESULT: PHASE 4D READ-ONLY CROSSWALK COMPLETE; report={out}")

if __name__ == "__main__":
    main()
