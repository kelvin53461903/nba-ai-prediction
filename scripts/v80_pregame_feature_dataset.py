#!/usr/bin/env python3
"""Build leakage-safe pregame team-form features from verified NBA final scores.

Input CSV columns: game_id, season, home_team_id, away_team_id, home_score,
away_score, commence_time_utc, game_status. No network access or DB writes.
Games with the same tipoff timestamp are evaluated before any are added to history.
"""
from __future__ import annotations
import argparse, csv, hashlib, json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
REQUIRED=('game_id','season','home_team_id','away_team_id','home_score','away_score','commence_time_utc','game_status')
def parse_utc(value):
 dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
 if dt.tzinfo is None or dt.utcoffset() is None: raise ValueError('timestamp must include timezone')
 return dt
def _team_features(history,tip):
 if not history: return {'games_before':0,'win_pct_last5':'','avg_points_for_last5':'','avg_points_against_last5':'','win_pct_last10':'','avg_points_for_last10':'','avg_points_against_last10':'','rest_days':''}
 def win(n):
  s=history[-n:]; return sum(x['win'] for x in s)/len(s),sum(x['pf'] for x in s)/len(s),sum(x['pa'] for x in s)/len(s)
 w5,pf5,pa5=win(5); w10,pf10,pa10=win(10)
 rest=max(0.0,(tip-history[-1]['tipoff']).total_seconds()/86400.0)
 return {'games_before':len(history),'win_pct_last5':round(w5,6),'avg_points_for_last5':round(pf5,4),'avg_points_against_last5':round(pa5,4),'win_pct_last10':round(w10,6),'avg_points_for_last10':round(pf10,4),'avg_points_against_last10':round(pa10,4),'rest_days':round(rest,4)}
def build_pregame_rows(games):
 clean=[]; seen=set()
 for i,g in enumerate(games):
  missing=[k for k in REQUIRED if k not in g or g[k] in (None,'')]
  if missing: raise ValueError(f'row {i}: missing {missing}')
  gid=str(g['game_id'])
  if gid in seen: raise ValueError(f'duplicate game_id: {gid}')
  seen.add(gid)
  if str(g['game_status']).casefold() not in {'final','completed'}: continue
  home,away=str(g['home_team_id']),str(g['away_team_id'])
  if home==away: raise ValueError(f'game {gid}: home and away team IDs match')
  hs,ascore=int(g['home_score']),int(g['away_score'])
  if hs<0 or ascore<0: raise ValueError(f'game {gid}: negative score')
  clean.append({'game_id':gid,'season':str(g['season']),'home_team_id':home,'away_team_id':away,'home_score':hs,'away_score':ascore,'tipoff':parse_utc(g['commence_time_utc'])})
 clean.sort(key=lambda x:(x['tipoff'],x['game_id']))
 history=defaultdict(list); output=[]; i=0
 while i<len(clean):
  tip=clean[i]['tipoff']; batch=[]
  while i<len(clean) and clean[i]['tipoff']==tip: batch.append(clean[i]); i+=1
  for g in batch:
   hf=_team_features(history[g['home_team_id']],tip); af=_team_features(history[g['away_team_id']],tip)
   row={'game_id':g['game_id'],'season':g['season'],'commence_time_utc':tip.isoformat(),'home_team_id':g['home_team_id'],'away_team_id':g['away_team_id']}
   row.update({f'home_{k}':v for k,v in hf.items()}); row.update({f'away_{k}':v for k,v in af.items()})
   row.update({'actual_home_score':g['home_score'],'actual_away_score':g['away_score'],'actual_home_win':int(g['home_score']>g['away_score']),'actual_total':g['home_score']+g['away_score'],'actual_margin':g['home_score']-g['away_score']})
   output.append(row)
  for g in batch:
   history[g['home_team_id']].append({'tipoff':tip,'pf':g['home_score'],'pa':g['away_score'],'win':int(g['home_score']>g['away_score'])})
   history[g['away_team_id']].append({'tipoff':tip,'pf':g['away_score'],'pa':g['home_score'],'win':int(g['away_score']>g['home_score'])})
 return output
def run(input_csv,output_csv,report_json):
 raw=Path(input_csv).read_bytes(); source_hash=hashlib.sha256(raw).hexdigest()
 with open(input_csv,newline='',encoding='utf-8-sig') as f: games=list(csv.DictReader(f))
 rows=build_pregame_rows(games)
 if not rows: raise RuntimeError('No completed games found')
 Path(output_csv).parent.mkdir(parents=True,exist_ok=True)
 with open(output_csv,'w',newline='',encoding='utf-8') as f:
  writer=csv.DictWriter(f,fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
 output_hash=hashlib.sha256(Path(output_csv).read_bytes()).hexdigest()
 report={'input_rows':len(games),'completed_games':len(rows),'input_sha256':source_hash,'output_sha256':output_hash,'feature_cutoff_rule':'strictly earlier tipoff timestamps only; same-tipoff games excluded','features_are_pregame_only':True,'market_odds_used':False,'model_predictions_generated':False,'roi':'NOT_CALCULATED','clv':'NOT_CALCULATED'}
 Path(report_json).parent.mkdir(parents=True,exist_ok=True); Path(report_json).write_text(json.dumps(report,indent=2),encoding='utf-8'); print(json.dumps(report,indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser(); p.add_argument('--input',required=True); p.add_argument('--output',required=True); p.add_argument('--report',required=True); a=p.parse_args(); run(a.input,a.output,a.report)