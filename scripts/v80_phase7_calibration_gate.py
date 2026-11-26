#!/usr/bin/env python3
"""Phase 7: probability calibration and release-risk assessment.

Fits a market-feature logistic model on TRAIN, fits a Platt calibrator on
VALIDATION predictions, and evaluates untouched TEST and FINAL_HOLDOUT.
No ROI claims: the source has no two-way prices, and source licensing is
unresolved. This is a research gate, not approval for live betting.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score,brier_score_loss,log_loss,roc_auc_score

INPUT=Path("artifacts/v80_phase6b/leak_safe_team_form_dataset.json")
OUT=Path("artifacts/v80_phase7")
NUM=["home_point","over_under","bookmaker_count","home_favorite",
 "home_prev_win_rate","home_prev_points_for_avg","home_prev_points_against_avg","home_prev_net_points_avg","home_prev_rest_days",
 "away_prev_win_rate","away_prev_points_for_avg","away_prev_points_against_avg","away_prev_net_points_avg","away_prev_rest_days",
 "pregame_net_form_diff","pregame_win_rate_diff","pregame_rest_diff"]
BASE_NUM=["home_point","over_under","bookmaker_count","home_favorite"]
CAT=["home_team","away_team"]
SPECS={"spread":("ats_result","HOME_COVER","AWAY_COVER"),
       "total":("total_result","OVER","UNDER")}

def build_model():
 return Pipeline([
  ("prep",ColumnTransformer([
   ("num",Pipeline([("impute",SimpleImputer(strategy="median")),("scale",StandardScaler())]),NUM),
   ("teams",OneHotEncoder(handle_unknown="ignore"),CAT)])),
  ("model",LogisticRegression(max_iter=1500,C=.5))
 ])

def logit(p):
 p=np.clip(np.asarray(p,dtype=float),1e-5,1-1e-5)
 return np.log(p/(1-p)).reshape(-1,1)

def score(y,p):
 y=np.asarray(y,dtype=int); p=np.clip(np.asarray(p,dtype=float),1e-6,1-1e-6)
 return {"n":int(len(y)),"accuracy":float(accuracy_score(y,p>=.5)),
  "brier":float(brier_score_loss(y,p)),"log_loss":float(log_loss(y,p,labels=[0,1])),
  "auc":float(roc_auc_score(y,p)) if len(np.unique(y))==2 else None,
  "base_rate":float(y.mean()),"mean_probability":float(p.mean()),
  "calibration_gap":float(p.mean()-y.mean())}

def reliability(y,p,bins=10):
 y=np.asarray(y,dtype=int); p=np.asarray(p,dtype=float)
 edges=np.linspace(0,1,bins+1); out=[]
 for i in range(bins):
  mask=(p>=edges[i]) & ((p<edges[i+1]) if i<bins-1 else (p<=edges[i+1]))
  if mask.any(): out.append({"bin_low":float(edges[i]),"bin_high":float(edges[i+1]),
   "n":int(mask.sum()),"mean_probability":float(p[mask].mean()),"observed_rate":float(y[mask].mean())})
 return out

def run_market(df,name):
 target,pos,neg=SPECS[name]
 d=df[df[target].isin([pos,neg])].copy(); d["y"]=(d[target]==pos).astype(int)
 parts={s:d[d.split==s].copy() for s in ["TRAIN","VALIDATION","TEST","FINAL_HOLDOUT"]}
 if any(len(parts[s])<100 for s in parts): raise RuntimeError(f"{name}: insufficient split sample")
 variants={"market_only":BASE_NUM+CAT,"market_plus_form":NUM+CAT}
 all_results={}
 for variant,cols in variants.items():
  model=Pipeline([
   ("prep",ColumnTransformer([
    ("num",Pipeline([("impute",SimpleImputer(strategy="median")),("scale",StandardScaler())]),cols[:len(cols)-len(CAT)]),
    ("teams",OneHotEncoder(handle_unknown="ignore"),CAT)])),
   ("model",LogisticRegression(max_iter=1500,C=.5))
  ])
  model.fit(parts["TRAIN"][cols],parts["TRAIN"].y)
  pv=model.predict_proba(parts["VALIDATION"][cols])[:,1]
  calibrator=LogisticRegression(C=1e6,max_iter=1000).fit(logit(pv),parts["VALIDATION"].y)
  split_results={}
  for split in ["VALIDATION","TEST","FINAL_HOLDOUT"]:
   part=parts[split]
   raw=model.predict_proba(part[cols])[:,1]
   cal=calibrator.predict_proba(logit(raw))[:,1]
   split_results[split]={"uncalibrated":score(part.y,raw),"platt_calibrated":score(part.y,cal),
    "uncalibrated_reliability":reliability(part.y,raw),
    "calibrated_reliability":reliability(part.y,cal)}
  all_results[variant]={"feature_columns":cols,"metrics":split_results}
 base=all_results["market_only"]["metrics"]
 extended=all_results["market_plus_form"]["metrics"]
 test_improved=extended["TEST"]["platt_calibrated"]["brier"] < base["TEST"]["platt_calibrated"]["brier"]
 hold_improved=extended["FINAL_HOLDOUT"]["platt_calibrated"]["brier"] < base["FINAL_HOLDOUT"]["platt_calibrated"]["brier"]
 auc_test=extended["TEST"]["platt_calibrated"]["auc"]
 adequate_discrimination=auc_test is not None and auc_test>=.52
 return {"models":all_results,
  "rows_by_split":{k:len(v) for k,v in parts.items()},
  "calibration_fit":"Each variant: Platt scaling fitted on VALIDATION predictions from TRAIN-only model",
  "form_features_improve_test_brier":bool(test_improved),
  "form_features_improve_final_holdout_brier":bool(hold_improved),
  "form_model_test_auc_at_least_0_52":bool(adequate_discrimination),
  "research_gate":"PASS" if test_improved and hold_improved and adequate_discrimination else "FAIL",
  "release_note":"A failed research gate means no probability display in production. Even a pass would not establish profitability without two-way prices and licensing clearance."}

def main():
 OUT.mkdir(parents=True,exist_ok=True)
 if not INPUT.exists(): raise RuntimeError("Missing Phase 5 benchmark dataset")
 obj=json.loads(INPUT.read_text(encoding="utf-8"))
 if obj.get("mode")!="LEAK_SAFE_ROLLING_TEAM_FORM_FEATURES" or not isinstance(obj.get("rows"),list) or not obj["rows"]: raise RuntimeError("Phase 6B feature dataset not accepted")
 df=pd.DataFrame(obj["rows"])
 if df.nba_game_id.duplicated().any(): raise RuntimeError("Duplicate NBA game IDs")
 markets={m:run_market(df,m) for m in SPECS}
 source_license="NOASSERTION — legal review required before persistent import or redistribution"
 license_clear=source_license=="CLEARED"
 all_pass=all(v["research_gate"]=="PASS" for v in markets.values())
 report={"phase":"V8.0_PHASE7","mode":"CALIBRATION_AND_RELEASE_RISK_ASSESSMENT",
  "markets":markets,"moneyline":{"status":"NOT_AVAILABLE","reason":"No audited moneyline odds/labels."},
  "roi":{"status":"NOT_CALCULABLE","reason":"No two-way prices."},
  "source_license":source_license,"source_license_cleared":False,
  "database_writes":0,
  "overall_research_gate":"PASS" if all_pass else "FAIL",
  "production_release_approved":False,
  "release_decision":"NOT_APPROVED — source licensing unresolved and independent review required",
  "limitations":["No two-way prices; ROI and vig-adjusted edge cannot be measured.",
   "Closing consensus lines are market information, not independent odds prices.",
   "One validation, one test, and one final holdout season.",
   "No injury, rest, player availability, or full box-score features in this benchmark.",
   "Source licence metadata is NOASSERTION; legal review required before persistent import or redistribution."]}
 (OUT/"calibration_release_risk_report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
 print(json.dumps(report,indent=2))
 print("RESULT: PHASE 7 CALIBRATION AND RELEASE-RISK ASSESSMENT COMPLETE")
if __name__=="__main__": main()
