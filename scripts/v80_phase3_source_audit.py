#!/usr/bin/env python3
"""Read-only Phase 3 audit of pinned public NBA odds archives.

This script does not write to Neon. It downloads source files, validates their
schemas and season coverage, and dry-runs the SBR-to-NBA-game join against the
isolated V8.0 database.
"""
from __future__ import annotations

import gzip
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import certifi
import duckdb
import psycopg
import requests

OUT = Path("artifacts/v80_phase3")
OUT.mkdir(parents=True, exist_ok=True)
SOURCE_CACHE = Path(".cache_v80_phase3")
SOURCE_CACHE.mkdir(parents=True, exist_ok=True)
SBR_URL = (
    "https://raw.githubusercontent.com/flancast90/sportsbookreview-scraper/"
    "1a820e50c6fbd0276cde073c22bfffae78930868/data/nba_archive_10Y.json"
)
ODDS_API_URL = (
    "https://raw.githubusercontent.com/sportsdataverse/hoopR-nba-data/"
    "7be25dae2ebe5f6027f5343a4ab3195caa61aee5/"
    "nba/betting_lines/closing_lines_odds_api.parquet"
)
SBR_TEAMS = {
    "Hawks":"1610612737","Celtics":"1610612738","Pelicans":"1610612740",
    "Bulls":"1610612741","Cavaliers":"1610612739","Mavericks":"1610612742",
    "Nuggets":"1610612743","Pistons":"1610612765","Warriors":"1610612744",
    "Golden State":"1610612744","Rockets":"1610612745","Pacers":"1610612754",
    "Clippers":"1610612746","LA Clippers":"1610612746","Lakers":"1610612747",
    "Grizzlies":"1610612763","Heat":"1610612748","Bucks":"1610612749",
    "Timberwolves":"1610612750","Nets":"1610612751","NewJersey":"1610612751",
    "Knicks":"1610612752","Thunder":"1610612760","Oklahoma City":"1610612760",
    "Magic":"1610612753","Seventysixers":"1610612755","Suns":"1610612756",
    "Trailblazers":"1610612757","Kings":"1610612758","Spurs":"1610612759",
    "Raptors":"1610612761","Jazz":"1610612762","Wizards":"1610612764",
    "Hornets":"1610612766",
}

def download(url: str, path: Path) -> None:
    if path.exists() and path.stat().st_size:
        return
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    if not response.content:
        raise RuntimeError(f"Empty source response: {url}")
    path.write_bytes(response.content)
    print(f"DOWNLOADED {path.name}: {len(response.content)} bytes")

def load_games() -> list[dict]:
    url = os.environ.get("V80_HISTORICAL_IMPORT_DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("Missing V80_HISTORICAL_IMPORT_DATABASE_URL")
    # Force a read-only transaction. This phase must never mutate Neon.
    with psycopg.connect(
        url, sslmode="verify-full", sslrootcert=certifi.where(),
        connect_timeout=20, options="-c default_transaction_read_only=on",
        application_name="NBA_AI_V80_PHASE3_SOURCE_AUDIT",
    ) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT game_id::text, season, home_team_id::text, away_team_id::text,
                       (commence_time_utc AT TIME ZONE 'America/New_York')::date AS game_date,
                       home_score, away_score
                FROM public.nba_game_results
                WHERE season IN ('2020-21','2021-22','2022-23','2023-24',
                                 '2024-25','2025-26')
                ORDER BY commence_time_utc
            """)
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

def sbr_day(row: dict) -> date:
    raw = str(int(row["date"]))
    return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))

def audit_sbr(games: list[dict]) -> dict:
    path = SOURCE_CACHE / "nba_archive_10Y.json"
    download(SBR_URL, path)
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise RuntimeError("Unexpected SBR archive format: expected a JSON list")
    season_counts = Counter(str(r.get("season")) for r in rows)
    target = [r for r in rows if r.get("season") in (2020, 2021)
              and r.get("home_team") != 0 and r.get("away_team") != 0]
    db = defaultdict(list)
    for g in games:
        db[(g["season"], g["home_team_id"], g["away_team_id"])].append(g)
    candidates = []
    unknown_teams = Counter()
    line_quality = Counter()
    source_keys = sorted({k for row in target for k in row.keys()})
    for row in target:
        try:
            s, t = row.get("home_close_spread"), row.get("close_over_under")
            if s is not None and abs(float(s)) <= 40:
                line_quality["valid_close_spread_raw"] += 1
            elif t is not None and abs(float(t)) <= 40:
                line_quality["spread_in_swapped_column_candidate"] += 1
            if t is not None and 150 <= abs(float(t)) <= 300:
                line_quality["valid_close_total_raw"] += 1
            elif s is not None and 150 <= abs(float(s)) <= 300:
                line_quality["total_in_swapped_column_candidate"] += 1
            if row.get("home_close_ml") not in (None, 0) and row.get("away_close_ml") not in (None, 0):
                line_quality["both_close_moneylines_present"] += 1
        except (TypeError, ValueError):
            line_quality["unparseable_market_values"] += 1
    invalid_dates = 0
    for i, r in enumerate(target):
        home = SBR_TEAMS.get(r.get("home_team"))
        away = SBR_TEAMS.get(r.get("away_team"))
        if not home or not away:
            unknown_teams[(r.get("home_team"), r.get("away_team"))] += 1
            continue
        start_year = int(r["season"])
        season = f"{start_year}-{str(start_year + 1)[-2:]}"
        try:
            day = sbr_day(r)
        except Exception:
            invalid_dates += 1
            continue
        matches = []
        for g in games:
            if g["season"] != season:
                continue
            if g["home_team_id"] != home or g["away_team_id"] != away:
                continue
            delta = abs((g["game_date"] - day).days)
            if delta <= 1:
                matches.append((delta, g))
        if matches:
            matches.sort(key=lambda x: x[0])
            candidates.append({
                "source_index": i, "season": season, "date": day.isoformat(),
                "home": r.get("home_team"), "away": r.get("away_team"),
                "candidate_game_ids": [x[1]["game_id"] for x in matches],
                "best_day_delta": matches[0][0],
                "source_score_fields": {
                    "home_final": r.get("home_final"),
                    "away_final": r.get("away_final"),
                },
            })
    # Greedy one-to-one assignment, nearest date first. Ambiguous collisions
    # remain visible in the report rather than silently double-matching.
    used = set()
    assigned = []
    collisions = 0
    for c in sorted(candidates, key=lambda x:(x["best_day_delta"], len(x["candidate_game_ids"]))):
        available = [gid for gid in c["candidate_game_ids"] if gid not in used]
        if not available:
            collisions += 1
            continue
        gid = available[0]
        used.add(gid)
        assigned.append((c, gid))
    matched_by_season = Counter(c["season"] for c, _ in assigned)
    game_by_id = {g["game_id"]: g for g in games}
    score_checks = Counter()
    score_mismatches = []
    for candidate, game_id in assigned:
        game = game_by_id[game_id]
        try:
            src_home = int(float(candidate["source_score_fields"]["home_final"]))
            src_away = int(float(candidate["source_score_fields"]["away_final"]))
            db_home = int(game["home_score"])
            db_away = int(game["away_score"])
            score_checks["checked"] += 1
            if (src_home, src_away) == (db_home, db_away):
                score_checks["exact_match"] += 1
            else:
                score_checks["mismatch"] += 1
                if len(score_mismatches) < 20:
                    score_mismatches.append({
                        "game_id": game_id,
                        "source_date": candidate["date"],
                        "teams": [candidate["home"], candidate["away"]],
                        "source_score": [src_home, src_away],
                        "database_score": [db_home, db_away],
                    })
        except (KeyError, TypeError, ValueError):
            score_checks["missing_or_invalid"] += 1
    unmatched_by_season = Counter()
    for r in target:
        start_year = int(r["season"])
        unmatched_by_season[f"{start_year}-{str(start_year+1)[-2:]}"] += 1
    for c, _ in assigned:
        unmatched_by_season[c["season"]] -= 1
    result = {
        "source": "flancast90/sportsbookreview-scraper",
        "revision": "1a820e50c6fbd0276cde073c22bfffae78930868",
        "license": "Repository software is MIT; rights to redistribute the bundled historical data have not been independently verified",
        "bytes": path.stat().st_size,
        "json_rows": len(rows),
        "source_season_counts_start_year": dict(sorted(season_counts.items())),
        "target_rows_2020_21_and_2021_22": len(target),
        "source_field_names": source_keys,
        "raw_market_field_quality_counts": dict(line_quality),
        "market_price_availability": {
            "moneyline_close_prices": "available as home_close_ml and away_close_ml",
            "spread_close_prices": "not present in the NBA archive schema; only home_close_spread and away_close_spread lines are present",
            "total_close_prices": "not present in the NBA archive schema; only close_over_under total line is present",
            "roi_eligibility": "moneyline may be evaluated after price validation; spread and total ROI are not eligible without both-side prices and a verified price source",
        },
        "matched_unique_games": len(assigned),
        "matched_by_season": dict(matched_by_season),
        "score_validation": {
            "counts": dict(score_checks),
            "mismatch_examples": score_mismatches,
            "rule": "SBR home_final/away_final must exactly equal the isolated NBA game result for the assigned home/away teams",
        },
        "unmatched_by_season": dict(unmatched_by_season),
        "candidate_rows_with_multiple_matches": sum(len(c["candidate_game_ids"])>1 for c in candidates),
        "assignment_collisions": collisions,
        "unknown_team_rows": sum(unknown_teams.values()),
        "unknown_team_examples": [{"teams":list(k),"rows":v} for k,v in unknown_teams.most_common(10)],
        "invalid_date_rows": invalid_dates,
        "sample_matches": [{"source_date":c["date"],"home":c["home"],"away":c["away"],"game_id":gid,"day_delta":c["best_day_delta"]} for c,gid in assigned[:12]],
    }
    return result

def audit_consensus() -> dict:
    path = SOURCE_CACHE / "closing_lines_odds_api.parquet"
    download(ODDS_API_URL, path)
    con = duckdb.connect()
    schema = con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]).fetchall()
    names = [r[0] for r in schema]
    required = {"game_id", "home_point", "over_under", "spread_source"}
    missing = sorted(required - set(names))
    if missing:
        raise RuntimeError(f"Consensus parquet missing expected fields: {missing}; found {names}")
    rows = con.execute("""
        SELECT spread_source, COUNT(*) AS rows,
               COUNT(home_point) AS spread_rows,
               COUNT(over_under) AS total_rows,
               MIN(game_id::VARCHAR), MAX(game_id::VARCHAR)
        FROM read_parquet(?) GROUP BY spread_source ORDER BY spread_source
    """, [str(path)]).fetchall()
    return {
        "source":"sportsdataverse/hoopR-nba-data",
        "revision":"7be25dae2ebe5f6027f5343a4ab3195caa61aee5",
        "license":"NOASSERTION in repository metadata; legal approval required before redistribution",
        "bytes":path.stat().st_size,
        "schema":[{"name":r[0],"type":r[1]} for r in schema],
        "rows_by_spread_source":[list(r) for r in rows],
        "note":"ESPN event IDs; an ESPN scoreboard-to-NBA game ID bridge is required. This archive is not a direct NBA game_id join.",
    }

def main() -> None:
    games = load_games()
    report = {
        "mode":"READ_ONLY_DRY_RUN",
        "database":"nba_v80 (connection role/endpoint supplied by isolated import secret)",
        "games_loaded":len(games),
        "games_by_season":dict(Counter(g["season"] for g in games)),
        "sbr":audit_sbr(games),
        "odds_api_consensus":audit_consensus(),
        "database_writes":0,
        "next_gate":"Inspect this report and source licensing, then build a separately approved importer. No INSERT/UPDATE/DELETE is performed.",
    }
    out = OUT / "source_audit.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    print(f"RESULT: READ-ONLY DRY RUN COMPLETE; report={out}")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"PHASE 3 AUDIT FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
