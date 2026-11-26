"""Settle SBR closing markets and score market probability calibration; read-only."""
import json,math,sys
from pathlib import Path
from v80_recent_form_backtest import connect

def american_prob(odds):
 o=float(odds)
 if o==0: raise ValueError("zero American odds")
 return 100/(o+100) if o>0 else abs(o)/(abs(o)+100)
def metrics(ps,ys):
 n=len(ys)
 if not n:return {"n":0}
 ps=[min(1-1e-9,max(1e-9,float(p))) for p in ps]
 b=sum((p-y)**2 for p,y in zip(ps,ys))/n
 ll=-sum(y*math.log(p)+(1-y)*math.log(1-p) for p,y in zip(ps,ys))/n
 acc=sum((p>=.5)==bool(y) for p,y in zip(ps,ys))/n
 ece=0.0
 for i in range(10):
  part=[(p,y) for p,y in zip(ps,ys) if i/10<=p<(i+1)/10 or (i==9 and p==1)]
  if part:ece+=len(part)/n*abs(sum(p for p,y in part)/len(part)-sum(y for p,y in part)/len(part))
 return {"n":n,"brier":round(b,6),"log_loss":round(ll,6),"accuracy":round(acc,6),"ece_10_bins":round(ece,6)}
def main():
 c=connect()
 try:
  with c.cursor() as cur:
   cur.execute("SET TRANSACTION READ ONLY");cur.execute("SET LOCAL TIME ZONE 'UTC'")
   cur.execute("""SELECT b.season,b.game_id,b.close_spread,b.close_total,b.close_home_moneyline,b.close_away_moneyline,
      g.home_score,g.away_score
     FROM public.nba_historical_bookmaker_lines b JOIN public.nba_game_results g USING(game_id)
     WHERE b.provider_id='sbr' AND b.license_review_status='approved'
     ORDER BY b.season,g.commence_time_utc""")
   sbr=cur.fetchall()
   cur.execute("""SELECT m.season,m.close_home_win_prob,m.close_home_cover_prob,m.close_over_prob,
      m.ats_result,m.total_result,g.home_score,g.away_score
     FROM public.nba_historical_market_closes m JOIN public.nba_game_results g USING(game_id)
     ORDER BY m.season,g.commence_time_utc""")
   consensus=cur.fetchall()
 finally:c.rollback();c.close()
 report={"status":"HISTORICAL_MARKET_SETTLEMENT_AUDIT","note":"SBR is an archived source with no individual bookmaker identified. Moneyline ROI is a paper calculation at archived closing prices, not proof those prices were executable. Spread and totals have closing lines but no side prices in this archive; no spread/total ROI or CLV is calculated.","sbr_archive":{},"consensus_close":{}}
 for season in ("2020-21","2021-22"):
  rows=[r for r in sbr if r["season"]==season]
  p_home=[];y_home=[];favorite_wins=[];favorite_profit=[];ats=[];over=[]
  spread_push=total_push=0
  for r in rows:
   ph=american_prob(r["close_home_moneyline"]);pa=american_prob(r["close_away_moneyline"])
   p=ph/(ph+pa); y=int(r["home_score"]>r["away_score"])
   p_home.append(p);y_home.append(y)
   fav_home=ph>=pa;fav_odds=float(r["close_home_moneyline"] if fav_home else r["close_away_moneyline"])
   fav_win=(y==1) if fav_home else (y==0)
   favorite_wins.append(int(fav_win))
   profit=(100/abs(fav_odds) if fav_odds<0 else fav_odds/100) if fav_win else -1.0
   favorite_profit.append(profit)
   margin=r["home_score"]-r["away_score"]
   cover=margin+float(r["close_spread"])
   if cover==0:spread_push+=1
   else:ats.append(int((cover>0)==(float(r["close_spread"])<0)))
   total_score=r["home_score"]+r["away_score"]
   if total_score==float(r["close_total"]):total_push+=1
   else:over.append(int(total_score>float(r["close_total"])))
  report["sbr_archive"][season]={
   "rows":len(rows),"moneyline_no_vig_market":metrics(p_home,y_home),
   "closing_favorite_win_rate":round(sum(favorite_wins)/len(favorite_wins),6) if favorite_wins else None,
   "closing_favorite_flat_bet_paper_roi":round(sum(favorite_profit)/len(favorite_profit),6) if favorite_profit else None,
   "spread_favorite_cover_rate":round(sum(ats)/len(ats),6) if ats else None,"spread_settled_n":len(ats),"spread_pushes":spread_push,
   "over_rate_at_closing_total":round(sum(over)/len(over),6) if over else None,"total_settled_n":len(over),"total_pushes":total_push}
 for season in ("2024-25","2025-26"):
  rows=[r for r in consensus if r["season"]==season]
  mlp=[];mly=[];spp=[];spy=[];top=[];toy=[]
  for r in rows:
   mly.append(int(r["home_score"]>r["away_score"]));mlp.append(float(r["close_home_win_prob"]))
   if r["ats_result"] in ("home","away"):spy.append(int(r["ats_result"]=="home"));spp.append(float(r["close_home_cover_prob"]))
   if r["total_result"] in ("over","under"):toy.append(int(r["total_result"]=="over"));top.append(float(r["close_over_prob"]))
  report["consensus_close"][season]={"rows":len(rows),"moneyline":metrics(mlp,mly),"spread":metrics(spp,spy),"totals":metrics(top,toy)}
 Path("v80_historical_market_settlement.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
 print(json.dumps(report,indent=2));print("PASS: SBR and consensus market settlement audit completed")
if __name__=="__main__":
 try:main()
 except Exception as e:print(f"MARKET SETTLEMENT FAILED: {type(e).__name__}: {e}",file=sys.stderr);sys.exit(1)
