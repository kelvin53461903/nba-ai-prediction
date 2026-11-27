"""Free NBA Stats pilot. Reconstructed data is never a contemporaneous snapshot."""
import argparse, json, math
from datetime import date, datetime, timezone
from pathlib import Path

def normalize(rows, season, cutoff, captured):
    result=[]
    seen=set()
    for row in rows:
        team=int(row["TEAM_ID"])
        if team in seen or not 1610612737 <= team <= 1610612766:
            raise ValueError("Unexpected or duplicate NBA team")
        seen.add(team)
        gp=int(row["GP"])
        values=[float(row[k]) for k in ("OFF_RATING","DEF_RATING","PACE")]
        if gp<=0 or not all(math.isfinite(v) and v>0 for v in values):
            raise ValueError("Invalid advanced statistics")
        result.append(dict(team_id=team,team_name=row["TEAM_NAME"],season=season,
            season_type="Regular Season",games_played=gp,offensive_rating=values[0],
            defensive_rating=values[1],pace=values[2],cutoff_date=cutoff.isoformat(),
            captured_at_utc=captured.isoformat(),available_at_utc=captured.isoformat(),
            source="NBA.com",is_reconstructed=True))
    if len(result)!=30: raise ValueError("Expected all 30 teams")
    return result

def main():
    from nba_api.stats.endpoints import leaguedashteamstats
    p=argparse.ArgumentParser()
    p.add_argument("--season",default="2025-26")
    p.add_argument("--cutoff",default="2025-12-31")
    p.add_argument("--output",default="axle_advanced_pilot.json")
    a=p.parse_args()
    cutoff=date.fromisoformat(a.cutoff)
    if cutoff>=datetime.now(timezone.utc).date(): raise ValueError("Cutoff must be historical")
    endpoint=leaguedashteamstats.LeagueDashTeamStats(season=a.season,
        season_type_all_star="Regular Season",measure_type_detailed_defense="Advanced",
        date_to_nullable=cutoff.strftime("%m/%d/%Y"),league_id_nullable="00",timeout=30)
    payload=endpoint.get_dict()
    params=payload.get("parameters",{})
    if params.get("DateTo")!=cutoff.strftime("%m/%d/%Y") or params.get("Season")!=a.season or params.get("MeasureType")!="Advanced":
        raise ValueError("Response parameters not confirmed")
    data=next(x for x in payload["resultSets"] if x["name"]=="LeagueDashTeamStats")
    rows=[dict(zip(data["headers"],r)) for r in data["rowSet"]]
    captured=datetime.now(timezone.utc)
    out=normalize(rows,a.season,cutoff,captured)
    Path(a.output).write_text(json.dumps({"request":params,"raw":payload,"rows":out},indent=2))
    print("Validated pilot rows:",len(out),"; reconstruction only, not historical availability proof")

if __name__=="__main__": main()
