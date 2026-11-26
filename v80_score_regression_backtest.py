#!/usr/bin/env python3
"""Regularized score-regression experiment with temporal calibration holdout."""
import json, math, sys
from pathlib import Path
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from v80_recent_form_backtest import connect, chronological_features, CUTOFF, EXPECTED

def metrics(ps,ys):
 n=len(ys)
 if not n: return {"n":0}
 ps=[min(1-1e-9,max(1e-9,float(p))) for p in ps]
 b=sum((p-y)**2 for p,y in zip(ps,ys))/n
 ll=-sum(y*math.log(p)+(1-y)*math.log(1-p) for p,y in zip(ps,ys))/n
 acc=sum((p>=.5)==bool(y) for p,y in zip(ps,ys))/n
 ece=0.0
 for i in range(10):
  part=[(p,y) for p,y in zip(ps,ys) if i/10<=p<(i+1)/10 or (i==9 and p==1)]
  if part: ece+=len(part)/n*abs(sum(p for p,y in part)/len(part)-sum(y for p,y in part)/len(part))
 return {"n":n,"brier":round(b,6),"log_loss":round(ll,6),"directional_accuracy":round(acc,6),"ece_10_bins":round(ece,6)}
def empirical_prob(residuals,threshold):
 return sum(r>threshold for r in residuals)/len(residuals)
def main():
 c=connect()
 try:
  with c.cursor() as cur:
   cur.execute("SET TRANSACTION READ ONLY")
   cur.execute("SET LOCAL TIME ZONE 'UTC'")
   cur.execute("""SELECT g.game_id,g.season,g.home_team_id,g.away_team_id,g.home_team,g.away_team,
     g.commence_time_utc,g.home_score,g.away_score,g.home_win,
     m.close_home_win_prob,m.close_spread_home,m.close_home_cover_prob,m.close_total,m.close_over_prob,
     m.ats_result,m.total_result
     FROM public.nba_game_results g
     LEFT JOIN public.nba_historical_market_closes m ON m.game_id=g.game_id
     WHERE g.season IN ('2024-25','2025-26') AND g.game_status='Final'
     AND g.commence_time_utc < %s::timestamptz ORDER BY g.commence_time_utc,g.game_id""",(CUTOFF,))
   games=cur.fetchall()
 finally: c.rollback(); c.close()
 train=[g for g in games if g["season"]=="2024-25"]
 test=[g for g in games if g["season"]=="2025-26"]
 if len(train)!=EXPECTED["2024-25"] or len(test)!=EXPECTED["2025-26"]: raise RuntimeError("Season counts do not match verified dataset")
 tr=chronological_features(train,"2024-25")
 te=chronological_features(test,"2025-26")
 # Keep the final 20% of 2024-25 strictly out of fitting for residual calibration.
 cut=int(len(tr)*0.8)
 fit_rows,cal_rows=tr[:cut],tr[cut:]
 def targets(rows):
  margins=[]; totals=[]
  for r in rows:
   g=r["game"]; margins.append(g["home_score"]-g["away_score"]); totals.append(g["home_score"]+g["away_score"])
  return margins,totals
 ym,yt=targets(fit_rows)
 X=[r["x"] for r in fit_rows]
 margin_model=make_pipeline(StandardScaler(),Ridge(alpha=25.0))
 total_model=make_pipeline(StandardScaler(),Ridge(alpha=25.0))
 margin_model.fit(X,ym); total_model.fit(X,yt)
 cal_margin,cal_total=targets(cal_rows)
 cal_margin_pred=margin_model.predict([r["x"] for r in cal_rows])
 cal_total_pred=total_model.predict([r["x"] for r in cal_rows])
 margin_res=[float(y-p) for y,p in zip(cal_margin,cal_margin_pred)]
 total_res=[float(y-p) for y,p in zip(cal_total,cal_total_pred)]
 out=[]
 for r in te:
  g=r["game"]
  if any(g[k] is None for k in ("close_spread_home","close_home_cover_prob","close_total","close_over_prob","ats_result","total_result")): continue
  pm=float(margin_model.predict([r["x"]])[0])
  pt=float(total_model.predict([r["x"]])[0])
  line=float(g["close_spread_home"]); total_line=float(g["close_total"])
  pcover=empirical_prob(margin_res,-(pm+line))
  pover=empirical_prob(total_res,total_line-pt)
  out.append({"ats":g["ats_result"],"total":g["total_result"],"pcover":pcover,
    "market_cover":float(g["close_home_cover_prob"]),"pover":pover,"market_over":float(g["close_over_prob"]),
    "margin_error":(g["home_score"]-g["away_score"])-pm,"total_error":(g["home_score"]+g["away_score"])-pt})
 ats=[r for r in out if r["ats"] in ("home","away")]
 totals=[r for r in out if r["total"] in ("over","under")]
 report={"status":"experimental_score_regression_not_approved","training_season":"2024-25","evaluation_season":"2025-26",
  "fit_rows":len(fit_rows),"calibration_rows":len(cal_rows),"test_market_rows":len(out),
  "method":"Ridge regression with StandardScaler, alpha=25. First 80% of 2024-25 fits score margin and total; final 20% calibrates empirical residual distributions; 2025-26 is untouched holdout.",
  "spread":{"n":len(ats),"ridge_model":metrics([r["pcover"] for r in ats],[int(r["ats"]=="home") for r in ats]),
    "market_close":metrics([r["market_cover"] for r in ats],[int(r["ats"]=="home") for r in ats]),
    "margin_mae":round(sum(abs(r["margin_error"]) for r in ats)/len(ats),4) if ats else None},
  "totals":{"n":len(totals),"ridge_model":metrics([r["pover"] for r in totals],[int(r["total"]=="over") for r in totals]),
    "market_close":metrics([r["market_over"] for r in totals],[int(r["total"]=="over") for r in totals]),
    "total_mae":round(sum(abs(r["total_error"]) for r in totals)/len(totals),4) if totals else None},
  "limitations":"One held-out season only. Market consensus is a benchmark, not a guaranteed executable price. Do not deploy or claim positive ROI unless independent multi-season testing and actual price-based CLV/ROI tests pass."}
 Path("v80_score_regression_backtest.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
 print(json.dumps(report,indent=2)); print("PASS: temporal score-regression experiment completed")
if __name__=="__main__":
 try: main()
 except Exception as exc:
  print(f"SCORE REGRESSION BACKTEST FAILED: {type(exc).__name__}: {exc}",file=sys.stderr); sys.exit(1)
