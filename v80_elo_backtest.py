"""Leakage-safe chronological Elo baseline backtest for NBA V8.0. Read-only."""
import argparse, csv, hashlib, json, math, os
from collections import defaultdict
from pathlib import Path
import certifi, psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

SECRET="V80_HISTORICAL_IMPORT_DATABASE_URL"
CUTOFF="2026-04-02T00:00:00Z"
EXPECTED={"2024-25":1321,"2025-26":1138}

def connect():
    raw=os.environ.get(SECRET,"").strip()
    if not raw: raise RuntimeError("Missing isolated database secret")
    cfg=conninfo_to_dict(raw)
    if cfg.get("dbname")!="nba_v80" or cfg.get("user")!="v80_historical_import" or not cfg.get("host","").endswith("neon.tech"):
        raise RuntimeError("Unexpected database or role")
    conn=psycopg.connect(host=cfg["host"],port=int(cfg.get("port","5432")),dbname="nba_v80",
        user="v80_historical_import",password=cfg.get("password"),sslmode="verify-full",
        sslrootcert=certifi.where(),channel_binding="require",connect_timeout=15,
        application_name="NBA_V80_ELO_BACKTEST",row_factory=dict_row)
    if not conn.pgconn.ssl_in_use:
        conn.close()
        raise RuntimeError("TLS is not active")
    return conn

def sigmoid(x): return 1/(1+10**(-x/400))
def margin_k(margin,diff): return math.log(abs(margin)+1)*(2.2/(2.2+0.001*abs(diff)))

def metric(rows,key):
    n=len(rows)
    if not n: raise RuntimeError("No test predictions")
    ys=[int(r["home_win"]) for r in rows]
    ps=[min(1-1e-12,max(1e-12,float(r[key]))) for r in rows]
    bins=[]; ece=0.0
    for i in range(10):
        lo,hi=i/10,(i+1)/10
        part=[(p,y) for p,y in zip(ps,ys) if lo<=p<hi or (i==9 and p==1)]
        if part:
            mp=sum(p for p,y in part)/len(part); my=sum(y for p,y in part)/len(part)
            ece+=len(part)/n*abs(mp-my)
            bins.append({"bin":f"{lo:.1f}-{hi:.1f}","count":len(part),"mean_probability":mp,"observed_home_win_rate":my})
        else: bins.append({"bin":f"{lo:.1f}-{hi:.1f}","count":0,"mean_probability":None,"observed_home_win_rate":None})
    return {"sample_size":n,"accuracy":sum((p>=.5)==bool(y) for p,y in zip(ps,ys))/n,
            "brier_score":sum((p-y)**2 for p,y in zip(ps,ys))/n,
            "log_loss":-sum(y*math.log(p)+(1-y)*math.log(1-p) for p,y in zip(ps,ys))/n,
            "ece_10_bins":ece,"calibration_bins":bins}



def fit_temperature(rows):
    # Grid-search a single temperature on calibration-only predictions.
    best_t=1.0
    best_loss=float("inf")
    for step in range(50,501):
        t=step/100.0
        loss=0.0
        for r in rows:
            p=min(1-1e-9,max(1e-9,float(r["home_probability"])))
            z=max(-30.0,min(30.0,logit(p)/t))
            q=1.0/(1.0+math.exp(-z))
            y=int(r["home_win"])
            loss -= y*math.log(q)+(1-y)*math.log(1-q)
        loss /= len(rows)
        if loss < best_loss:
            best_loss=loss
            best_t=t
    return {"temperature":best_t,"calibration_log_loss":best_loss}

def apply_temperature(p, temperature):
    z=max(-30.0,min(30.0,logit(p)/temperature))
    return 1.0/(1.0+math.exp(-z))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--out",default="artifacts/v80-elo"); args=ap.parse_args()
    conn=connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("SET LOCAL TIME ZONE 'UTC'")
            cur.execute("""SELECT game_id,season,home_team_id,away_team_id,home_team,away_team,
                commence_time_utc,home_score,away_score,home_win
                FROM public.nba_game_results
                WHERE season IN ('2024-25','2025-26') AND game_status='Final'
                AND commence_time_utc < %s::timestamptz
                ORDER BY commence_time_utc,game_id""",(CUTOFF,))
            games=cur.fetchall()
    finally: conn.rollback(); conn.close()
    counts=defaultdict(int)
    for g in games: counts[g["season"]]+=1
    if len(games)!=sum(EXPECTED.values()) or dict(counts)!=EXPECTED: raise RuntimeError(f"Dataset count mismatch: {dict(counts)}")
    if len({g["game_id"] for g in games})!=len(games): raise RuntimeError("Duplicate game IDs")
    training=[g for g in games if g["season"]=="2024-25"]
    testing=[g for g in games if g["season"]=="2025-26"]
    home_rate=sum(bool(g["home_win"]) for g in training)/len(training)
    elo=defaultdict(lambda:1500.0); K=20.0; HCA=65.0
    def update(g):
        h,a=g["home_team_id"],g["away_team_id"]
        diff=elo[h]+HCA-elo[a]; exp=sigmoid(diff); actual=int(bool(g["home_win"]))
        change=K*margin_k(g["home_score"]-g["away_score"],diff)*(actual-exp)
        elo[h]+=change; elo[a]-=change
    for g in training: update(g)
    grouped=defaultdict(list)
    for g in testing: grouped[g["commence_time_utc"]].append(g)
    preds=[]
    for tip in sorted(grouped):
        batch=grouped[tip]
        for g in batch:
            h,a=g["home_team_id"],g["away_team_id"]
            preds.append({"game_id":g["game_id"],"season":g["season"],"commence_time_utc":g["commence_time_utc"].isoformat(),
                "home_team":g["home_team"],"away_team":g["away_team"],"home_probability":sigmoid(elo[h]+HCA-elo[a]),
                "constant_home_rate_probability":home_rate,"home_win":bool(g["home_win"]),
                "actual_home_score":g["home_score"],"actual_away_score":g["away_score"],
                "pre_game_home_elo":elo[h],"pre_game_away_elo":elo[a]})
        for g in batch: update(g)
    # First half of 2025-26 is calibration-only; second half is untouched evaluation.
    tips=sorted({r["commence_time_utc"] for r in preds})
    calibration_cut=tips[len(tips)//2]
    calibration_rows=[r for r in preds if r["commence_time_utc"] < calibration_cut]
    test_rows=[r for r in preds if r["commence_time_utc"] >= calibration_cut]
    if len(calibration_rows)<100 or len(test_rows)<100: raise RuntimeError("Insufficient calibration/test split")
    temperature=fit_temperature(calibration_rows)
    for r in preds:
        r["split"]="calibration" if r["commence_time_utc"] < calibration_cut else "test"
        r["temperature_home_probability"]=None if r["split"]=="calibration" else apply_temperature(r["home_probability"],temperature["temperature"])
    raw_test=metric(test_rows,"home_probability")
    temperature_test=metric(test_rows,"temperature_home_probability")
    baseline_test=metric(test_rows,"constant_home_rate_probability")
    payload="\n".join(f'{g["game_id"]}|{g["commence_time_utc"].isoformat()}|{g["home_score"]}|{g["away_score"]}' for g in games).encode()
    report={"model":"NBA V8.0 Elo + Platt Calibration","status":"experimental_not_approved","training_season":"2024-25",
        "calibration_season":"2025-26 first chronological half","evaluation_season":"2025-26 second chronological half",
        "training_rows":len(training),"calibration_rows":len(calibration_rows),"evaluation_rows":len(test_rows),
        "calibration_cutoff_utc":calibration_cut,"dataset_sha256":hashlib.sha256(payload).hexdigest(),"cutoff_exclusive_utc":CUTOFF,
        "method":{"elo_start":1500,"k_factor":K,"home_advantage":HCA,"walk_forward":True,
        "same_tipoff_games_predicted_before_updates":True,"calibration":"Platt scaling fitted only on first half of 2025-26",
        "limitations":"Uses historical final scores only; no injuries, odds, or advanced stats. Experimental baseline, not production-ready."},
        "temperature_parameters":temperature,"elo_raw_test":raw_test,"elo_temperature_test":temperature_test,"constant_home_rate_baseline_test":baseline_test}

    out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    (out/"report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    with (out/"predictions.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=list(preds[0])); w.writeheader(); w.writerows(preds)
    print("PASS: read-only TLS database access")
    print(f"PASS: chronological walk-forward; train={len(training)} test={len(testing)}")
    print("ELO_RAW_TEST:",json.dumps({k:v for k,v in raw_test.items() if k!="calibration_bins"}))
    print("ELO_TEMPERATURE_TEST:",json.dumps({k:v for k,v in temperature_test.items() if k!="calibration_bins"}))
    print("BASELINE_TEST:",json.dumps({k:v for k,v in baseline_test.items() if k!="calibration_bins"}))
    print("RESULT: BACKTEST COMPLETE; no database writes performed")

if __name__=="__main__": main()
