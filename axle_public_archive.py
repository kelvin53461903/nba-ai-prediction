import json, hashlib, math, io
from urllib.request import urlopen
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import pyarrow.parquet as pq
BASE="https://basketball-data.billmill.org/nba/stats/"
def load(name,season=2027):
    with urlopen(f"{BASE}{name}/season={season}/data.parquet",timeout=45) as r:
        raw=r.read()
    return pq.ParquetFile(io.BytesIO(raw)).read(use_threads=False).to_pylist(),hashlib.sha256(raw).hexdigest()
def pilot():
    schedule,sh=load("schedule")
    logs,lh=load("team_game_logs")
    now=datetime.now(timezone.utc)
    index={g["game_id"]:g for g in schedule}
    grouped=defaultdict(list)
    for row in logs: grouped[row["game_id"]].append(row)
    finals=0; history=defaultdict(list)
    from collections import Counter
    types=Counter(); rejects=Counter()
    for gid,rows in grouped.items():
        g=index.get(gid)
        if not g or g["status"]!="final" or len(rows)!=2 or g["neutral_site"]: continue
        if {x["team_id"] for x in rows}!={g["home_team_id"],g["away_team_id"]}: continue
        if g["start_time"]>=now: continue
        h,a=sorted(rows,key=lambda x:x["team_id"]!=g["home_team_id"])
        if min(h["pts"],a["pts"])<=0 or h["pts"]==a["pts"]: continue
        finals+=1
        types[str(g["game_type"])]+=1
        if g["start_time"]>now-timedelta(days=2) or g["game_type"] not in ("regular_season","cup_final"): continue
        for x in rows:
            v=[x[k] for k in ("off_rating","def_rating","pace")]
            if all(y is not None and math.isfinite(y) and y>0 for y in v):
                history[x["team_id"]].append((g["start_time"],v))
    print("ARCHIVE_DIAGNOSTICS",json.dumps(dict(game_types=dict(types),counts={str(k):len(v) for k,v in history.items()},sample_schedule_keys=list(schedule[0]),sample_log_keys=list(logs[0]))))
    ready=sum(len(v)>=20 for v in history.values())
    report=dict(source=BASE,captured_at=now.isoformat(),schedule_sha256=sh,logs_sha256=lh,finals=finals,teams_with_10_games=sum(len(v)>=10 for v in history.values()),teams_with_20_games=ready,upcoming=sum(g["status"]=="scheduled" and g["start_time"]>now for g in schedule if g["start_time"]),research_only=True,license_verified=False,predictions_written=0)
    print("PUBLIC_ARCHIVE",json.dumps(report))
if __name__=="__main__": pilot()
