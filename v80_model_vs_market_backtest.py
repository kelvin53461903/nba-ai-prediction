#!/usr/bin/env python3
"""Same-game, season-held-out comparison: V8 recent-form model vs closing market."""
import json, math, sys
from pathlib import Path
from v80_recent_form_backtest import connect, chronological_features, fit_logistic, predict, CUTOFF, EXPECTED

def score_forecast(x):
    home_for,home_against,away_for,away_against=x[11]*100,x[13]*100,x[12]*100,x[14]*100
    return (home_for+away_against)/2,(away_for+home_against)/2

def probability_metrics(ps,ys):
    n=len(ys)
    if not n: return {"n":0}
    ps=[min(1-1e-9,max(1e-9,float(p))) for p in ps]
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
    return {"n":n,"brier":round(brier,6),"log_loss":round(ll,6),"directional_accuracy":round(acc,6),"ece_10_bins":round(ece,6),"bins":bins}

def main():
    conn=connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("SET LOCAL TIME ZONE 'UTC'")
            cur.execute("""SELECT g.game_id,g.season,g.home_team_id,g.away_team_id,g.home_team,g.away_team,
                g.commence_time_utc,g.home_score,g.away_score,g.home_win,
                m.close_home_win_prob,m.close_spread_home,m.close_home_cover_prob,
                m.close_total,m.close_over_prob,m.ats_result,m.total_result
                FROM public.nba_game_results g
                LEFT JOIN public.nba_historical_market_closes m ON m.game_id=g.game_id
                WHERE g.season IN ('2024-25','2025-26') AND g.game_status='Final'
                AND g.commence_time_utc < %s::timestamptz
                ORDER BY g.commence_time_utc,g.game_id""",(CUTOFF,))
            games=cur.fetchall()
    finally:
        conn.rollback(); conn.close()
    train=[g for g in games if g["season"]=="2024-25"]
    test=[g for g in games if g["season"]=="2025-26"]
    if len(train)!=EXPECTED["2024-25"] or len(test)!=EXPECTED["2025-26"]:
        raise RuntimeError(f"Unexpected game counts: train={len(train)} test={len(test)}")
    train_rows=chronological_features(train,"2024-25")
    model=fit_logistic(train_rows)
    test_rows=chronological_features(test,"2025-26")
    # Empirical residual distributions are estimated only from 2024-25.
    margin_residuals=[]; total_residuals=[]
    for r in train_rows:
        g=r["game"]; ph,pa=score_forecast(r["x"])
        margin_residuals.append((g["home_score"]-g["away_score"])-(ph-pa))
        total_residuals.append((g["home_score"]+g["away_score"])-(ph+pa))
    if len(margin_residuals)<1000 or len(total_residuals)<1000:
        raise RuntimeError("Insufficient training residuals")
    matched=[]
    for r in test_rows:
        g=r["game"]
        if any(g[k] is None for k in ("close_home_win_prob","close_spread_home","close_home_cover_prob","close_total","close_over_prob","ats_result","total_result")):
            continue
        ph,pa=score_forecast(r["x"])
        p_ml=predict(r["x"],model)
        predicted_margin=ph-pa
        predicted_total=ph+pa
        spread_line=float(g["close_spread_home"])
        total_line=float(g["close_total"])
        # Empirical CDF: no Gaussian assumption and no test-season outcomes used.
        p_cover=sum(res+predicted_margin+spread_line>0 for res in margin_residuals)/len(margin_residuals)
        p_over=sum(res+predicted_total-total_line>0 for res in total_residuals)/len(total_residuals)
        matched.append({
          "game_id":g["game_id"],"home_win":int(bool(g["home_win"])),
          "feature_ml":p_ml,"market_ml":float(g["close_home_win_prob"]),
          "ats_result":g["ats_result"],"feature_cover":p_cover,"market_cover":float(g["close_home_cover_prob"]),
          "total_result":g["total_result"],"feature_over":p_over,"market_over":float(g["close_over_prob"]),
          "predicted_margin":predicted_margin,"actual_margin":g["home_score"]-g["away_score"],
          "predicted_total":predicted_total,"actual_total":g["home_score"]+g["away_score"],
          "spread_line":spread_line,"total_line":total_line
        })
    if len(matched)<1000: raise RuntimeError(f"Only {len(matched)} matched test games")
    ml_y=[r["home_win"] for r in matched]
    ml={"feature_model":probability_metrics([r["feature_ml"] for r in matched],ml_y),
        "market_close":probability_metrics([r["market_ml"] for r in matched],ml_y)}
    ats=[r for r in matched if r["ats_result"] in ("home","away")]
    ats_y=[int(r["ats_result"]=="home") for r in ats]
    spread={"n":len(ats),
      "feature_model":probability_metrics([r["feature_cover"] for r in ats],ats_y),
      "market_close":probability_metrics([r["market_cover"] for r in ats],ats_y)}
    totals=[r for r in matched if r["total_result"] in ("over","under")]
    total_y=[int(r["total_result"]=="over") for r in totals]
    total={"n":len(totals),
      "feature_model":probability_metrics([r["feature_over"] for r in totals],total_y),
      "market_close":probability_metrics([r["market_over"] for r in totals],total_y)}
    report={"status":"experimental_comparison_not_approved_for_betting","train_season":"2024-25","test_season":"2025-26",
      "train_games":len(train),"test_games":len(test),"matched_market_test_games":len(matched),
      "training_only_residual_samples":{"margin":len(margin_residuals),"total":len(total_residuals)},
      "method":"Train the V8 recent-form logistic model on 2024-25 only. Generate 2025-26 walk-forward predictions. Convert its score forecast to spread/total probabilities using empirical residual distributions from 2024-25 only. Compare with consensus closing no-vig probabilities on the exact same matched games.",
      "markets":{"moneyline":ml,"spread":spread,"totals":total},
      "limitations":"Only one held-out season; consensus close is a strong benchmark, not executable price. Spread and total probabilities are derived from a simple score forecast and historical residual CDF. No ROI/CLV claim is made; independent multi-season replication and actual bookmaker prices are still required."}
    Path("v80_model_vs_market_backtest.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))
    print("PASS: same-sample three-market comparison completed")
if __name__=="__main__":
    try: main()
    except Exception as exc:
        print(f"MODEL VS MARKET BACKTEST FAILED: {type(exc).__name__}: {exc}",file=sys.stderr); sys.exit(1)
