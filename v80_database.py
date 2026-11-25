
"""
NBA AI V8.0 CALIBRATION PRO
Isolated Neon PostgreSQL connection module.
"""

import os
from contextlib import contextmanager

import certifi
import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row


DATABASE_NAME = "nba_v80"
DATABASE_ROLE = "v80_app"
SECRET_NAME = "V80_TEST_DATABASE_URL"

EXPECTED_HOST = (
    "ep-summer-boat-bi5bgzrl"
    ".c-5.ap-southeast-1.aws.neon.tech"
)


class V80DatabaseError(RuntimeError):
    pass


def get_connection_config():
    database_url = os.environ.get(
        SECRET_NAME, ""
    ).strip()

    if not database_url:
        raise V80DatabaseError(
            "V80 database secret is missing."
        )

    try:
        config = conninfo_to_dict(database_url)
    except Exception:
        raise V80DatabaseError(
            "Invalid V80 database configuration."
        ) from None

    if config.get("dbname") != DATABASE_NAME:
        raise V80DatabaseError(
            "Unexpected database name."
        )

    if config.get("user") != DATABASE_ROLE:
        raise V80DatabaseError(
            "Unexpected database role."
        )

    if config.get("host") != EXPECTED_HOST:
        raise V80DatabaseError(
            "Unexpected Neon endpoint."
        )

    if config.get("port", "5432") != "5432":
        raise V80DatabaseError(
            "Unexpected database port."
        )

    if not config.get("password"):
        raise V80DatabaseError(
            "Database password is missing."
        )

    return {
        "host": EXPECTED_HOST,
        "port": 5432,
        "dbname": DATABASE_NAME,
        "user": DATABASE_ROLE,
        "password": config["password"],
        "sslmode": "verify-full",
        "sslrootcert": certifi.where(),
        "channel_binding": "require",
        "connect_timeout": 15,
        "application_name": "NBA_AI_V80_TEST",
        "row_factory": dict_row,
        "autocommit": False,
    }


@contextmanager
def connect_v80():
    """
    Open a verified read-only V8.0 connection.
    No production database fallback is permitted.
    """

    config = get_connection_config()
    conn = None

    try:
        print(
            "DIAGNOSTIC: libpq version =",
            psycopg.pq.version(),
        )

        conn = psycopg.connect(**config)

        print("DIAGNOSTIC: Connection established")

    except Exception as exc:
        message = str(exc).lower()

        if "certificate" in message:
            reason = "SSL_CERTIFICATE_ERROR"
        elif "password authentication failed" in message:
            reason = "PASSWORD_AUTHENTICATION_FAILED"
        elif "permission denied" in message:
            reason = "DATABASE_ACCESS_DENIED"
        elif "channel binding" in message:
            reason = "CHANNEL_BINDING_ERROR"
        elif "timeout" in message:
            reason = "CONNECTION_TIMEOUT"
        else:
            reason = "OTHER_CONNECTION_ERROR"

        print("DIAGNOSTIC:", reason)
        print("ERROR CLASS:", type(exc).__name__)

        raise V80DatabaseError(
            "V80 secure database connection failed."
        ) from None

    try:
        # Verify actual client-side TLS.
        ssl_enabled = bool(conn.pgconn.ssl_in_use)

        print(
            "DIAGNOSTIC: Client SSL =",
            ssl_enabled,
        )

        if not ssl_enabled:
            raise V80DatabaseError(
                "Client TLS verification failed."
            )

        with conn.cursor() as cur:
            cur.execute(
                "SET TRANSACTION READ ONLY"
            )

            cur.execute(
                "SET LOCAL TIME ZONE 'UTC'"
            )

            cur.execute(
                "SET LOCAL statement_timeout = '30s'"
            )

            cur.execute("""
                SELECT
                    current_database() AS database_name,
                    current_user AS database_role,
                    session_user AS session_role,
                    current_setting(
                        'transaction_read_only'
                    ) AS read_only
            """)

            status = cur.fetchone()

        print(
            "DIAGNOSTIC: Database =",
            status["database_name"],
        )

        print(
            "DIAGNOSTIC: Role =",
            status["database_role"],
        )

        print(
            "DIAGNOSTIC: Session role =",
            status["session_role"],
        )

        print(
            "DIAGNOSTIC: Read only =",
            status["read_only"],
        )

        if (
            status["database_name"] != DATABASE_NAME
            or status["database_role"] != DATABASE_ROLE
            or status["session_role"] != DATABASE_ROLE
            or status["read_only"] != "on"
        ):
            raise V80DatabaseError(
                "V80 connection safety verification failed."
            )

        yield conn

    finally:
        if conn is not None:
            try:
                conn.rollback()
            finally:
                conn.close()



def check_connection():
    """Return non-sensitive client TLS diagnostics."""

    with connect_v80() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    current_database() AS database_name,
                    current_user AS database_role,
                    current_setting(
                        'TimeZone'
                    ) AS timezone,
                    current_setting(
                        'transaction_read_only'
                    ) AS read_only
            """)

            result = cur.fetchone()

        result["ssl"] = bool(
            conn.pgconn.ssl_in_use
        )

        # Psycopg 3 PGconn does not expose
        # ssl_attribute() in its public API.
        # Do not invent a TLS protocol version.
        result["tls_version"] = None

    return result
