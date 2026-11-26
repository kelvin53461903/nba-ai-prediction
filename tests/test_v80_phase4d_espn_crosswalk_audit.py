import importlib.util
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "scripts" / "v80_phase4d_espn_crosswalk_audit.py"
spec = importlib.util.spec_from_file_location("v80_phase4d_espn_crosswalk_audit", PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class Phase4DCrosswalkTests(unittest.TestCase):
    def test_canonical_team_alias(self):
        self.assertEqual(module.canonical_team("LA Clippers"), "Los Angeles Clippers")

    def test_parse_scoreboard_event(self):
        payload = {"events": [{
            "id": "123", "date": "2025-01-02T00:30:00Z",
            "competitions": [{"date": "2025-01-02T00:30:00Z", "status": {"type": {"name": "STATUS_FINAL"}}, "competitors": [
                {"homeAway": "home", "score": "110", "team": {"displayName": "Los Angeles Lakers"}},
                {"homeAway": "away", "score": "105", "team": {"displayName": "Boston Celtics"}}
            ]}]
        }]}
        rows = module.scoreboard_event_rows(payload)
        self.assertEqual(rows[0]["event_id"], "123")
        self.assertEqual(rows[0]["home_score"], 110)
        self.assertEqual(rows[0]["away"], "Boston Celtics")
        self.assertEqual(rows[0]["date"], "2025-01-01")

    def test_exact_score_match(self):
        event = {"date":"2025-01-01","home":"Los Angeles Lakers","away":"Boston Celtics","home_score":110,"away_score":105}
        game = {"game_id":"1","game_date":"2025-01-01","home_team":"Los Angeles Lakers","away_team":"Boston Celtics","home_score":110,"away_score":105}
        self.assertEqual(module.match_event(event,[game])["status"], "EXACT_SCORE_MATCH")

    def test_score_mismatch(self):
        event = {"date":"2025-01-01","home":"Los Angeles Lakers","away":"Boston Celtics","home_score":110,"away_score":105}
        game = {"game_id":"1","game_date":"2025-01-01","home_team":"Los Angeles Lakers","away_team":"Boston Celtics","home_score":109,"away_score":105}
        self.assertEqual(module.match_event(event,[game])["status"], "SCORE_MISMATCH")

    def test_ambiguous_event_rejected(self):
        event = {"date":"2025-01-01","home":"Los Angeles Lakers","away":"Boston Celtics","home_score":110,"away_score":105}
        games = [{"game_id":str(i),"game_date":"2025-01-01","home_team":"Los Angeles Lakers","away_team":"Boston Celtics","home_score":110,"away_score":105} for i in (1,2)]
        self.assertEqual(module.match_event(event,games)["status"], "AMBIGUOUS")

if __name__ == "__main__":
    unittest.main()
