import pandas as pd
import numpy as np
import requests

def request(config, method, **kwargs):
    url,key=config
    headers={'apikey':key,'Authorization':'Bearer '+key,'Content-Type':'application/json','Prefer':'return=minimal,resolution=ignore-duplicates'}
    if key.startswith('sb_secret_'): headers.pop('Authorization',None)
    r=requests.request(method,url+'/rest/v1/nba_pinnacle_odds',headers=headers,timeout=20,**kwargs)
    if not r.ok: raise ValueError(f'Pinnacle 雲端操作失敗 HTTP {r.status_code}')
    return r

def load(config):
    rows=[]
    for offset in range(0,100000,500):
        page=request(config,'GET',params={'select':'*','order':'id.asc','limit':500,'offset':offset}).json()
        rows.extend(page)
        if len(page)<500: return rows
    raise ValueError('紀錄超過讀取上限')

def save(config,row):
    request(config,'POST',json=row,params={'on_conflict':'game_id,captured'})

def settle(config,records,games,final):
    byid={int(g['id']):g for g in games if final(g) and g.get('home_team_score') is not None and g.get('visitor_team_score') is not None and g['home_team_score']!=g['visitor_team_score']}
    for r in records:
        g=byid.get(r['game_id'])
        if g and not r.get('settled'):
            patch={'actual_home_score':int(g['home_team_score']),'actual_away_score':int(g['visitor_team_score']),'settled':True}
            request(config,'PATCH',params={'id':'eq.'+str(r['id']),'settled':'eq.false'},json=patch)
            r.update(patch)
    return records

def probabilities(draws,spread,total):
    m=draws[:,0]-draws[:,1]+spread; t=draws.sum(axis=1)-total
    return dict(ai_home_cover=float(np.mean(m>0)),ai_away_cover=float(np.mean(m<0)),ai_over=float(np.mean(t>0)),ai_under=float(np.mean(t<0)))

def accuracy(records,now):
    # Earliest qualifying pregame snapshot per game; ties in predicted sides excluded.
    chosen={}
    for r in sorted(records,key=lambda r:pd.Timestamp(r['captured'])):
        if pd.Timestamp(r['captured'])>=pd.Timestamp(r['tip']) or not r.get('settled'): continue
        chosen.setdefault(r['game_id'],r)
    out=[]
    for days in (7,30,None):
        rows=[r for r in chosen.values() if days is None or pd.Timestamp(r['tip'])>=pd.Timestamp(now)-pd.Timedelta(days=days)]
        for label,a,b,actual in [('獨贏','ai_home_win',None,lambda r:r['actual_home_score']-r['actual_away_score']),('讓分','ai_home_cover','ai_away_cover',lambda r:r['actual_home_score']-r['actual_away_score']+r['home_spread']),('大小分','ai_over','ai_under',lambda r:r['actual_home_score']+r['actual_away_score']-r['total_line'])]:
            hits=[]; pushes=0
            for r in rows:
                p=r.get(a); q=r.get(b) if b else (None if p is None else 1-p)
                if p is None or q is None or p==q: continue
                v=actual(r)
                if v==0: pushes+=1; continue
                hits.append((p>q)==(v>0))
            out.append({'期間':'全部' if days is None else f'近{days}天','類別':label,'有效場數':len(hits),'走盤':pushes,'命中率':None if not hits else sum(hits)/len(hits)})
    return out
