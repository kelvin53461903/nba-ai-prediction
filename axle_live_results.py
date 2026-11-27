import json
from urllib.request import urlopen
from datetime import datetime, timezone
BASE="https://cdn.nba.com/static/json/liveData/"
def fetch(path):
    with urlopen(BASE+path,timeout=25) as response:
        return json.load(response)
def pilot():
    board=fetch("scoreboard/todaysScoreboard_00.json")
    games=board["scoreboard"]["games"]
    finals=[g for g in games if g["gameStatus"]==3]
    results=[]
    for g in finals:
        h,a=g["homeTeam"],g["awayTeam"]
        results.append(dict(game_id=g["gameId"],home=str(h["teamId"]),away=str(a["teamId"]),home_score=int(h["score"]),away_score=int(a["score"]),status="Final",observed_at=datetime.now(timezone.utc).isoformat()))
    report=dict(source=BASE,scoreboard_games=len(games),finals=len(results),boxscore_verified=False)
    if finals:
        game=fetch("boxscore/boxscore_"+finals[0]["gameId"]+".json")["game"]
        assert game["gameId"]==finals[0]["gameId"] and game["gameStatus"]==3
        fields=("fieldGoalsAttempted","freeThrowsAttempted","reboundsOffensive","turnovers")
        for side in ("homeTeam","awayTeam"):
            assert all(k in game[side]["statistics"] for k in fields)
        report["boxscore_verified"]=True
    print(json.dumps(report))
if __name__=="__main__": pilot()
