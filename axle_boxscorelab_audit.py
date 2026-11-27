import csv, hashlib, json, re
from pathlib import Path

def audit(path):
    raw=path.read_bytes()
    with path.open(encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        fields=reader.fieldnames or []
        rows=list(reader)
    if not rows or len(set(fields))!=len(fields):
        raise ValueError("Empty or ambiguous CSV")
    if any(None in r or any(v is None for v in r.values()) for r in rows):
        raise ValueError("Malformed CSV")
    aliases={re.sub(r"[^a-z0-9]","",k.lower()):k for k in fields}
    def pick(*names):
        return next((aliases[n] for n in names if n in aliases),None)
    team=pick("team","teamid","teamname","teamabbreviation","teamabbr","teamtricode")
    gid=pick("gameid","game")
    stage=pick("seasontype","gametype","stage","seasonphase","playoffs","isplayoff")
    teams=sorted({r[team] for r in rows}) if team else []
    counts={}
    if gid:
        for r in rows: counts[r[gid]]=counts.get(r[gid],0)+1
    stages=sorted({r[stage] for r in rows}) if stage else []
    return dict(file=path.name,sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw),columns=fields,rows=len(rows),team_column=team,teams=teams,game_id_column=gid,unique_games=len(counts) if gid else None,two_row_games=sum(v==2 for v in counts.values()) if gid else None,stage_column=stage,stage_values=stages,playoff_coverage="requires stage validation" if stage else "unverified",research_only=True)

if __name__=="__main__":
    reports=[audit(Path(f"box_{year}.csv")) for year in (2025,2026)]
    Path("boxscorelab_audit.json").write_text(json.dumps(reports,indent=2))
    print(json.dumps(reports,indent=2))
    if any(len(r["teams"])!=30 or r["unique_games"] is None or r["two_row_games"]!=r["unique_games"] for r in reports):
        raise ValueError("Team or game coverage not verified")
