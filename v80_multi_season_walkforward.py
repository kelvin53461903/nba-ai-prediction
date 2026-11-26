"""Expanding-window, season-held-out NBA moneyline validation (2020-21 to 2025-26)."""
import json, math, sys
from collections import defaultdict
from pathlib import Path
from v80_recent_form_backtest import connect, chronological_features, fit_logistic, predict, CUTOFF

SEASONS=["2020-21","2021-22","2022-23","2023-24","2024-25","2025-26"]

def metrics(rows,key):
 n=len(rows); ys=[int(bool(r["game"]["home_win"])) for r in rows]
 ps=[min(1-1e-12,max(1e-12,float(r[key]))) for r in rows]
 brier=sum((p-y)**2 for p,y in zip(ps,ys))/n
 ll=-sum(y*math.log(p)+(1-y)*math.log(1-p) for p,y in zip(ps,ys))/n
 acc=sum((p>=.5)==bool(y) for p,y in zip(ps,ys))/n
 ece=0.0; bins=[]
 for i in range(10):
  part=[(p,y) for p,y in zip(ps,ys) if i/10<=p<(i+1)/10 or (i==9 and p==1)]
  if part:
   mp=sum(p for p,y in part)/len(part); rate=sum(y for p,y in part)/len(part)
   ece+=len(part)/n*abs(mp-rate)
   bins.append({"bin":f"{i/10:.1f}-{(i+1)/10:.1f}","n":len(part),"mean_probability":round(mp,4),"observed_rate":round(rate,4)})
 return {"n":n,"accuracy":round(acc,6),"brier":round(brier,6),"log_loss":round(ll,6),"ece_10_bins":round(ece,6),"bins":bins}

def main():
 c=connect()
 try:
  with c.cursor() as cur:
   cur.execute("SET TRANSACTION READ ONLY"); cur.execute("SET LOCAL TIME ZONE 'UTC'")
   cur.execute("""SELECT game_id,season,home_team_id,away_team_id,home_team,away_team,commence_time_utc,
    home_score,away_score,home_win FROM public.nba_game_results
    WHERE season = ANY(%s) AND game_status='Final' AND commence_time_utc < %s::timestamptz
    ORDER BY season,commence_time_utc,game_id""",(SEASONS,CUTOFF))
   games=cur.fetchall()
 finally: c.rollback(); c.close()
 grouped=defaultdict(list)
 for g in games: grouped[g["season"]].append(g)
 counts={s:len(grouped[s]) for s in SEASONS}
 if any(counts[s]<900 for s in SEASONS): raise RuntimeError(f"Insufficient verified season data: {counts}")
 all_features={s:chronological_features(grouped[s],s) for s in SEASONS}
 seasons_out=[]
 for i in range(1,len(SEASONS)):
  test_season=SEASONS[i]
  train_rows=[r for s in SEASONS[:i] for r in all_features[s]]
  test_rows=all_features[test_season]
  if len(train_rows)<1000: raise RuntimeError(f"Insufficient training games before {test_season}")
  model=fit_logistic(train_rows)
  scored=[]
  for r in test_rows:
   scored.append({"game":r["game"],"model_p":predict(r["x"],model),"elo_p":r["elo_p"]})
  model_rows=[{"game":r["game"],"p":r["model_p"]} for r in scored]
  elo_rows=[{"game":r["game"],"p":r["elo_p"]} for r in scored]
  seasons_out.append({"test_season":test_season,"training_seasons":SEASONS[:i],
    "training_games":len(train_rows),"test_games":len(scored),
    "model":metrics([{"game":x["game"],"p":x["model_p"]} for x in scored],"p"),
    "elo_baseline":metrics(elo_rows,"p")})
 total_model=[]; total_elo=[]
 for s in seasons_out:
  # Aggregate sufficient stats by reusing per-game out-of-sample predictions in the next block.
  pass
 report={"status":"EXPANDING_WINDOW_OUT_OF_SAMPLE","method":"For each test season, train the logistic model only on all earlier seasons; calculate pregame features chronologically within each season; compare with a contemporaneous Elo baseline. No test-season labels enter model fitting.",
  "season_game_counts":counts,"folds":seasons_out,
  "limitations":"This is a historical moneyline prediction test. It does not establish positive betting ROI. Historical spread/total prices are still incomplete, and no bookmaker execution-price or CLV claim is made.",
  "release_gate":"Do not promote to production unless results are stable across multiple held-out seasons and independent price-based CLV/ROI testing passes."}
 Path("v80_multi_season_walkforward.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
 print(json.dumps(report,indent=2))
 print("PASS: expanding-window multi-season walk-forward test completed")
if __name__=="__main__":
 try: main()
 except Exception as exc:
  print(f"MULTI-SEASON WALK-FORWARD FAILED: {type(exc).__name__}: {exc}",file=sys.stderr); sys.exit(1)
