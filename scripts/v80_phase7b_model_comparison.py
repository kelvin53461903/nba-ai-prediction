#!/usr/bin/env python3
"""Phase 7B: compare market baseline with leak-safe form/ATS/total/Elo models.

Candidate selection uses VALIDATION only. Calibration is fitted on validation
predictions from TRAIN-only models. TEST and FINAL_HOLDOUT are never used for
model selection or calibration. This remains research-only, not a betting ROI test.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder,StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import accuracy_score,brier_score_loss,log_loss,roc_auc_score

INPUT=Path("artifacts/v80_phase6c/rolling_market_elo_features.json")
OUT=Path("artifacts/v80_phase7b")
BASE_NUM=["home_point","over_under","bookmaker_count","home_favorite"]
CAT=["home_team","away_team"]
ROLL=[]
for side in ("home","away"):
 ROLL += [side+"_elo",side+"_rest_days"]
 for w in (5,10,20):
  ROLL += [side+f"_prev{w}_"+k for k in ("win_rate","points_for_avg","points_against_avg","net_points_avg","ats_cover_rate","ats_margin_avg","over_rate","total_residual_avg")]
DIFF=["pregame_elo_diff","pregame_rest_days_diff"]
for w in (5,10,20):
 DIFF += [f"pregame_prev{w}_{k}_diff" for k in ("win_rate","net_points_avg","ats_cover_rate","ats_margin_avg","over_rate","total_residual_avg")]
NUM=BASE_NUM+ROLL+DIFF
SPECS={"spread":("ats_result","HOME_COVER","AWAY_COVER"),
       "total":("total_result","OVER","UNDER")}

def logit(p):
 p=np.clip(np.asarray(p,dtype=float),1e-5,1-1e-5)
 return np.log(p/(1-p)).reshape(-1,1)

def metrics(y,p):
 y=np.asarray(y,dtype=int); p=np.clip(np.asarray(p,dtype=float),1e-6,1-1e-6)
 return {"n":int(len(y)),"accuracy":float(accuracy_score(y,p>=.5)),
  "brier":float(brier_score_loss(y,p)),"log_loss":float(log_loss(y,p,labels=[0,1])),
  "auc":float(roc_auc_score(y,p)) if len(np.unique(y))==2 else None,
  "base_rate":float(y.mean()),"mean_probability":float(p.mean()),
  "calibration_gap":float(p.mean()-y.mean())}

def build_logistic(num_cols,cat_cols):
 return Pipeline([
  ("prep",ColumnTransformer([
   ("num",Pipeline([("impute",SimpleImputer(strategy="median",keep_empty_features=True)),("scale",StandardScaler())]),num_cols),
   ("teams",OneHotEncoder(handle_unknown="ignore"),cat_cols)])),
  ("model",LogisticRegression(max_iter=2000,C=.5))
 ])

def build_hist():
 return Pipeline([
  ("prep",ColumnTransformer([
   ("num",SimpleImputer(strategy="median",keep_empty_features=True),NUM)])),
  ("model",HistGradientBoostingClassifier(max_iter=160,max_leaf_nodes=15,l2_regularization=8,learning_rate=.04,random_state=42))
 ])

def evaluate_candidate(model,cols,parts):
 train,val=parts["TRAIN"],parts["VALIDATION"]
 model.fit(train[cols],train.y)
 pv=model.predict_proba(val[cols])[:,1]
 calibrator=LogisticRegression(C=1e6,max_iter=1000).fit(logit(pv),val.y)
 result={"validation_uncalibrated":metrics(val.y,pv),
         "validation_calibrated":metrics(val.y,calibrator.predict_proba(logit(pv))[:,1]),
         "splits":{}}
 for split in ("TEST","FINAL_HOLDOUT"):
  part=parts[split]; raw=model.predict_proba(part[cols])[:,1]
  cal=calibrator.predict_proba(logit(raw))[:,1]
  result["splits"][split]={"uncalibrated":metrics(part.y,raw),"platt_calibrated":metrics(part.y,cal)}
 return result

def run_market(df,name):
 target,pos,neg=SPECS[name]
 d=df[df[target].isin([pos,neg])].copy(); d["y"]=(d[target]==pos).astype(int)
 parts={s:d[d.split==s].copy() for s in ("TRAIN","VALIDATION","TEST","FINAL_HOLDOUT")}
 if any(len(parts[s])<100 for s in parts): raise RuntimeError(f"{name}: insufficient split sizes")
 candidates={
  "market_only_logistic":(build_logistic(BASE_NUM,CAT),BASE_NUM+CAT),
  "rolling_features_logistic":(build_logistic(NUM,CAT),NUM+CAT),
  "rolling_features_hist_gradient_boosting":(build_hist(),NUM)
 }
 results={}
 for name2,(model,cols) in candidates.items():
  results[name2]=evaluate_candidate(model,cols,parts)
 baseline=results["market_only_logistic"]
 advanced_names=list(candidates.keys())[1:]
 chosen=min(advanced_names,key=lambda n:results[n]["validation_calibrated"]["brier"])
 chosen_result=results[chosen]
 test_base=baseline["splits"]["TEST"]["platt_calibrated"]
 test_adv=chosen_result["splits"]["TEST"]["platt_calibrated"]
 hold_base=baseline["splits"]["FINAL_HOLDOUT"]["platt_calibrated"]
 hold_adv=chosen_result["splits"]["FINAL_HOLDOUT"]["platt_calibrated"]
 test_brier= test_adv["brier"] < test_base["brier"]
 hold_brier= hold_adv["brier"] < hold_base["brier"]
 auc_test=test_adv["auc"] is not None and test_adv["auc"]>=.52
 auc_hold=hold_adv["auc"] is not None and hold_adv["auc"]>=.52
 return {"rows_by_split":{s:len(v) for s,v in parts.items()},
  "candidate_results":results,"selected_advanced_model":chosen,
  "selected_by":"lowest Platt-calibrated VALIDATION Brier among advanced models",
  "advanced_model_beats_baseline_test_brier":bool(test_brier),
  "advanced_model_beats_baseline_holdout_brier":bool(hold_brier),
  "advanced_model_test_auc_at_least_0_52":bool(auc_test),
  "advanced_model_holdout_auc_at_least_0_52":bool(auc_hold),
  "research_gate":"PASS" if test_brier and hold_brier and auc_test and auc_hold else "FAIL"}

def main():
 OUT.mkdir(parents=True,exist_ok=True)
 if not INPUT.exists(): raise RuntimeError("Missing Phase 6C features")
 obj=json.loads(INPUT.read_text(encoding="utf-8"))
 if obj.get("mode")!="LEAK_SAFE_ROLLING_MARKET_RESIDUAL_AND_ELO" or len(obj.get("rows",[]))!=7577:
  raise RuntimeError("Phase 6C dataset failed validation")
 df=pd.DataFrame(obj["rows"])
 if df.nba_game_id.duplicated().any(): raise RuntimeError("Duplicate game IDs")
 if not set(NUM).issubset(df.columns): raise RuntimeError("Missing engineered features: "+str(sorted(set(NUM)-set(df.columns))))
 markets={m:run_market(df,m) for m in SPECS}
 all_pass=all(v["research_gate"]=="PASS" for v in markets.values())
 report={"phase":"V8.0_PHASE7B","mode":"MARKET_BASELINE_VS_ROLLING_FORM_ATS_TOTAL_ELO_COMPARISON",
  "dataset_rows":len(df),"split_seasons":{"TRAIN":["2020-21","2021-22","2022-23"],"VALIDATION":["2023-24"],"TEST":["2024-25"],"FINAL_HOLDOUT":["2025-26"]},
  "markets":markets,"moneyline":{"status":"NOT_AVAILABLE","reason":"No audited moneyline prices in this consensus-line dataset."},
  "roi":{"status":"NOT_CALCULABLE","reason":"No two-way prices."},
  "source_license":"NOASSERTION — legal review required before persistent import or redistribution",
  "source_license_cleared":False,"database_writes":0,
  "overall_research_gate":"PASS" if all_pass else "FAIL",
  "production_release_approved":False,
  "release_decision":"NOT_APPROVED — independent review, prices and source licensing remain outstanding",
  "limitations":["No player injury/availability or player-level data.",
   "One season each for validation, test and final holdout.",
   "No two-way prices, vig-adjusted ROI or CLV.",
   "No future profitability guarantee."]}
 (OUT/"market_baseline_vs_rolling_form_report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
 print(json.dumps(report,indent=2))
 print("RESULT: PHASE 7B MODEL COMPARISON COMPLETE")
if __name__=="__main__": main()
