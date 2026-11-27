import tempfile, unittest
from datetime import datetime, timezone
from axle_holdout_capture import capture, utc
from axle_snapshot_research import grade

class TestHoldout(unittest.TestCase):
    def test_capture(self):
        now=utc("2026-12-01T00:00:00Z")
        r=dict(game_id="synthetic",market="spread",model="Rolling 10",provider="synthetic",quote_source="synthetic",feature_source="synthetic",model_commit="synthetic",tip="2026-12-01T01:00:00Z",quote_at="2026-11-30T23:00:00Z",feature_available_at="2026-11-30T23:00:00Z",prediction_at="2026-11-30T23:30:00Z",prediction=4,line=-3)
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(len(capture(r,d,now)),64)
            with self.assertRaises(FileExistsError): capture(r,d,now)
            with self.assertRaises(ValueError): capture(r,d,utc(r["tip"]))
            with self.assertRaises(ValueError): capture(dict(r,quote_at=r["tip"]),d,now)
    def test_settlement(self):
        self.assertEqual(grade(1,0),"push")
        self.assertEqual(grade(1,-1),"loss")
        self.assertEqual(grade(-1,-1),"win")
if __name__=="__main__": unittest.main()
