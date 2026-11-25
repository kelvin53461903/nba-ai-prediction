"""NBA V8.0 recent-form + home/away split model. Read-only, chronological backtest."""
import argparse,csv,hashlib,json,math,os
from collections import defaultdict,deque
from pathlib import Path
from urllib.parse import urlsplit,unquote
import certifi,psycopg
from psycopg.rows import dict_row

SECRET="V80_HISTORICAL_IMPORT_DATABASE_URL"
CUTOFF="2026-04-02T00:00:00Z"
EXPECTED={"2024-25":1321,"2025-26":1138}
FEATURES=["elo_diff","home_win10","away_win10","home_margin10","away_margin10",
"home_for10","home_against10","away_for10","away_against10",
"home_venue_margin10","away_venue_margin10","home_venue_for10","away_venue_for10",
"home_venue_against10","away_venue_against10"]

def connect():
    raw=os.environ.get(SECRET,"").strip()
    if not raw: raise RuntimeError("Missing isolated DB secret")
    u=urlsplit(raw)
    cfg={"host":u.hostname or "","port":u.port or 5432,"dbname":u.path.lstrip("/"),"user":unquote(u.username or ""),"password":unquote(u.password or "")}
    if cfg["dbname"]!="nba_v80" or cfg["user"]!="v80_historical_import" or not cfg["host"].endswith("neon.tech"):
        raise RuntimeError("Unexpected database or role")
    c=psycopg.connect(host=cfg["host"],port=int(cfg["port"]),dbname="nba_v80",user="v80_historical_import",
        password=cfg["password"],sslmode="verify-full",sslrootcert=certifi.where(),channel_binding="require",
        connect_timeout=15,application_name="NBA_V80_FEATURE_BACKTEST",row_factory=dict_row)
    if not c.pgconn.ssl_in_use: c.close(); raise RuntimeError("TLS not active")
    return c

def sigmoid(z):
    z=max(-30.0,min(30.0,z))
    return 1/(1+math.exp(-z))

def elo_prob(diff): return 1/(1+10**(-diff/400))
def margin_k(m,d): return math.log(abs(m)+1)*(2.2/(2.2+0.001*abs(d)))

def avg(items,key):
    return sum(x[key] for x in items)/len(items) if items else 0.0

def make_features(g,elo,history,venue_history):
    h,a=g["home_team_id"],g["away_team_id"]
    hh=list(history[h]); ah=list(history[a])
    hv=list(venue_history[(h,"home")]); av=list(venue_history[(a,"away")])
    return [
        (elo[h]+65-elo[a])/400.0,
        avg(hh,"win"),avg(ah,"win"),
        avg(hh,"margin")/20.0,avg(ah,"margin")/20.0,
        avg(hh,"pf")/100.0,avg(hh,"pa")/100.0,
        avg(ah,"pf")/100.0,avg(ah,"pa")/100.0,
        avg(hv,"margin")/20.0,avg(av,"margin")/20.0,
        avg(hv,"pf")/100.0,avg(av,"pf")/100.0,
        avg(hv,"pa")/100.0,avg(av,"pa")/100.0
    ]

def update_game(g,elo,history,venue_history):
    h,a=g["home_team_id"],g["away_team_id"]
    diff=elo[h]+65-elo[a]; expected=elo_prob(diff); actual=int(bool(g["home_win"]))
    change=20*margin_k(g["home_score"]-g["away_score"],diff)*(actual-expected)
    elo[h]+=change; elo[a]-=change
    history[h].append({"win":actual,"margin":g["home_score"]-g["away_score"],"pf":g["home_score"],"pa":g["away_score"]})
    history[a].append({"win":1-actual,"margin":g["away_score"]-g["home_score"],"pf":g["away_score"],"pa":g["home_score"]})
    venue_history[(h,"home")].append({"margin":g["home_score"]-g["away_score"],"pf":g["home_score"],"pa":g["away_score"]})
    venue_history[(a,"away")].append({"margin":g["away_score"]-g["home_score"],"pf":g["away_score"],"pa":g["home_score"]})

def chronological_features(games,season):
    elo=defaultdict(lambda:1500.0)
    hist=defaultdict(lambda:deque(maxlen=10))
    venue=defaultdict(lambda:deque(maxlen=10))
    grouped=defaultdict(list)
    for g in games: grouped[g["commence_time_utc"]].append(g)
    rows=[]
    for tip in sorted(grouped):
        batch=grouped[tip]
        for g in batch:
            x=make_features(g,elo,hist,venue)
            rows.append({"game":g,"x":x,"elo_p":elo_prob(elo[g["home_team_id"]]+65-elo[g["away_team_id"]])})
        for g in batch: update_game(g,elo,hist,venue)
    return rows

def fit_logistic(rows):
    xs=[r["x"] for r in rows]; ys=[int(bool(r["game"]["home_win"])) for r in rows]
    means=[sum(x[j] for x in xs)/len(xs) for j in range(len(FEATURES))]
    stds=[]
    for j in range(len(FEATURES)):
        v=math.sqrt(sum((x[j]-means[j])**2 for x in xs)/len(xs))
        stds.append(v if v>1e-8 else 1.0)
    z=[[ (x[j]-means[j])/stds[j] for j in range(len(FEATURES))] for x in xs]
    w=[0.0]*(len(FEATURES)+1); rate=0.03; reg=0.01
    for epoch in range(3000):
        grad=[0.0]*len(w)
        for row,y in zip(z,ys):
            p=sigmoid(w[0]+sum(w[j+1]*row[j] for j in range(len(row))))
            grad[0]+=p-y
            for j,v in enumerate(row): grad[j+1]+=(p-y)*v
        n=len(z)
        for j in range(len(w)):
            grad[j]=grad[j]/n+(reg*w[j] if j else 0.0)
            w[j]-=rate*grad[j]
    return {"means":means,"stds":stds,"weights":w,"features":FEATURES,"training_rows":len(rows)}

def predict(x,model):
    z=[(x[j]-model["means"][j])/model["stds"][j] for j in range(len(x))]
    return sigmoid(model["weights"][0]+sum(model["weights"][j+1]*z[j] for j in range(len(z))))

def metrics(rows,key):
    n=len(rows); ys=[int(bool(r["game"]["home_win"])) for r in rows]
    ps=[min(1-1e-12,max(1e-12,float(r[key]))) for r in rows]
    brier=sum((p-y)**2 for p,y in zip(ps,ys))/n
    ll=-sum(y*math.log(p)+(1-y)*math.log(1-p) for p,y in zip(ps,ys))/n
    ece=0
    for i in range(10):
        part=[(p,y) for p,y in zip(ps,ys) if i/10<=p<(i+1)/10 or (i==9 and p==1)]
        if part: ece+=len(part)/n*abs(sum(p for p,y in part)/len(part)-sum(y for p,y in part)/len(part))
    return {"sample_size":n,"accuracy":sum((p>=.5)==bool(y) for p,y in zip(ps,ys))/n,
        "brier_score":brier,"log_loss":ll,"ece_10_bins":ece}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--out",default="artifacts/v80-features"); args=ap.parse_args()
    c=connect()
    try:
        with c.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY"); cur.execute("SET LOCAL TIME ZONE 'UTC'")
            cur.execute("""SELECT game_id,season,home_team_id,away_team_id,home_team,away_team,commence_time_utc,
                home_score,away_score,home_win FROM public.nba_game_results
                WHERE season IN ('2024-25','2025-26') AND game_status='Final'
                AND commence_time_utc < %s::timestamptz ORDER BY commence_time_utc,game_id""",(CUTOFF,))
            games=cur.fetchall()
    finally: c.rollback(); c.close()
    counts=defaultdict(int)
    for g in games: counts[g["season"]]+=1
    if len(games)!=sum(EXPECTED.values()) or dict(counts)!=EXPECTED: raise RuntimeError(f"Dataset mismatch {dict(counts)}")
    if len({g["game_id"] for g in games})!=len(games): raise RuntimeError("Duplicate IDs")
    train=[g for g in games if g["season"]=="2024-25"]
    test=[g for g in games if g["season"]=="2025-26"]
    tr=chronological_features(train,"2024-25")
    model=fit_logistic(tr)
    te=chronological_features(test,"2025-26")
    outrows=[]
    for r in te:
        g=r["game"]; p=predict(r["x"],model)
        # Rolling venue-specific points forecast from the same pregame feature vector.
        hf,ha,af,aa=r["x"][11]*100,r["x"][13]*100,r["x"][12]*100,r["x"][14]*100
        pred_home=(hf+aa)/2; pred_away=(af+ha)/2
        outrows.append({"game_id":g["game_id"],"commence_time_utc":g["commence_time_utc"].isoformat(),
            "home_team":g["home_team"],"away_team":g["away_team"],"feature_model_home_probability":p,
            "elo_home_probability":r["elo_p"],"home_win":bool(g["home_win"]),
            "predicted_home_score":pred_home,"predicted_away_score":pred_away,
            "actual_home_score":g["home_score"],"actual_away_score":g["away_score"],
            "features_json":json.dumps(dict(zip(FEATURES,r["x"])))})
    # Metrics use a common sample and direct probability values.
    def simple(rows,key):
        n=len(rows); ys=[int(r["home_win"]) for r in rows]; ps=[min(1-1e-12,max(1e-12,r[key])) for r in rows]
        ece=0
        for i in range(10):
            part=[(p,y) for p,y in zip(ps,ys) if i/10<=p<(i+1)/10 or (i==9 and p==1)]
            if part: ece+=len(part)/n*abs(sum(p for p,y in part)/len(part)-sum(y for p,y in part)/len(part))
        return {"sample_size":n,"accuracy":sum((p>=.5)==bool(y) for p,y in zip(ps,ys))/n,
            "brier_score":sum((p-y)**2 for p,y in zip(ps,ys))/n,
            "log_loss":-sum(y*math.log(p)+(1-y)*math.log(1-p) for p,y in zip(ps,ys))/n,"ece_10_bins":ece}
    feature_metrics=simple(outrows,"feature_model_home_probability")
    elo_metrics=simple(outrows,"elo_home_probability")
    score={"sample_size":len(outrows),
        "home_score_mae":sum(abs(r["predicted_home_score"]-r["actual_home_score"]) for r in outrows)/len(outrows),
        "away_score_mae":sum(abs(r["predicted_away_score"]-r["actual_away_score"]) for r in outrows)/len(outrows),
        "total_score_mae":sum(abs((r["predicted_home_score"]+r["predicted_away_score"])-(r["actual_home_score"]+r["actual_away_score"])) for r in outrows)/len(outrows),
        "margin_mae":sum(abs((r["predicted_home_score"]-r["predicted_away_score"])-(r["actual_home_score"]-r["actual_away_score"])) for r in outrows)/len(outrows)}
    material="\n".join(f'{g["game_id"]}|{g["commence_time_utc"].isoformat()}|{g["home_score"]}|{g["away_score"]}' for g in games).encode()
    report={"model":"NBA V8.0 Recent Form + Home/Away Splits Logistic Regression","status":"experimental_not_approved",
        "training_season":"2024-25","evaluation_season":"2025-26","training_rows":len(tr),"evaluation_rows":len(te),
        "dataset_sha256":hashlib.sha256(material).hexdigest(),"features":FEATURES,
        "method":"Chronological pregame rolling last-10 team form and last-10 home/away venue splits; logistic regression fit only on 2024-25; 2025-26 evaluated walk-forward. Same-tipoff games predicted before results update history.",
        "feature_model":feature_metrics,"elo_baseline":elo_metrics,"score_forecast":score,
        "model_parameters":model,"limitations":"Only historical scores/results used. No injuries, odds, rest days, or official advanced stats. Experimental only."}
    out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    (out/"report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    with (out/"predictions.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=list(outrows[0])); w.writeheader(); w.writerows(outrows)
    print("PASS: isolated read-only TLS database access")
    print(f"PASS: chronological features train={len(tr)} test={len(te)}")
    print("FEATURE_MODEL:",json.dumps(feature_metrics))
    print("ELO_BASELINE:",json.dumps(elo_metrics))
    print("SCORE_FORECAST:",json.dumps(score))
    print("RESULT: FEATURE BACKTEST COMPLETE; no database writes")

if __name__=="__main__": main()
