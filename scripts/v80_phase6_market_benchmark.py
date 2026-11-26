#!/usr/bin/env python3
"""Phase 6: chronological spread/total model benchmark.

Consumes the ephemeral Phase 5 artifact. No production DB writes. No Moneyline
model is attempted because the audited source has no moneyline prices.
Models use only pregame consensus closing lines and team identities.
Pushes are excluded from binary settlement metrics and reported separately.
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
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score

ROOT=Path(__file__).resolve().parents[1]
INPUT=Path("artifacts/v80_phase5/market_benchmark_dataset.json")
OUT=Path("artifacts/v80_phase6")
NUMERIC=["home_point","over_under","bookmaker_count","home_favorite"]
CATEGORICAL=["home_team","away_team"]
MARKETS={
 "spread":{"target":"ats_result","positive":"HOME_COVER","push":"PUSH"},
 "total":{"target":"total_result","positive":"OVER","push":"PUSH"},
}

def build_models():
 logistic=Pipeline([
  ("prep",ColumnTransformer([
   ("num",Pipeline([("impute",SimpleImputer(strategy="median")),("scale",StandardScaler())]),NUMERIC),
   ("teams",OneHotEncoder(handle_unknown="ignore"),CATEGORICAL),
  ])),
  ("model",LogisticRegression(max_iter=1000,C=0.5,class_weight=None))
 ])
 hist=Pipeline([
  ("prep",ColumnTransformer([
   ("num",SimpleImputer(strategy="median"),NUMERIC),
  ],remainder="drop")),
  ("model",HistGradientBoostingClassifier(max_iter=120,max_leaf_nodes=15,l2_regularization=5,learning_rate=.05,random_state=42))
 ])
 return {"logistic_market_features":logistic,"hist_gradient_boosting_numeric":hist}

def metrics(y,p):
 p=np.clip(np.asarray(p,dtype=float),1e-6,1-1e-6)
 y=np.asarray(y,dtype=int)
 return {"n":int(len(y)),"accuracy":float(accuracy_score(y,p>=.5)),
  "brier":float(brier_score_loss(y,p)),"log_loss":float(log_loss(y,p,labels=[0,1])),
  "auc":float(roc_auc_score(y,p)) if len(np.unique(y))==2 else None,
  "positive_rate":float(y.mean()),"prediction_mean":float(p.mean())}

def run_market(df,market):
 spec=MARKETS[market]; target=spec["target"]
 d=df[df[target].isin([spec["positive"],"AWAY_COVER" if market=="spread" else "UNDER"])].copy()
 d["y"]=(d[target]==spec["positive"]).astype(int)
 splits={s:d[d["split"]==s].copy() for s in ["TRAIN","VALIDATION","TEST","FINAL_HOLDOUT"]}
 if any(len(splits[s])<100 for s in splits):
  raise RuntimeError(f"{market}: insufficient non-push rows by split: "+str({k:len(v) for k,v in splits.items()}))
 Xcols=NUMERIC+CATEGORICAL
 train=splits["TRAIN"]; val=splits["VALIDATION"]; test=splits["TEST"]; hold=splits["FINAL_HOLDOUT"]
 candidates={}
 for name,model in build_models().items():
  model.fit(train[Xcols],train["y"])
  pv=model.predict_proba(val[Xcols])[:,1]
  candidates[name]={"validation":metrics(val["y"],pv),"model":model}
 chosen=min(candidates,key=lambda n:candidates[n]["validation"]["brier"])
 model=build_models()[chosen]
 trainval=pd.concat([train,val],ignore_index=True)
 model.fit(trainval[Xcols],trainval["y"])
 ptest=model.predict_proba(test[Xcols])[:,1]
 phold=model.predict_proba(hold[Xcols])[:,1]
 return {
  "chosen_model":chosen,
  "rows_by_split":{k:len(v) for k,v in splits.items()},
  "pushes_by_split":{s:int((df[df["split"]==s][target]=="PUSH").sum()) for s in ["TRAIN","VALIDATION","TEST","FINAL_HOLDOUT"]},
  "candidate_validation":{n:v["validation"] for n,v in candidates.items()},
  "test":metrics(test["y"],ptest),
  "final_holdout":metrics(hold["y"],phold),
  "feature_columns":Xcols,
  "limitations":["No two-way odds; ROI is not calculable.",
   "Closing consensus line is a pregame market feature, not an independent bookmaker price.",
   "Only 2024-25 is the test season and 2025-26 is the final holdout season.",
   "These results are historical research, not evidence of future betting profit."]
 }

def main():
 OUT.mkdir(parents=True,exist_ok=True)
 if not INPUT.exists(): raise RuntimeError("Missing Phase 5 dataset artifact")
 obj=json.loads(INPUT.read_text(encoding="utf-8"))
 report=obj.get("report",{}); rows=obj.get("rows")
 if report.get("acceptance")!="DATASET_CANDIDATE_FOR_BENCHMARK_ONLY" or not isinstance(rows,list) or not rows:
  raise RuntimeError("Phase 5 dataset not accepted or empty")
 df=pd.DataFrame(rows)
 if df["nba_game_id"].duplicated().any(): raise RuntimeError("Duplicate NBA game IDs")
 if not set(df["split"].unique()).issubset({"TRAIN","VALIDATION","TEST","FINAL_HOLDOUT"}):
  raise RuntimeError("Unexpected split label")
 if df["commence_time_utc"].is_monotonic_increasing is False:
  raise RuntimeError("Dataset is not chronologically sorted")
 results={m:run_market(df,m) for m in ("spread","total")}
 out={"phase":"V8.0_PHASE6","mode":"CHRONOLOGICAL_MARKET_FEATURE_BENCHMARK",
  "dataset_rows":len(df),"date_range":[str(df["game_date"].min()),str(df["game_date"].max())],
  "split_seasons":report.get("splits"),"markets":results,
  "moneyline":{"status":"NOT_AVAILABLE","reason":"No audited moneyline prices/labels in the source dataset."},
  "roi":{"status":"NOT_CALCULABLE","reason":"No two-way prices or vig-adjusted settlement."},
  "source_license":report.get("source_license"),
  "database_writes":0,
  "acceptance":"RESEARCH_METRICS_ONLY; Phase 7 calibration and independent review required"}
 (OUT/"chronological_market_model_benchmark.json").write_text(json.dumps(out,indent=2),encoding="utf-8")
 print(json.dumps(out,indent=2))
 print("RESULT: PHASE 6 CHRONOLOGICAL MARKET BENCHMARK COMPLETE")
if __name__=="__main__": main()
