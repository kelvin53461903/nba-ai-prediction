from collections import defaultdict, Counter
from datetime import datetime, timezone, timedelta
import math
import pyarrow.parquet as pq

def audit_market(games):
    cutoff=datetime(2026,4,2,tzinfo=timezone.utc)
    assert len(games)==2459 and len({g["nba_id"] for g in games})==2459
    index={g["nba_id"]:g for g in games}
    assert all(datetime.fromisoformat(g["tip"])<cutoff for g in games)
    coverage=defaultdict(set)
    rows=Counter()
    rejected=Counter()
    for season in (2025,2026):
        for r in pq.read_table(f"lines_{season}.parquet").to_pylist():
            g=index.get(r["game_id"])
            if g is None: continue
            if g["season"]!=season or {r["home_team_id"],r["away_team_id"]}!={g["home"],g["away"]}:
                rejected["team_or_season"]+=1; continue
            rows[str(r["provider_id"])]+=1
            for phase in ("open","close"):
                for market,fields in (("moneyline",("home_moneyline","away_moneyline")),("spread",("spread",)),("total",("total",)),("spread_prices",("home_spread_odds","away_spread_odds")),("total_prices",("over_odds","under_odds"))):
                    v=[r.get(phase+"_"+k) for k in fields]
                    if not all(isinstance(x,(float,int)) and math.isfinite(x) for x in v): continue
                    if market=="spread": ok=abs(v[0])<=60
                    elif market=="total": ok=100<=v[0]<=400
                    else: ok=all(abs(x)>=100 for x in v)
                    if ok: coverage[phase+"_"+market].add(g["nba_id"])
    return dict(target_games=len(games),cutoff=cutoff.isoformat(),coverage={k:len(v) for k,v in coverage.items()},provider_rows=dict(rows),rejected=dict(rejected),verified_quote_games=0,strict_backtest={"n":0,"status":"blocked_missing_quote_timestamp_and_provenance"},research_only=True)
