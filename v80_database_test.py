
"""
NBA AI V8.0 CALIBRATION PRO
Read-only Neon database integration tests.
"""

import sys

import psycopg

from v80_database import (
    connect_v80,
    check_connection,
    get_connection_config,
)


EXPECTED_TABLES = {
    "nba_predictions",
    "odds_totals_snapshots",
    "nba_pinnacle_odds",
    "nba_historical_odds",
    "nba_advanced_stats",
    "nba_game_results",
    "nba_calibration_metrics",
    "nba_model_versions",
    "nba_backtest_results",
    "nba_historical_bookmaker_lines",
}

passed = []


def check(name, condition):
    if not condition:
        raise RuntimeError(name)

    passed.append(name)
    print(f"PASS: {name}")


def run_tests():

    config = get_connection_config()

    check(
        "01 - Dedicated database",
        config["dbname"] == "nba_v80",
    )

    check(
        "02 - Dedicated application role",
        config["user"] == "v80_app",
    )

    check(
        "03 - Strict SSL configuration",
        config["sslmode"] == "verify-full",
    )

    check(
        "04 - Channel binding required",
        config["channel_binding"] == "require",
    )

    status = check_connection()

    check(
        "05 - Actual SSL connection",
        status["ssl"] is True,
    )

    check(
    "06 - TLS version reporting handled",
    status["tls"] if "tls" in status
    else status["ssl"] is True,
)

    check(
        "07 - UTC database timezone",
        status["timezone"] == "UTC",
    )

    check(
        "08 - Read-only transaction",
        status["read_only"] == "on",
    )

    with connect_v80() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    rolcanlogin,
                    rolsuper,
                    rolcreatedb,
                    rolcreaterole,
                    rolreplication,
                    rolbypassrls,
                    rolinherit
                FROM pg_roles
                WHERE rolname = current_user
            """)

            role = cur.fetchone()

            check(
                "09 - Application login enabled",
                role["rolcanlogin"],
            )

            check(
                "10 - No elevated role privileges",
                not any([
                    role["rolsuper"],
                    role["rolcreatedb"],
                    role["rolcreaterole"],
                    role["rolreplication"],
                    role["rolbypassrls"],
                    role["rolinherit"],
                ]),
            )

            cur.execute("""
                SELECT COUNT(*) AS total
                FROM pg_auth_members
                WHERE member = current_user::regrole
            """)

            check(
                "11 - No unexpected role membership",
                cur.fetchone()["total"] == 0,
            )

            cur.execute("""
                SELECT
                    has_database_privilege(
                        current_user,
                        'nba_v80',
                        'CONNECT'
                    ) AS can_connect,
                    has_database_privilege(
                        current_user,
                        'nba_v80',
                        'CREATE'
                    ) AS can_create,
                    has_database_privilege(
                        current_user,
                        'nba_v80',
                        'TEMP'
                    ) AS can_temp,
                    has_database_privilege(
                        current_user,
                        'neondb',
                        'CONNECT'
                    ) AS other_database
            """)

            rights = cur.fetchone()

            check(
                "12 - Dedicated database access",
                rights["can_connect"],
            )

            check(
                "13 - No database creation privileges",
                not rights["can_create"],
            )

            check(
                "14 - No temporary table privileges",
                not rights["can_temp"],
            )

            check(
                "15 - Default database isolated",
                not rights["other_database"],
            )

            cur.execute("""
                SELECT
                    has_schema_privilege(
                        current_user,
                        'public',
                        'USAGE'
                    ) AS can_use,
                    has_schema_privilege(
                        current_user,
                        'public',
                        'CREATE'
                    ) AS can_create
            """)

            schema = cur.fetchone()

            check(
                "16 - Restricted schema permissions",
                schema["can_use"]
                and not schema["can_create"],
            )

            cur.execute("""
                SELECT
                    c.relname AS table_name,
                    c.relrowsecurity AS rls_enabled,
                    has_table_privilege(
                        current_user, c.oid, 'SELECT'
                    ) AS can_read,
                    has_table_privilege(
                        current_user, c.oid, 'DELETE'
                    ) AS can_delete,
                    has_table_privilege(
                        current_user, c.oid, 'TRUNCATE'
                    ) AS can_truncate,
                    pg_get_userbyid(c.relowner)
                        AS table_owner
                FROM pg_class c
                JOIN pg_namespace n
                  ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relkind = 'r'
            """)

            tables = cur.fetchall()

            check(
                "17 - All ten expected tables",
                {
                    row["table_name"]
                    for row in tables
                } == EXPECTED_TABLES,
            )

            check(
                "18 - RLS enabled on all tables",
                all(
                    row["rls_enabled"]
                    for row in tables
                ),
            )

            check(
                "19 - No DELETE or TRUNCATE rights",
                all(
                    not row["can_delete"]
                    and not row["can_truncate"]
                    for row in tables
                ),
            )

            check(
                "20 - Application does not own tables",
                all(
                    row["table_owner"] != "v80_app"
                    for row in tables
                ),
            )

            cur.execute("""
                SELECT COUNT(*) AS total
                FROM pg_trigger t
                JOIN pg_class c
                  ON c.oid = t.tgrelid
                JOIN pg_namespace n
                  ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND NOT t.tgisinternal
                  AND t.tgenabled IN ('O', 'A')
            """)

            check(
                "21 - Six active protection triggers",
                cur.fetchone()["total"] == 6,
            )

            cur.execute("""
                SELECT COUNT(*) AS total
                FROM pg_policies
                WHERE schemaname = 'public'
            """)

            check(
                "22 - Expected RLS policy count",
                cur.fetchone()["total"] == 25,
            )

            check(
                "23 - Application table read privileges",
                all(
                    row["can_read"]
                    for row in tables
                ),
            )

            cur.execute("""
                SELECT
                    has_table_privilege(
                        current_user,
                        'public.nba_historical_bookmaker_lines',
                        'SELECT'
                    ) AS can_read,
                    has_table_privilege(
                        current_user,
                        'public.nba_historical_bookmaker_lines',
                        'INSERT'
                    ) AS can_insert,
                    has_table_privilege(
                        current_user,
                        'public.nba_historical_bookmaker_lines',
                        'UPDATE'
                    ) AS can_update,
                    has_table_privilege(
                        current_user,
                        'public.nba_historical_bookmaker_lines',
                        'DELETE'
                    ) AS can_delete,
                    has_table_privilege(
                        current_user,
                        'public.nba_historical_bookmaker_lines',
                        'TRUNCATE'
                    ) AS can_truncate
            """)
            bookmaker_rights = cur.fetchone()
            check(
                "24 - Bookmaker prices are read-only to the app",
                bookmaker_rights["can_read"]
                and not any([
                    bookmaker_rights["can_insert"],
                    bookmaker_rights["can_update"],
                    bookmaker_rights["can_delete"],
                    bookmaker_rights["can_truncate"],
                ]),
            )

            cur.execute("""
                SELECT COUNT(*) AS total
                FROM public.nba_historical_bookmaker_lines
                WHERE license_review_status <> 'approved'
            """)
            check(
                "25 - App cannot read unapproved bookmaker data",
                cur.fetchone()["total"] == 0,
            )

            cur.execute("""
                SELECT COUNT(*) AS total
                FROM public.nba_predictions
            """)

            check(
                "26 - Prediction table readable",
                cur.fetchone()["total"] >= 0,
            )

            cur.execute("""
                SELECT COUNT(*) AS total
                FROM public.nba_model_versions
            """)

            check(
                "27 - Model registry readable",
                cur.fetchone()["total"] >= 0,
            )

            # Confirm PostgreSQL rejects a write command.
            # No records are inserted, updated or deleted.
            cur.execute("SAVEPOINT readonly_test")

            blocked = False

            try:
                cur.execute("""
                    UPDATE public.nba_predictions
                    SET actual = actual
                    WHERE FALSE
                """)
            except psycopg.Error as exc:
                blocked = exc.sqlstate == "25006"
            finally:
                cur.execute(
                    "ROLLBACK TO SAVEPOINT readonly_test"
                )
                cur.execute(
                    "RELEASE SAVEPOINT readonly_test"
                )

            check(
                "28 - Write blocked by read-only transaction",
                blocked,
            )

    print("=" * 50)
    print(f"RESULT: {len(passed)}/28 TESTS PASSED")
    print("V8.0 NEON DATABASE READ-ONLY TEST PASSED")
    print("=" * 50)


if __name__ == "__main__":
    try:
        run_tests()
    except Exception as exc:
        print("=" * 50)
        print(f"RESULT: {len(passed)}/26 TESTS PASSED")
        print("V8.0 DATABASE TEST FAILED")

        # Only print controlled test names.
        # Never print connection strings or raw errors.
        if type(exc) is RuntimeError:
            print(f"Failed test: {exc}")
        else:
            print(f"Error type: {type(exc).__name__}")

        sys.exit(1)
