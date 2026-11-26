"""Market-aware hybrid calibration experiment: market close plus pregame NBA features."""
import json, math, sys
from pathlib import Path
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from v80_recent_form_backtest import connect, chronological_features, CUTOFF

TRAIN="2024-25"; TEST="2025-26"
def logit(p):
 p=min(max(float(p),1e-6),1-1e-6)
 return math.log(p/(1-p))
def metrics(ps,ys):
 n=len(ys); ps=[min(1-1e-9,max(1e-9,float(p))) for p in ps]
 b=sum((p-y)**2 for p,y in zip(ps,ys))/n
 ll=-sum(y*math.log(p)+(1-y)*math.log(1-p) for p,y in zip(ps,ys))/n
 acc=sum((p>=.5)==bool(y) for p,y in zip(ps,ys))/n
 ece=0.0
 for i in range(10):
  part=[(p,y) for p,y in zip(ps,ys) if i/10<=p<(i+1)/10 or (i==9 and p==1)]
  if part: ece+=len(part)/n*abs(sum(p for p,y in part)/len(part)-sum(y for p,y in part)/len(part))
 return {"n":n,"brier":round(b,6),"log_loss":round(ll,6),"directional_accuracy":round(acc,6),"ece_10_bins":round(ece,6)}
def score_forecast(x):
 hf,ha,af,aa=x[11]*100,x[13]*100,x[12]*100,x[14]*100
 ph=(hf+aa)/2; pa=(af+ha)/2
 return ph-pa,ph+pa
def main():
 c=connect()
 try:
  with c.cursor() as cur:
   cur.execute("SET TRANSACTION READ ONLY"); cur.execute("SET LOCAL TIME ZONE 'UTC'")
   cur.execute("""SELECT g.game_id,g.season,g.home_team_id,g.away_team_id,g.home_team,g.away_team,
    g.commence_time_utc,g.home_score,g.away_score,g.home_win,
    m.close_home_win_prob,m.close_home_cover_prob,m.close_over_prob,
    m.close_spread_home,m.close_total,m.ats_result,m.total_result
    FROM public.nba_game_results g LEFT JOIN public.nba_historical_market_closes m USING(game_id)
    WHERE g.season IN ('2024-25','2025-26') AND g.game_status='Final'
    AND g.commence_time_utc < %s::timestamptz ORDER BY g.season,g.commence_time_utc,g.game_id""",(CUTOFF,))
   games=cur.fetchall()
 finally: c.rollback(); c.close()
 by={TRAIN:[],TEST:[]}
 for g in games: by[g["season"]].append(g)
 if len(by[TRAIN])<1000 or len(by[TEST])<1000: raise RuntimeError("Insufficient same-sample market rows")
 feature_rows={}
 for season in (TRAIN,TEST):
  feature_rows[season]=chronological_features(by[season],season)
 lookup={s:{r["game"]["game_id"]:r for r in feature_rows[s]} for s in (TRAIN,TEST)}
 data={m:{"train_X":[],"train_y":[],"test_X":[],"test_y":[],"test_market":[]} for m in ("moneyline","spread","totals")}
 for season in (TRAIN,TEST):
  for g in by[season]:
   fr=lookup[season][g["game_id"]]; x=fr["x"]
   margin,total=score_forecast(x)
   for market in data:
    if market=="moneyline":
     if g["close_home_win_prob"] is None: continue
     p_market=float(g["close_home_win_prob"])
     y=int(bool(g["home_win"]))
     features=[logit(p_market),logit(fr["elo_p"])]
    elif market=="spread":
     if g["close_home_cover_prob"] is None or g["close_spread_home"] is None or g["ats_result"] not in ("home","away"): continue
     p_market=float(g["close_home_cover_prob"])
     y=int(g["ats_result"]=="home")
     features=[logit(p_market),margin+float(g["close_spread_home"])]
    else:
     if g["close_over_prob"] is None or g["close_total"] is None or g["total_result"] not in ("over","under"): continue
     p_market=float(g["close_over_prob"])
     y=int(g["total_result"]=="over")
     features=[logit(p_market),total-float(g["close_total"])]
    d=data[market]
    if season==TRAIN:
     d["train_X"].append(features); d["train_y"].append(y)
    else:
     d["test_X"].append(features); d["test_y"].append(y)
     d["test_market"].append(p_market)
 report={"status":"EXPERIMENTAL_MARKET_AWARE_HYBRID","train_season":TRAIN,"test_season":TEST,
  "method":"Fit regularized logistic regression on 2024-25 only. Inputs: no-vig consensus closing probability plus an independent pregame feature (Elo for moneyline; score-forecast edge against closing spread/total for the other markets). Evaluate once on untouched 2025-26 matched games.",
  "markets":{},"limitations":"This is a predictive calibration experiment, not an executable betting strategy. Consensus closing lines are not individual bookmaker prices. No ROI or CLV is inferred."}
 for market,d in data.items():
  Xtr=np.asarray(d["train_X"],dtype=float); ytr=np.asarray(d["train_y"],dtype=int)
  Xte=np.asarray(d["test_X"],dtype=float); yte=np.asarray(d["test_y"],dtype=int)
  if len(ytr)<1000 or len(yte)<500: raise RuntimeError(f"Insufficient {market} sample train={len(ytr)} test={len(yte)}")
  model=make_pipeline(StandardScaler(),LogisticRegression(C=0.1,max_iter=2000,solver="lbfgs"))
  model.fit(Xtr,ytr)
  hybrid=model.predict_proba(Xte)[:,1]
  report["markets"][market]={"train_n":len(ytr),"test_n":len(yte),
   "raw_market":metrics(d["test_market"],yte),"market_aware_hybrid":metrics(hybrid,yte),
   "hybrid_coefficients":model[-1].coef_[0].round(6).tolist(),
   "hybrid_intercept":round(float(model[-1].intercept_[0]),6)}
 Path("v80_market_aware_hybrid_backtest.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
 print(json.dumps(report,indent=2)); print("PASS: market-aware hybrid experiment completed")
if __name__=="__main__":
 try: main()
 except Exception as exc:
  print(f"MARKET-AWARE HYBRID FAILED: {type(exc).__name__}: {exc}",file=sys.stderr); sys.exit(1)
