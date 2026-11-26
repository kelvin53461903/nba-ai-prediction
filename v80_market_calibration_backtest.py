#!/usr/bin/env python3
"""Leakage-safe, season-held-out calibration benchmark for V8.0 market closes."""
from __future__ import annotations
import json, math, sys
from pathlib import Path
import psycopg
from v80_database import get_connection_config

TRAIN_SEASON="2024-25"
TEST_SEASON="2025-26"
MARKETS={
 "moneyline":{"prob":"close_home_win_prob","outcome":"home_win","label":"Home win"},
 "spread":{"prob":"close_home_cover_prob","outcome":"home_cover","label":"Home covers"},
 "totals":{"prob":"close_over_prob","outcome":"over","label":"Over"},
}
def logit(p):
 p=min(max(float(p),1e-6),1-1e-6)
 return math.log(p/(1-p))
def sigmoid(z):
 if z>=0:
  e=math.exp(-min(z,700)); return 1/(1+e)
 e=math.exp(max(z,-700)); return e/(1+e)
def fit_logistic_calibrator(ps,ys):
 xs=[logit(p) for p in ps]
 a,b=0.0,1.0
 ridge=1e-5
 for _ in range(100):
  g0=g1=h00=h01=h11=0.0
  for x,y in zip(xs,ys):
   q=sigmoid(a+b*x); w=q*(1-q); err=q-y
   g0+=err; g1+=err*x; h00+=w; h01+=w*x; h11+=w*x*x
  g1+=ridge*b; h11+=ridge
  det=h00*h11-h01*h01
  if det<=1e-14: break
  da=(g0*h11-g1*h01)/det
  db=(g1*h00-g0*h01)/det
  a-=da; b-=db
  if max(abs(da),abs(db))<1e-8: break
 return {"intercept":a,"slope":b}
def apply_calibrator(ps,params):
 return [sigmoid(params["intercept"]+params["slope"]*logit(p)) for p in ps]
def metrics(ps,ys):
 n=len(ys)
 if not n: raise RuntimeError("No test outcomes")
 brier=sum((p-y)**2 for p,y in zip(ps,ys))/n
 eps=1e-12
 ll=-sum(y*math.log(max(eps,min(1-eps,p)))+(1-y)*math.log(max(eps,min(1-eps,1-p))) for p,y in zip(ps,ys))/n
 acc=sum((p>=.5)==bool(y) for p,y in zip(ps,ys))/n
 bins=[]
 ece=0.0
 for i in range(10):
  lo=i/10; hi=(i+1)/10
  idx=[k for k,p in enumerate(ps) if (lo<=p<hi) or (i==9 and p==1)]
  if not idx: continue
  mp=sum(ps[k] for k in idx)/len(idx); rate=sum(ys[k] for k in idx)/len(idx)
  ece+=len(idx)/n*abs(mp-rate)
  bins.append({"range":f"{lo:.1f}-{hi:.1f}","n":len(idx),"mean_probability":round(mp,4),"observed_rate":round(rate,4)})
 return {"n":n,"brier":round(brier,6),"log_loss":round(ll,6),"directional_accuracy":round(acc,6),"ece_10_bins":round(ece,6),"calibration_bins":bins}
def main():
 cfg=get_connection_config()
 conn=psycopg.connect(**cfg)
 try:
  if not conn.pgconn.ssl_in_use: raise RuntimeError("TLS not active")
  with conn.cursor() as cur:
   cur.execute("SET TRANSACTION READ ONLY")
   cur.execute("SET LOCAL TIME ZONE 'UTC'")
   cur.execute("SET LOCAL statement_timeout='60s'")
   cur.execute("""SELECT current_database(),current_user,
    current_setting('transaction_read_only'),
    (SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user)""")
   state=cur.fetchone()
   if tuple(state)!=("nba_v80","v80_app","on",False): raise RuntimeError(f"Read-only app role verification failed: {tuple(state)}")
   cur.execute("""SELECT m.season,m.close_home_win_prob,m.close_home_cover_prob,m.close_over_prob,
      (m.home_score>m.away_score) AS home_win,
      (m.ats_result='home') AS home_cover,m.ats_result,
      (m.total_result='over') AS over_result,m.total_result
    FROM public.nba_historical_market_closes m
    ORDER BY m.commence_time_utc,m.game_id""")
   rows=cur.fetchall()
  if len(rows)!=2445: raise RuntimeError(f"Expected 2445 market rows; found {len(rows)}")
  output={"method":"Train calibration on 2024-25; evaluate once on held-out 2025-26","train_season":TRAIN_SEASON,"test_season":TEST_SEASON,"markets":{},"warning":"This benchmarks consensus closing probabilities, not the NBA AI model. No executable bookmaker prices for spread/totals are stored, so ROI is deliberately not calculated."}
  for name,meta in MARKETS.items():
   train=[]; test=[]
   for row in rows:
    season=row[0]
    if name=="moneyline": p,y,valid=row[1],row[4],True
    elif name=="spread": p,y,valid=row[2],row[5],row[6]!="push"
    else: p,y,valid=row[3],row[7],row[8]!="push"
    if not valid: continue
    item=(float(p),int(bool(y)))
    if season==TRAIN_SEASON: train.append(item)
    elif season==TEST_SEASON: test.append(item)
   if len(train)<1000 or len(test)<500: raise RuntimeError(f"Insufficient {name} sample: train={len(train)} test={len(test)}")
   params=fit_logistic_calibrator([x[0] for x in train],[x[1] for x in train])
   raw_ps=[x[0] for x in test]; ys=[x[1] for x in test]
   cal_ps=apply_calibrator(raw_ps,params)
   output["markets"][name]={"label":meta["label"],"train_n":len(train),"test_n":len(test),"calibrator":{k:round(v,6) for k,v in params.items()},"raw_market":metrics(raw_ps,ys),"calibrated_market":metrics(cal_ps,ys)}
  Path("v80_market_calibration_backtest.json").write_text(json.dumps(output,indent=2),encoding="utf-8")
  print(json.dumps(output,indent=2))
  print("PASS: 2025-26 held-out calibration benchmark completed")
 finally:
  conn.rollback()
  conn.close()
if __name__=="__main__":
 try: main()
 except Exception as exc:
  print(f"BACKTEST FAILED: {type(exc).__name__}: {exc}",file=sys.stderr); sys.exit(1)
