#!/usr/bin/env python3
"""Phase 10.6 retrospective research model for NBA three-market probabilities.

Uses only pregame team-form features plus historical OPEN market fields as
predictors. Closing consensus probabilities are benchmarks, never predictors.
The source has no per-quote timestamps, so results are research-only and are
not verified as executable or point-in-time predictions.
"""
from __future__ import annotations
import argparse, csv, json, math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

MARKETS = ("moneyline", "spread", "total")
EPS = 1e-12

def number(row, key):
    value = row.get(key)
    if value in (None, ""):
        raise ValueError(f"missing numeric field: {key}")
    x = float(value)
    if not math.isfinite(x):
        raise ValueError(f"non-finite numeric field: {key}")
    return x

def game_date(row):
    value = row.get("commence_time_utc")
    if not value:
        raise ValueError("missing commence_time_utc")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("commence_time_utc must include timezone")
    return dt.date().isoformat()

def logit(p):
    p = min(1-EPS, max(EPS, p))
    return math.log(p/(1-p))

def sigmoid(z):
    z = max(-30.0, min(30.0, z))
    return 1.0/(1.0+math.exp(-z))

def label_for(row, market):
    if market == "moneyline":
        return int(number(row, "actual_home_win"))
    if market == "spread":
        value = row.get("ats_result", "").strip().lower()
        return 1 if value == "home" else 0 if value == "away" else None
    value = row.get("total_result", "").strip().lower()
    return 1 if value == "over" else 0 if value == "under" else None

def market_probability(row, market):
    key = {"moneyline":"close_home_win_prob",
           "spread":"close_home_cover_prob",
           "total":"close_over_prob"}[market]
    return number(row, key)

def features(row, market):
    h5,a5 = number(row,"home_win_pct_last5"),number(row,"away_win_pct_last5")
    h10,a10 = number(row,"home_win_pct_last10"),number(row,"away_win_pct_last10")
    hpf5,apf5 = number(row,"home_avg_points_for_last5"),number(row,"away_avg_points_for_last5")
    hpa5,apa5 = number(row,"home_avg_points_against_last5"),number(row,"away_avg_points_against_last5")
    hpf10,apf10 = number(row,"home_avg_points_for_last10"),number(row,"away_avg_points_for_last10")
    hpa10,apa10 = number(row,"home_avg_points_against_last10"),number(row,"away_avg_points_against_last10")
    rest_diff = (number(row,"home_rest_days")-number(row,"away_rest_days"))/3.0
    if market == "moneyline":
        return [h5-a5,h10-a10,((hpf5-hpa5)-(apf5-apa5))/10.0,
                ((hpf10-hpa10)-(apf10-apa10))/10.0,rest_diff,
                logit(number(row,"open_home_win_prob"))]
    if market == "spread":
        return [h5-a5,h10-a10,((hpf5-hpa5)-(apf5-apa5))/10.0,
                ((hpf10-hpa10)-(apf10-apa10))/10.0,rest_diff,
                number(row,"open_spread_home")/10.0]
    return [(hpf5+apf5-220.0)/10.0,(hpa5+apa5-220.0)/10.0,
            (hpf10+apf10-220.0)/10.0,(hpa10+apa10-220.0)/10.0,
            (number(row,"open_total")-220.0)/10.0]

def prepare(rows, market):
    result = []
    for row in rows:
        y = label_for(row, market)
        if y is None:  # pushes are excluded from binary market scoring
            continue
        p = market_probability(row, market)
        if not 0 < p < 1:
            raise ValueError(f"market probability outside (0,1): {row.get('game_id')}")
        result.append({"game_id":str(row["game_id"]), "season":row["season"],
                       "date":game_date(row), "x":features(row,market),
                       "y":y, "market":p})
    return result

def fit_logistic(rows, steps=3000, learning_rate=0.03, l2=0.02):
    if not rows:
        raise ValueError("empty training set")
    width = len(rows[0]["x"])
    means = [sum(r["x"][j] for r in rows)/len(rows) for j in range(width)]
    scales = []
    for j in range(width):
        variance = sum((r["x"][j]-means[j])**2 for r in rows)/len(rows)
        scales.append(math.sqrt(variance) or 1.0)
    matrix = [[1.0]+[(v-means[j])/scales[j] for j,v in enumerate(r["x"])] for r in rows]
    beta = [0.0]*(width+1)
    for _ in range(steps):
        grad = [0.0]*(width+1)
        for r,x in zip(rows,matrix):
            error = sigmoid(sum(b*v for b,v in zip(beta,x)))-r["y"]
            for j,v in enumerate(x):
                grad[j] += error*v
        for j in range(width+1):
            grad[j] /= len(rows)
            if j:
                grad[j] += l2*beta[j]
            beta[j] -= learning_rate*grad[j]
    def predict(row):
        z = beta[0]+sum(beta[j+1]*(v-means[j])/scales[j] for j,v in enumerate(row["x"]))
        return sigmoid(z)
    return predict

def fit_platt(rows, raw_predict, steps=3000, learning_rate=0.02):
    if not rows:
        raise ValueError("empty calibration set")
    a,b = 0.0,1.0
    for _ in range(steps):
        ga=gb=0.0
        for row in rows:
            z=logit(raw_predict(row))
            error=sigmoid(a+b*z)-row["y"]
            ga += error
            gb += error*z
        a -= learning_rate*ga/len(rows)
        b -= learning_rate*gb/len(rows)
    return lambda p: sigmoid(a+b*logit(p))

def metrics(rows, key):
    n=len(rows)
    if not n:
        return {"n":0,"brier":None,"log_loss":None,"auc":None}
    brier=sum((r[key]-r["y"])**2 for r in rows)/n
    ll=-sum(r["y"]*math.log(max(EPS,r[key]))+(1-r["y"])*math.log(max(EPS,1-r[key])) for r in rows)/n
    positive=[r for r in rows if r["y"]==1]
    negative=[r for r in rows if r["y"]==0]
    auc=None
    if positive and negative:
        wins=0.0
        for p in positive:
            for q in negative:
                wins += 1.0 if p[key]>q[key] else 0.5 if p[key]==q[key] else 0.0
        auc=wins/(len(positive)*len(negative))
    return {"n":n,"brier":round(brier,6),"log_loss":round(ll,6),
            "auc":None if auc is None else round(auc,4)}

def run(input_csv, output_csv, report_json):
    with open(input_csv,newline="",encoding="utf-8-sig") as f:
        source=list(csv.DictReader(f))
    if not source:
        raise RuntimeError("empty input CSV")
    seasons={r.get("season") for r in source}
    if not {"2024-25","2025-26"}.issubset(seasons):
        raise RuntimeError("expected 2024-25 development and 2025-26 holdout seasons")
    report={"input_rows":len(source),"prediction_type":"retrospective_reconstruction",
            "opening_quote_timestamp_verified":False,
            "closing_market_used_as_predictor":False,
            "split_method":"70% of distinct 2024-25 game dates train; later 30% calibrate; 2025-26 chronological season holdout",
            "markets":{},"roi":"NOT_CALCULATED","clv":"NOT_CALCULATED",
            "release_status":"RESEARCH_ONLY"}
    prediction_rows=[]
    for market in MARKETS:
        data=prepare(source,market)
        development=[r for r in data if r["season"]=="2024-25"]
        holdout=[r for r in data if r["season"]=="2025-26"]
        dates=sorted({r["date"] for r in development})
        if len(dates)<10 or not holdout:
            raise RuntimeError(f"insufficient chronological data for {market}")
        cut=max(1,min(len(dates)-1,math.ceil(len(dates)*0.70)))
        train_end=dates[cut-1]
        train=[r for r in development if r["date"]<=train_end]
        calibration=[r for r in development if r["date"]>train_end]
        raw_predict=fit_logistic(train)
        platt=fit_platt(calibration,raw_predict)
        scored=[]
        for row in holdout:
            raw=raw_predict(row)
            scored.append({**row,"raw":raw,"calibrated":platt(raw)})
            prediction_rows.append({"game_id":row["game_id"],"season":row["season"],
              "game_date":row["date"],"market":market,"outcome":row["y"],
              "raw_probability":f"{raw:.10f}","calibrated_probability":f"{platt(raw):.10f}",
              "market_close_probability":f"{row['market']:.10f}",
              "prediction_type":"retrospective_reconstruction",
              "opening_quote_timestamp_verified":"false"})
        raw_metrics=metrics(scored,"raw")
        calibrated_metrics=metrics(scored,"calibrated")
        market_metrics=metrics(scored,"market")
        report["markets"][market]={
          "train_n":len(train),"calibration_n":len(calibration),"holdout_n":len(scored),
          "train_end_date":train_end,"calibration_start_date":dates[cut],
          "holdout_start_date":min(r["date"] for r in holdout),
          "holdout_end_date":max(r["date"] for r in holdout),
          "raw_model":raw_metrics,"calibrated_model":calibrated_metrics,
          "closing_market":market_metrics,
          "calibrated_brier_delta_model_minus_market":round(calibrated_metrics["brier"]-market_metrics["brier"],6),
          "calibrated_log_loss_delta_model_minus_market":round(calibrated_metrics["log_loss"]-market_metrics["log_loss"],6)}
    Path(output_csv).parent.mkdir(parents=True,exist_ok=True)
    with open(output_csv,"w",newline="",encoding="utf-8") as f:
        writer=csv.DictWriter(f,fieldnames=list(prediction_rows[0]))
        writer.writeheader(); writer.writerows(prediction_rows)
    Path(report_json).parent.mkdir(parents=True,exist_ok=True)
    Path(report_json).write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))
    return report

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--input",required=True)
    p.add_argument("--predictions",required=True)
    p.add_argument("--report",required=True)
    a=p.parse_args()
    run(a.input,a.predictions,a.report)
