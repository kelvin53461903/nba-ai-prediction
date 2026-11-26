#!/usr/bin/env python3
"""Phase 7C: CC-BY-4.0 closing-market probability plus rolling-form research."""
from __future__ import annotations
import csv,hashlib,io,json,re
from collections import defaultdict,deque
from datetime import datetime
from pathlib import Path
import requests,numpy as np,pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder,StandardScaler
from sklearn.metrics import accuracy_score,brier_score_loss,log_loss,roc_auc_score

OUT=Path("artifacts/v80_phase7c")
CROSSWALK=Path("artifacts/v80_phase4g/full_six_season_exact_score_crosswalk.json")
SOURCES={
 "2024-25":("minmaxxxer/nba-closing-lines-ats-2024-25","https://huggingface.co/datasets/minmaxxxer/nba-closing-lines-ats-2024-25/resolve/main/nba_2024_25_closing_lines_ats.csv"),
 "2025-26":("Cameronkelly92/nba-closing-lines-ats-2025-26","https://huggingface.co/datasets/Cameronkelly92/nba-closing-lines-ats-2025-26/resolve/main/nba_2025_26_closing_lines_ats.csv")}
REQUIRED={"game_id","start_time_utc","season","season_type","home_team","away_team","home_score","away_score","bookmakers","open_home_win_prob","close_home_win_prob","close_fair_home_odds","close_fair_away_odds","open_spread_home","close_spread_home","close_home_cover_prob","open_total","close_total","close_over_prob","moneyline_winner","ats_result","total_result"}
WINDOWS=(5,10,20)
MARKETS={
 "moneyline":("moneyline_winner","home","away","close_home_win_prob","close_fair_home_odds","open_home_win_prob"),
 "spread":("ats_result","home","away","close_home_cover_prob","close_spread_home","open_spread_home"),
 "totals":("total_result","over","under","close_over_prob","close_total","open_total")}
NUMERIC=["market_probability","market_line","open_market_line","bookmaker_count","home_elo","away_elo","elo_diff","home_rest_days","away_rest_days","rest_diff"]
for side in ("home","away"):
 for w in WINDOWS:
  NUMERIC += [f"{side}_prev{w}_{k}" for k in ("win_rate","points_for_avg","points_against_avg","net_points_avg")]
NUMERIC += [f"prev{w}_{k}_diff" for w in WINDOWS for k in ("win_rate","net_points_avg")]
CATEGORICAL=["home_team","away_team"]

def parse_utc(v):
 if not isinstance(v,str): raise ValueError("timestamp must be text")
 d=datetime.fromisoformat(v.replace("Z","+00:00"))
 if d.tzinfo is None or d.utcoffset() is None: raise ValueError("timezone required")
 return d

def norm_team(s):
 return re.sub(r"[^a-z]","",s.lower().replace("la ","los angeles ").replace("ny ","new york "))

def metrics(y,p):
 y=np.asarray(y,dtype=int); p=np.clip(np.asarray(p,dtype=float),1e-6,1-1e-6)
 return {"n":int(len(y)),"accuracy":float(accuracy_score(y,p>=.5)),
  "brier":float(brier_score_loss(y,p)),"log_loss":float(log_loss(y,p,labels=[0,1])),
  "auc":float(roc_auc_score(y,p)) if len(np.unique(y))==2 else None,
  "base_rate":float(y.mean()),"mean_probability":float(p.mean()),
  "calibration_gap":float(p.mean()-y.mean())}

def download_sources():
 out=[]; hashes={}
 for season,(dataset,url) in SOURCES.items():
  resp=requests.get(url,timeout=90,headers={"User-Agent":"NBA-AI-V8.0-Phase7C/1.0"}); resp.raise_for_status()
  raw=resp.content; hashes[season]=hashlib.sha256(raw).hexdigest()
  rows=list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
  if not rows or REQUIRED-set(rows[0]): raise RuntimeError(f"{season}: missing schema fields")
  for r in rows:
   if r["season"]!=season: raise RuntimeError(f"{season}: wrong season label")
   r["_season"]=season; r["_dataset"]=dataset; r["_url"]=url; r["_tip"]=parse_utc(r["start_time_utc"])
   for k in ("home_score","away_score","bookmakers"): r[k]=int(r[k])
   r["bookmaker_count"]=r["bookmakers"]
   for k in ("open_home_win_prob","close_home_win_prob","close_fair_home_odds","close_fair_away_odds","open_spread_home","close_spread_home","close_home_cover_prob","open_total","close_total","close_over_prob"): r[k]=float(r[k])
   r["_sha256"]=hashes[season]
  out.extend(rows)
 return out,hashes

def match_rows(rows,cross):
 if cross.get("mode")!="READ_ONLY_FULL_SIX_SEASON_EXACT_SCORE_CROSSWALK" or cross.get("scoreboard_query_failures"):
  raise RuntimeError("Six-season crosswalk failed")
 idx=defaultdict(list)
 for g in cross["resolved_rows"]:
  if g.get("status")!="EXACT_SCORE_AND_SOURCE_ID_PRESENT": continue
  try: dt=parse_utc(g["espn_utc_date"])
  except Exception: continue
  idx[(dt.date().isoformat(),norm_team(g["home"]),norm_team(g["away"]),int(g["score"][0]),int(g["score"][1]))].append(g)
 accepted=[]
 for r in rows:
  k=(r["_tip"].date().isoformat(),norm_team(r["home_team"]),norm_team(r["away_team"]),r["home_score"],r["away_score"])
  m=idx.get(k,[])
  if len(m)!=1 or m[0]["season"]!=r["_season"]: continue
  if not all(0<float(r[x])<1 for x in ("close_home_win_prob","close_home_cover_prob","close_over_prob")): continue
  if r["close_fair_home_odds"]<=1 or r["close_fair_away_odds"]<=1 or r["bookmakers"]<1: continue
  if r["moneyline_winner"] not in ("home","away") or r["ats_result"] not in ("home","away","push") or r["total_result"] not in ("over","under","push"): continue
  r["nba_game_id"]=m[0]["nba_game_id"]; accepted.append(r)
 if len(accepted)<2200 or len({r["nba_game_id"] for r in accepted})!=len(accepted):
  raise RuntimeError(f"Exact score crosswalk coverage failed: {len(accepted)} rows")
 return accepted

def build_features(rows,cross):
 hist=defaultdict(lambda:deque(maxlen=20)); elo=defaultdict(lambda:1500.0)
 games=defaultdict(list); markets=defaultdict(list)
 for g in cross["resolved_rows"]:
  if g.get("status")=="EXACT_SCORE_AND_SOURCE_ID_PRESENT": games[g["espn_utc_date"][:10]].append(g)
 for r in rows: markets[r["_tip"].date().isoformat()].append(r)
 out=[]
 for day in sorted(set(games)|set(markets)):
  for r in markets.get(day,[]):
   h,a=r["home_team"],r["away_team"]
   def f(team):
    q=list(hist[team]); z={"elo":elo[team],"rest":(parse_utc(r["start_time_utc"]).date()-datetime.fromisoformat(q[-1]["date"]).date()).days if q else np.nan}
    for w in WINDOWS:
     v=q[-w:]
     for key,values in (("win_rate",[x["win"] for x in v]),("points_for_avg",[x["pf"] for x in v]),("points_against_avg",[x["pa"] for x in v]),("net_points_avg",[x["pf"]-x["pa"] for x in v])):
      z[f"prev{w}_{key}"]=float(np.mean(values)) if values else np.nan
    return z
   hf,af=f(h),f(a); x=dict(r)
   x.update({"home_elo":hf["elo"],"away_elo":af["elo"],"elo_diff":hf["elo"]-af["elo"],"home_rest_days":hf["rest"],"away_rest_days":af["rest"],"rest_diff":hf["rest"]-af["rest"] if np.isfinite(hf["rest"]) and np.isfinite(af["rest"]) else np.nan})
   for w in WINDOWS:
    for key in ("win_rate","points_for_avg","points_against_avg","net_points_avg"):
     x[f"home_prev{w}_{key}"]=hf[f"prev{w}_{key}"]; x[f"away_prev{w}_{key}"]=af[f"prev{w}_{key}"]
    for key in ("win_rate","net_points_avg"):
     hv,av=hf[f"prev{w}_{key}"],af[f"prev{w}_{key}"]
     x[f"prev{w}_{key}_diff"]=hv-av if np.isfinite(hv) and np.isfinite(av) else np.nan
   out.append(x)
  # No game result from this UTC date enters another game on the same date.
  updates=[]
  for g in games.get(day,[]):
   h,a=g["home"],g["away"]; hs,as_=map(int,g["score"]); margin=hs-as_
   hist[h].append({"date":day,"pf":hs,"pa":as_,"win":1.0 if margin>0 else 0.0})
   hist[a].append({"date":day,"pf":as_,"pa":hs,"win":1.0 if margin<0 else 0.0})
   eh,ea=elo[h],elo[a]; exp=1/(1+10**((ea-(eh+65.0))/400.0)); act=1.0 if margin>0 else 0.0
   updates.append((h,a,eh+20*(act-exp),ea-20*(act-exp)))
  for h,a,eh,ea in updates: elo[h]=eh; elo[a]=ea
 return out

def assign_splits(rows):
 by=defaultdict(list)
 for r in rows: by[r["_season"]].append(r)
 for s in by: by[s].sort(key=lambda x:x["_tip"])
 a,b=by.get("2024-25",[]),by.get("2025-26",[])
 if len(a)<1000 or len(b)<900: raise RuntimeError("Insufficient season coverage")
 def cuts(items,fractions):
  counts=defaultdict(int)
  for r in items: counts[r["_tip"].date().isoformat()]+=1
  dates=sorted(counts); n=len(items); boundaries=[]
  for frac in fractions:
   target=n*frac; cum=0; cut=len(dates)
   for i,day in enumerate(dates):
    cum+=counts[day]
    if cum>=target:
     cut=i+1; break
   boundaries.append(cut)
  return dates,boundaries
 da,(i,j)=cuts(a,[.70,.85]); db,(k,)=cuts(b,[.50])
 train,cal,val=set(da[:i]),set(da[i:j]),set(da[j:])
 test,hold=set(db[:k]),set(db[k:])
 for r in rows:
  day=r["_tip"].date().isoformat()
  r["split"]="TRAIN" if day in train else "CALIBRATION" if day in cal else "VALIDATION" if day in val else "TEST" if day in test else "FINAL_HOLDOUT" if day in hold else "EXCLUDED"
 return rows,{"2024-25":{"TRAIN_games":sum(r["_tip"].date().isoformat() in train for r in a),"CALIBRATION_games":sum(r["_tip"].date().isoformat() in cal for r in a),"VALIDATION_games":sum(r["_tip"].date().isoformat() in val for r in a)},"2025-26":{"TEST_games":sum(r["_tip"].date().isoformat() in test for r in b),"FINAL_HOLDOUT_games":sum(r["_tip"].date().isoformat() in hold for r in b)}}

def logistic():
 return Pipeline([("prep",ColumnTransformer([
  ("num",Pipeline([("impute",SimpleImputer(strategy="median",keep_empty_features=True)),("scale",StandardScaler())]),NUMERIC),
  ("teams",OneHotEncoder(handle_unknown="ignore"),CATEGORICAL)])),
  ("model",LogisticRegression(max_iter=2000,C=.25))])

def hist():
 return Pipeline([("prep",ColumnTransformer([("num",SimpleImputer(strategy="median",keep_empty_features=True),NUMERIC)])),
  ("model",HistGradientBoostingClassifier(max_iter=160,max_leaf_nodes=12,l2_regularization=12,learning_rate=.03,random_state=42))])

def run_market(df,name):
 target,pos,neg,prob,line,openline=MARKETS[name]
 d=df[df[target].isin([pos,neg])].copy(); d["y"]=(d[target]==pos).astype(int)
 d["market_probability"]=d[prob].astype(float)
 d["market_line"]=d[line].astype(float)
 d["open_market_line"]=d[openline].astype(float)
 parts={s:d[d.split==s].copy() for s in ("TRAIN","CALIBRATION","VALIDATION","TEST","FINAL_HOLDOUT")}
 if any(len(parts[s])<75 for s in parts): raise RuntimeError(f"{name}: insufficient split sizes { {k:len(v) for k,v in parts.items()} }")
 xcols=NUMERIC+CATEGORICAL; results={}
 for name2,model in (("market_plus_rolling_logistic",logistic()),("market_plus_rolling_hist_gradient_boosting",hist())):
  model.fit(parts["TRAIN"][xcols],parts["TRAIN"].y)
  pcal=np.clip(model.predict_proba(parts["CALIBRATION"][xcols])[:,1],1e-5,1-1e-5)
  calx=np.log(pcal/(1-pcal)).reshape(-1,1)
  calibrator=LogisticRegression(C=1e6,max_iter=1000).fit(calx,parts["CALIBRATION"].y)
  entry={"splits":{}}
  for split in ("CALIBRATION","VALIDATION","TEST","FINAL_HOLDOUT"):
   raw=np.clip(model.predict_proba(parts[split][xcols])[:,1],1e-5,1-1e-5)
   calibrated=calibrator.predict_proba(np.log(raw/(1-raw)).reshape(-1,1))[:,1]
   entry["splits"][split]={"uncalibrated":metrics(parts[split].y,raw),"calibrated":metrics(parts[split].y,calibrated)}
  results[name2]=entry
 baseline={s:metrics(parts[s].y,parts[s].market_probability) for s in ("VALIDATION","TEST","FINAL_HOLDOUT")}
 chosen=min(results,key=lambda n:results[n]["splits"]["VALIDATION"]["calibrated"]["brier"])
 test=results[chosen]["splits"]["TEST"]["calibrated"]; hold=results[chosen]["splits"]["FINAL_HOLDOUT"]["calibrated"]
 gate=(test["brier"]<baseline["TEST"]["brier"] and hold["brier"]<baseline["FINAL_HOLDOUT"]["brier"]
  and test["auc"] is not None and test["auc"]>=.52 and hold["auc"] is not None and hold["auc"]>=.52
  and abs(test["calibration_gap"])<=.03 and abs(hold["calibration_gap"])<=.03)
 return {"rows_by_split":{s:len(parts[s]) for s in parts},"market_baseline":baseline,"candidate_results":results,"selected_model":chosen,
  "advanced_beats_market_test_brier":test["brier"]<baseline["TEST"]["brier"],
  "advanced_beats_market_holdout_brier":hold["brier"]<baseline["FINAL_HOLDOUT"]["brier"],
  "test_auc_at_least_0_52":test["auc"] is not None and test["auc"]>=.52,
  "holdout_auc_at_least_0_52":hold["auc"] is not None and hold["auc"]>=.52,
  "research_gate":"PASS" if gate else "FAIL"}

def main():
 OUT.mkdir(parents=True,exist_ok=True)
 if not CROSSWALK.exists(): raise RuntimeError("Missing six-season crosswalk artifact")
 cross=json.loads(CROSSWALK.read_text(encoding="utf-8"))
 raw,hashes=download_sources(); matched=match_rows(raw,cross)
 featured=build_features(matched,cross); featured,splits=assign_splits(featured)
 df=pd.DataFrame(featured)
 if df.nba_game_id.duplicated().any(): raise RuntimeError("Duplicate NBA game ID")
 results={m:run_market(df,m) for m in MARKETS}
 report={"phase":"V8.0_PHASE7C","mode":"CC_BY_4_MARKET_PROBABILITY_PLUS_ROLLING_FEATURE_RESEARCH",
  "dataset_rows":len(df),"source_sha256":hashes,"split_date_counts":splits,"markets":results,
  "source_license":"CC-BY-4.0; attribution required","roi":{"status":"NOT_CALCULABLE","reason":"Fair probabilities/odds are not executable bookmaker prices; spread and totals two-way prices absent."},
  "clv":{"status":"NOT_CALCULABLE","reason":"No timestamped two-way opening/closing prices."},
  "database_writes":0,"paid_api_calls":0,"overall_research_gate":"PASS" if all(x["research_gate"]=="PASS" for x in results.values()) else "FAIL",
  "production_release_approved":False,"limitations":["Only two seasons of market probabilities.","No player/injury features.","Closing probabilities are market benchmarks, not guaranteed executable odds.","No future profit guarantee."]}
 (OUT/"ccby_market_model_report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
 print(json.dumps(report,indent=2)); print("RESULT: PHASE 7C MARKET MODEL RESEARCH COMPLETE")
if __name__=="__main__": main()
