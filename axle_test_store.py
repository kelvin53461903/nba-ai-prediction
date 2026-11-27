"""Synthetic-only database integration test; never connects to production."""
import sqlite3,json,tempfile
from pathlib import Path
from axle_holdout_capture import capture,utc
from axle_holdout_settle import summarize

def run():
    with tempfile.TemporaryDirectory() as d:
        db=Path(d)/"holdout_test.sqlite"
        record=dict(game_id="synthetic",market="spread",model="Rolling 10",provider="synthetic",quote_source="synthetic",feature_source="synthetic",model_commit="synthetic",home="H",away="A",tip="2026-12-01T01:00:00Z",quote_at="2026-11-30T23:00:00Z",feature_available_at="2026-11-30T23:00:00Z",prediction_at="2026-11-30T23:30:00Z",prediction=5,line=-3,price=1.91,price_format="decimal")
        folder=Path(d)/"capture"
        digest=capture(record,folder,utc("2026-12-01T00:00:00Z"))
        raw=next(folder.glob("*.json")).read_text()
        con=sqlite3.connect(db)
        with con:
            con.execute("CREATE TABLE predictions(game_id TEXT NOT NULL, market TEXT NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL, PRIMARY KEY(game_id,market))")
            con.execute("INSERT INTO predictions VALUES(?,?,?,?)",("synthetic","spread",raw,digest))
        try:
            with con: con.execute("INSERT INTO predictions VALUES(?,?,?,?)",("synthetic","spread",raw,digest))
            raise AssertionError("duplicate accepted")
        except sqlite3.IntegrityError: pass
        con.close()
        con=sqlite3.connect(db)
        records=[json.loads(x[0]) for x in con.execute("SELECT payload FROM predictions")]
        result=dict(game_id="synthetic",status="Final",home="H",away="A",home_score=104,away_score=100,observed_at="2026-12-01T04:00:00Z")
        stats=summarize(records,[result])
        assert stats["spread"]["counts"]["win"]==1
        assert len(records)==1 and stats["spread"]["roi"] is None
        con.close()
        print("SQLITE_E2E synthetic persistence duplicate rejection settlement PASS; real_records=0")
if __name__=="__main__": run()
