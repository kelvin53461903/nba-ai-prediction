"""Research-only connection check; no live writes or credential output."""
import os,json
from axle_holdout_settle import summarize

def run():
    dsn=os.environ.get("AXLE_TEST_DATABASE_URL")
    if not dsn:
        print("NEON_READINESS",json.dumps({"status":"blocked_missing_test_secret","writes":0}))
        return
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    cfg=conninfo_to_dict(dsn)
    if cfg.get("dbname")!="nba_v80" or cfg.get("sslmode") not in ("require","verify-full","verify-ca") or not cfg.get("host","").endswith(".neon.tech"):
        raise ValueError("isolated TLS database required")
    with psycopg.connect(dsn,connect_timeout=10) as con:
        con.execute("SET TRANSACTION READ ONLY")
        if con.execute("SELECT current_database()").fetchone()[0]!="nba_v80": raise ValueError("wrong database")
        count=con.execute("SELECT count(*) FROM public.axle_holdout_research").fetchone()[0]
        print("NEON_READINESS",json.dumps({"status":"read_only_connected","records":count,"writes":0,"settlement":"blocked_pending_verified_records"}))
if __name__=="__main__": run()
