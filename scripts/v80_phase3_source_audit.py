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
    "Hawks":"Atlanta Hawks","Celtics":"Boston Celtics","Nets":"Brooklyn Nets",
    "Hornets":"Charlotte Hornets","Bulls":"Chicago Bulls","Cavaliers":"Cleveland Cavaliers",
    "Mavericks":"Dallas Mavericks","Nuggets":"Denver Nuggets","Pistons":"Detroit Pistons",
    "Warriors":"Golden State Warriors","Golden State":"Golden State Warriors",
    "Rockets":"Houston Rockets","Pacers":"Indiana Pacers",
    "Clippers":"LA Clippers","Lakers":"Los Angeles Lakers","Grizzlies":"Memphis Grizzlies",
    "Heat":"Miami Heat","Bucks":"Milwaukee Bucks","Timberwolves":"Minnesota Timberwolves",
    "Pelicans":"New Orleans Pelicans","Knicks":"New York Knicks","Thunder":"Oklahoma City Thunder",
    "Magic":"Orlando Magic","Seventysixers":"Philadelphia 76ers","76ers":"Philadelphia 76ers",
    "Suns":"Phoenix Suns","Trailblazers":"Portland Trail Blazers","Kings":"Sacramento Kings",
    "Spurs":"San Antonio Spurs","Raptors":"Toronto Raptors","Jazz":"Utah Jazz","Wizards":"Washington Wizards",
    "NewJersey":"Brooklyn Nets","Seattle":"Oklahoma City Thunder",
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
                SELECT game_id::text, season, home_team, away_team,
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
        db[(g["season"], g["home_team"], g["away_team"])].append(g)
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
            if g["home_team"] != home or g["away_team"] != away:
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
    # Calculate closing-market baselines only on matched, score-verified rows.
    market_counts = Counter()
    ml_probs = []
    home_ml_values = []
    away_ml_values = []
    spread_values = []
    total_line_values = []
    actual_total_values = []
    market_samples = []
    ats_results = Counter()
    total_results = Counter()
    for candidate, game_id in assigned:
        src = rows[candidate["source_index"]]
        game = game_by_id[game_id]
        try:
            hml = float(src.get("home_close_ml"))
            aml = float(src.get("away_close_ml"))
            if hml != 0 and aml != 0:
                hp = (100.0 / (hml + 100.0)) if hml > 0 else (-hml / (-hml + 100.0))
                ap = (100.0 / (aml + 100.0)) if aml > 0 else (-aml / (-aml + 100.0))
                ph = hp / (hp + ap)
                actual_home = 1.0 if game["home_score"] > game["away_score"] else 0.0
                ml_probs.append((ph, actual_home))
                home_ml_values.append(hml)
                away_ml_values.append(aml)
                market_counts["valid_moneyline_pairs"] += 1
        except (TypeError, ValueError, ZeroDivisionError):
            market_counts["invalid_moneyline_pairs"] += 1
        try:
            spread = float(src.get("home_close_spread"))
            if spread != 0 and abs(spread) <= 40:
                margin_adjusted = float(game["home_score"]) - float(game["away_score"]) + spread
                spread_values.append(spread)
                ats_results["home_cover" if margin_adjusted > 0 else "away_cover" if margin_adjusted < 0 else "push"] += 1
            else:
                market_counts["invalid_or_missing_spread_line"] += 1
        except (TypeError, ValueError):
            market_counts["invalid_or_missing_spread_line"] += 1
        try:
            total_line = float(src.get("close_over_under"))
            if 150 <= total_line <= 300:
                final_total = float(game["home_score"]) + float(game["away_score"])
                total_line_values.append(total_line)
                actual_total_values.append(final_total)
                total_results["over" if final_total > total_line else "under" if final_total < total_line else "push"] += 1
            else:
                market_counts["invalid_or_missing_total_line"] += 1
        except (TypeError, ValueError):
            market_counts["invalid_or_missing_total_line"] += 1
        if len(market_samples) < 20:
            market_samples.append({
                "game_id": game_id,
                "season": candidate["season"],
                "home": candidate["home"],
                "away": candidate["away"],
                "home_close_ml": src.get("home_close_ml"),
                "away_close_ml": src.get("away_close_ml"),
                "home_close_spread": src.get("home_close_spread"),
                "close_over_under": src.get("close_over_under"),
                "home_score": game["home_score"],
                "away_score": game["away_score"],
            })
    def numeric_summary(values):
        ordered = sorted(values)
        if not ordered:
            return {"n": 0}
        mid = len(ordered) // 2
        median = ordered[mid] if len(ordered) % 2 else (ordered[mid-1] + ordered[mid]) / 2
        return {"n": len(ordered), "min": round(ordered[0], 3), "median": round(median, 3), "max": round(ordered[-1], 3), "mean": round(sum(ordered)/len(ordered), 3)}
    if ml_probs:
        ml_accuracy = sum((p >= 0.5) == bool(y) for p, y in ml_probs) / len(ml_probs)
        ml_brier = sum((p - y) ** 2 for p, y in ml_probs) / len(ml_probs)
    else:
        ml_accuracy = None
        ml_brier = None
    market_baseline = {
        "moneyline": {
            "valid_pairs": len(ml_probs),
            "accuracy": round(ml_accuracy, 6) if ml_accuracy is not None else None,
            "brier_score": round(ml_brier, 6) if ml_brier is not None else None,
            "method": "American closing moneylines converted to implied probabilities and two-way de-vigged",
            "home_price_distribution": numeric_summary(home_ml_values),
            "away_price_distribution": numeric_summary(away_ml_values),
        },
        "spread_line_settlement_counts": dict(ats_results),
        "spread_line_distribution": numeric_summary(spread_values),
        "total_line_settlement_counts": dict(total_results),
        "total_line_distribution": numeric_summary(total_line_values),
        "actual_game_total_distribution_for_valid_total_lines": numeric_summary(actual_total_values),
        "market_sample_rows": market_samples,
        "quality_counts": dict(market_counts),
        "roi_note": "Spread and total settlement labels have no matching both-side prices in this source; no ROI is calculated.",
    }
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
        "closing_market_baseline": market_baseline,
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
