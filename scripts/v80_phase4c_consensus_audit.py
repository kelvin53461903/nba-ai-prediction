#!/usr/bin/env python3
"""Phase 4C: read-only audit of SportsDataverse NBA consensus closing lines.

The pinned Parquet contains ESPN event IDs, a consensus home spread, a total,
bookmaker count and timestamps. It does NOT contain the two-way spread/total
prices needed for realized ROI. This script audits coverage and line quality
only; it never writes to Neon.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import duckdb
import requests

URL = (
    "https://raw.githubusercontent.com/sportsdataverse/hoopR-nba-data/"
    "7be25dae2ebe5f6027f5343a4ab3195caa61aee5/"
    "nba/betting_lines/closing_lines_odds_api.parquet"
)
CACHE = Path(".cache_v80_phase4c")
OUT = Path("artifacts/v80_phase4c")
CACHE.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)
REQUIRED = {"game_id", "home_point", "over_under", "spread_source"}

def validate_schema(columns: set[str]) -> list[str]:
    return sorted(REQUIRED - columns)

def plausible_spread(value) -> bool:
    return value is not None and abs(float(value)) <= 40

def plausible_total(value) -> bool:
    return value is not None and 150 <= float(value) <= 300

def download(path: Path) -> None:
    if path.exists() and path.stat().st_size > 0:
        return
    response = requests.get(URL, timeout=180)
    response.raise_for_status()
    if not response.content:
        raise RuntimeError("Empty SportsDataverse Parquet response")
    path.write_bytes(response.content)
    print(f"DOWNLOADED consensus parquet: {len(response.content)} bytes")

def main() -> None:
    path = CACHE / "closing_lines_odds_api.parquet"
    download(path)
    con = duckdb.connect()
    schema_rows = con.execute(
        "DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]
    ).fetchall()
    columns = {r[0] for r in schema_rows}
    missing = validate_schema(columns)
    if missing:
        raise RuntimeError(f"Unexpected Parquet schema; missing={missing}; found={sorted(columns)}")

    total_rows = con.execute(
        "SELECT COUNT(*) FROM read_parquet(?)", [str(path)]
    ).fetchone()[0]
    duplicate_ids = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT game_id FROM read_parquet(?) GROUP BY game_id HAVING COUNT(*) > 1
        )
    """, [str(path)]).fetchone()[0]
    null_ids = con.execute(
        "SELECT COUNT(*) FROM read_parquet(?) WHERE game_id IS NULL", [str(path)]
    ).fetchone()[0]
    year_rows = con.execute("""
        SELECT
            strftime(TRY_CAST(commence_time AS TIMESTAMP), '%Y') AS year,
            COUNT(*) AS games,
            COUNT(home_point) AS spread_rows,
            COUNT(over_under) AS total_rows,
            MIN(home_point) AS min_home_spread,
            MAX(home_point) AS max_home_spread,
            AVG(home_point) AS mean_home_spread,
            MIN(over_under) AS min_total,
            MAX(over_under) AS max_total,
            AVG(over_under) AS mean_total,
            MIN(n_books) AS min_books,
            MEDIAN(n_books) AS median_books,
            MAX(n_books) AS max_books
        FROM read_parquet(?)
        GROUP BY 1 ORDER BY 1
    """, [str(path)]).fetchall()
    year_data = []
    for row in year_rows:
        year_data.append({
            "year": row[0], "games": row[1], "spread_rows": row[2],
            "total_rows": row[3], "min_home_spread": row[4],
            "max_home_spread": row[5], "mean_home_spread": row[6],
            "min_total": row[7], "max_total": row[8], "mean_total": row[9],
            "min_books": row[10], "median_books": row[11], "max_books": row[12],
        })
    bad_lines = con.execute("""
        SELECT
          COUNT(*) FILTER (WHERE home_point IS NOT NULL AND ABS(home_point) > 40) AS bad_spread,
          COUNT(*) FILTER (WHERE over_under IS NOT NULL AND (over_under < 150 OR over_under > 300)) AS bad_total,
          COUNT(*) FILTER (WHERE n_books IS NULL OR n_books < 1) AS bad_book_count,
          COUNT(*) FILTER (WHERE commence_time IS NULL) AS missing_time
        FROM read_parquet(?)
    """, [str(path)]).fetchone()
    source_values = con.execute("""
        SELECT spread_source, COUNT(*) FROM read_parquet(?)
        GROUP BY spread_source ORDER BY spread_source
    """, [str(path)]).fetchall()
    # The published artifact uses ESPN event IDs, not NBA game IDs. Without a
    # checked ESPN scoreboard crosswalk, do not claim score-level validation.
    report = {
        "phase": "V8.0_PHASE4C",
        "mode": "READ_ONLY_SOURCE_AUDIT",
        "source": "sportsdataverse/hoopR-nba-data",
        "revision": "7be25dae2ebe5f6027f5343a4ab3195caa61aee5",
        "source_method": "The Odds API historical closing snapshots; median across bookmakers",
        "license": "NOASSERTION in repository metadata; redistribution/import approval not established",
        "file_bytes": path.stat().st_size,
        "rows": total_rows,
        "schema": [{"name": r[0], "type": r[1]} for r in schema_rows],
        "missing_required_columns": missing,
        "duplicate_game_ids": duplicate_ids,
        "null_game_ids": null_ids,
        "by_year": year_data,
        "invalid_values": {
            "spread_outside_40_points": bad_lines[0],
            "total_outside_150_300": bad_lines[1],
            "missing_or_invalid_book_count": bad_lines[2],
            "missing_commence_time": bad_lines[3],
        },
        "spread_source_counts": [list(x) for x in source_values],
        "join_status": "NOT_RUN",
        "join_reason": "Parquet keys are ESPN event IDs; an independently verified ESPN-event-to-NBA-game crosswalk is required before matching final scores.",
        "market_scope": {
            "closing_home_spread_line": True,
            "closing_total_line": True,
            "two_way_spread_prices": False,
            "two_way_total_prices": False,
            "moneyline_prices": False,
            "spread_total_roi_calculable": False,
            "clv_opening_lines_available": False,
        },
        "database_writes": 0,
        "acceptance": "CANDIDATE_LINES_ONLY_REQUIRES_CROSSWALK_AND_LICENSE_REVIEW",
        "next_gate": "Build and independently validate the ESPN event ID crosswalk, verify score matches, and locate a permitted source of both-side prices before any ROI analysis.",
    }
    out = OUT / "consensus_closing_lines_audit.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    print(f"RESULT: PHASE 4C CONSENSUS SOURCE AUDIT COMPLETE; report={out}")

if __name__ == "__main__":
    main()
