"""Safely import the fixed V8.0 historical NBA CSV into the isolated Neon test DB."""
from __future__ import annotations

import csv
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import certifi
import psycopg
from psycopg.conninfo import conninfo_to_dict

CSV_PATH = Path("data/nba_v80_historical_games_cutoff_2026-04-01.csv")
DB_NAME = "nba_v80"
DB_ROLE = "v80_historical_import"
SECRET_NAME = "V80_HISTORICAL_IMPORT_DATABASE_URL"
CUTOFF = datetime(2026, 4, 2, tzinfo=timezone.utc)
EXPECTED_TOTAL = 2459
EXPECTED_SEASONS = {"2024-25": 1321, "2025-26": 1138}
COLUMNS = [
    "game_id", "season", "season_type", "home_team_id", "away_team_id",
    "home_team", "away_team", "commence_time_utc", "home_score",
    "away_score", "total_score", "score_margin", "home_win",
    "overtime_periods", "game_status", "source", "verified_at_utc",
]
INSERT_SQL = """
INSERT INTO public.nba_game_results (
    game_id, season, season_type, home_team_id, away_team_id,
    home_team, away_team, commence_time_utc, home_score, away_score,
    overtime_periods, game_status, source, verified_at_utc
) VALUES (
    %(game_id)s, %(season)s, %(season_type)s, %(home_team_id)s, %(away_team_id)s,
    %(home_team)s, %(away_team)s, %(commence_time_utc)s, %(home_score)s, %(away_score)s,
    %(overtime_periods)s, %(game_status)s, %(source)s, %(verified_at_utc)s
)
ON CONFLICT (game_id) DO NOTHING
"""


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp missing timezone")
    return parsed.astimezone(timezone.utc)


def load_and_validate_csv() -> list[dict]:
    if not CSV_PATH.is_file():
        raise RuntimeError(f"Required CSV not found: {CSV_PATH}")
    rows: list[dict] = []
    with CSV_PATH.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != COLUMNS:
            raise RuntimeError("CSV header does not exactly match the approved 17-column schema")
        for line_no, raw in enumerate(reader, start=2):
            try:
                commence = parse_dt(raw["commence_time_utc"])
                verified = parse_dt(raw["verified_at_utc"])
                row = {
                    "game_id": int(raw["game_id"]),
                    "season": raw["season"].strip(),
                    "season_type": raw["season_type"].strip(),
                    "home_team_id": int(raw["home_team_id"]),
                    "away_team_id": int(raw["away_team_id"]),
                    "home_team": raw["home_team"].strip(),
                    "away_team": raw["away_team"].strip(),
                    "commence_time_utc": commence,
                    "home_score": int(raw["home_score"]),
                    "away_score": int(raw["away_score"]),
                    "total_score": int(raw["total_score"]),
                    "score_margin": int(raw["score_margin"]),
                    "home_win": raw["home_win"].strip().lower() == "true",
                    "overtime_periods": int(raw["overtime_periods"]) if raw["overtime_periods"].strip() else None,
                    "game_status": raw["game_status"].strip(),
                    "source": raw["source"].strip(),
                    "verified_at_utc": verified,
                }
            except Exception as exc:
                raise RuntimeError(f"Invalid CSV row at line {line_no}: {type(exc).__name__}") from None
            if commence >= CUTOFF:
                raise RuntimeError(f"CSV contains a game at/after the UTC cutoff on line {line_no}")
            if verified <= commence:
                raise RuntimeError(f"Verification timestamp is not after game time on line {line_no}")
            if row["game_status"] != "Final" or row["season_type"] not in {"Regular Season", "Playoffs"}:
                raise RuntimeError(f"Unexpected status or season type on line {line_no}")
            if row["home_score"] == row["away_score"] or min(row["home_score"], row["away_score"]) < 0:
                raise RuntimeError(f"Invalid final score on line {line_no}")
            if row["total_score"] != row["home_score"] + row["away_score"]:
                raise RuntimeError(f"Incorrect total_score on line {line_no}")
            if row["score_margin"] != row["home_score"] - row["away_score"]:
                raise RuntimeError(f"Incorrect score_margin on line {line_no}")
            if row["home_win"] != (row["home_score"] > row["away_score"]):
                raise RuntimeError(f"Incorrect home_win on line {line_no}")
            if not row["source"] or row["game_id"] <= 0 or row["home_team_id"] == row["away_team_id"]:
                raise RuntimeError(f"Invalid identifiers/source on line {line_no}")
            rows.append(row)

    ids = [r["game_id"] for r in rows]
    if len(rows) != EXPECTED_TOTAL or len(set(ids)) != EXPECTED_TOTAL:
        raise RuntimeError(f"Expected {EXPECTED_TOTAL} rows and unique game IDs; found {len(rows)} rows / {len(set(ids))} IDs")
    seasons = Counter(r["season"] for r in rows)
    if dict(seasons) != EXPECTED_SEASONS:
        raise RuntimeError(f"Unexpected season counts: {dict(seasons)}")
    season_types = Counter(r["season_type"] for r in rows)
    if season_types != Counter({"Regular Season": 2375, "Playoffs": 84}):
        raise RuntimeError(f"Unexpected season-type counts: {dict(season_types)}")
    if max(r["commence_time_utc"] for r in rows) >= CUTOFF:
        raise RuntimeError("Dataset date range failed cutoff validation")
    return rows


def connect_import_role():
    url = os.environ.get(SECRET_NAME, "").strip()
    if not url:
        raise RuntimeError(f"Missing required GitHub environment secret: {SECRET_NAME}")
    cfg = conninfo_to_dict(url)
    if cfg.get("dbname") != DB_NAME or cfg.get("user") != DB_ROLE:
        raise RuntimeError("Database URL must use the isolated nba_v80 database and v80_historical_import role")
    host = cfg.get("host", "")
    if not host.endswith("neon.tech"):
        raise RuntimeError("Database URL host is not an approved Neon endpoint")
    return psycopg.connect(
        host=host,
        port=int(cfg.get("port", "5432")),
        dbname=DB_NAME,
        user=DB_ROLE,
        password=cfg.get("password"),
        sslmode="verify-full",
        sslrootcert=certifi.where(),
        channel_binding="require",
        connect_timeout=15,
        application_name="NBA_AI_V80_HISTORICAL_IMPORT",
    )


def main():
    if os.environ.get("CONFIRM_HISTORICAL_IMPORT") != "YES":
        raise RuntimeError("Import not confirmed; use the protected manual workflow confirmation.")
    import_mode = os.environ.get("IMPORT_MODE", "dry-run").strip().lower()
    if import_mode not in {"dry-run", "commit"}:
        raise RuntimeError("IMPORT_MODE must be either dry-run or commit.")
    rows = load_and_validate_csv()
    print(f"PASS: validated {len(rows)} unique games; seasons={EXPECTED_SEASONS}; UTC cutoff exclusive=2026-04-02T00:00:00Z", flush=True)

    conn = connect_import_role()
    try:
        if not conn.pgconn.ssl_in_use:
            raise RuntimeError("Verified TLS connection is not active")
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ WRITE")
            cur.execute("SET LOCAL TIME ZONE 'UTC'")
            cur.execute("SET LOCAL row_security = on")
            cur.execute("SET LOCAL statement_timeout = '120s'")
            cur.execute("SET LOCAL lock_timeout = '10s'")
            cur.execute("""
                SELECT current_database(), current_user, session_user,
                       current_setting('transaction_read_only'),
                       (SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user),
                       has_table_privilege(current_user, 'public.nba_game_results', 'INSERT'),
                       has_table_privilege(current_user, 'public.nba_game_results', 'UPDATE'),
                       has_table_privilege(current_user, 'public.nba_game_results', 'DELETE'),
                       has_table_privilege(current_user, 'public.nba_game_results', 'TRUNCATE'),
                       (SELECT relrowsecurity FROM pg_class WHERE oid='public.nba_game_results'::regclass),
                       (SELECT relowner::regrole::text FROM pg_class WHERE oid='public.nba_game_results'::regclass)
            """)
            status = cur.fetchone()
            expected = (DB_NAME, DB_ROLE, DB_ROLE, "off", False, True, False, False, False, True, "neondb_owner")
            if tuple(status) != expected:
                raise RuntimeError("Database role, RLS, or least-privilege checks failed; import aborted")
            cur.execute("""
                SELECT count(*)
                FROM pg_policies
                WHERE schemaname='public' AND tablename='nba_game_results'
                  AND cmd='INSERT' AND policyname='historical_import_cutoff'
                  AND 'v80_historical_import' = ANY(roles)
                  AND with_check LIKE '%2026-04-02%'
            """)
            if cur.fetchone()[0] != 1:
                raise RuntimeError("Expected role-specific cutoff RLS policy is missing; import aborted")
            print("PASS: isolated role, TLS, RLS and least-privilege checks", flush=True)
            cur.executemany(INSERT_SQL, rows)
            cur.execute("""
                SELECT count(*), count(DISTINCT game_id),
                       count(*) FILTER (WHERE commence_time_utc >= %s::timestamptz),
                       count(*) FILTER (WHERE season='2024-25'),
                       count(*) FILTER (WHERE season='2025-26')
                FROM public.nba_game_results
            """, (CUTOFF,))
            totals = cur.fetchone()
            if tuple(totals) != (EXPECTED_TOTAL, EXPECTED_TOTAL, 0, 1321, 1138):
                raise RuntimeError(f"Post-import verification failed: {tuple(totals)}")
        print("PASS: database verification", flush=True)
        if import_mode == "dry-run":
            conn.rollback()
            print("RESULT: DRY RUN PASSED; all 2459 rows validated inside transaction and rolled back; database unchanged", flush=True)
        else:
            conn.commit()
            print("RESULT: 2459/2459 historical games committed", flush=True)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"IMPORT FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
