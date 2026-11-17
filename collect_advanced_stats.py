"""Standalone, opt-in NBA team advanced stats collector. No changes to existing app."""
import argparse,csv,json,time,urllib.parse,urllib.request,datetime,pathlib,sys
BASE='https://stats.nba.com/stats/leaguedashteamstats'
FIELDS=['TEAM_ID','TEAM_NAME','GP','OFF_RATING','DEF_RATING','NET_RATING','PACE']
def collect(season,cutoff,timeout):
    params={'Season':season,'SeasonType':'Regular Season','MeasureType':'Advanced','PerMode':'PerGame','LeagueID':'00','LastNGames':'0','Month':'0','OpponentTeamID':'0','TeamID':'0','PlusMinus':'N','PaceAdjust':'N','Rank':'N','DateFrom':'','DateTo':cutoff.strftime('%m/%d/%Y')}
    url=BASE+'?'+urllib.parse.urlencode(params)
    headers={'User-Agent':'Mozilla/5.0 (compatible; NBAResearchCollector/1.0)','Referer':'https://www.nba.com/','Origin':'https://www.nba.com','Accept':'application/json'}
    req=urllib.request.Request(url,headers=headers)
    with urllib.request.urlopen(req,timeout=timeout) as resp: data=json.load(resp)
    sets=data.get('resultSets') or data.get('resultSet')
    if isinstance(sets,dict): sets=[sets]
    if not sets: raise ValueError('NBA API returned no result sets')
    dataset=next((x for x in sets if x.get('name')=='LeagueDashTeamStats'),sets[0])
    cols=dataset['headers']; missing=set(FIELDS)-set(cols)
    if missing: raise ValueError('Missing required columns: '+', '.join(sorted(missing)))
    result=[]
    for values in dataset['rowSet']:
        d=dict(zip(cols,values)); result.append({'season':season,'cutoff_date':cutoff.isoformat(),**{f:d[f] for f in FIELDS}})
    if not 25<=len(result)<=32: raise ValueError(f'Unexpected team count {len(result)}')
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--season',default='2025-26');p.add_argument('--cutoff',help='YYYY-MM-DD, default yesterday UTC');p.add_argument('--out',default='data/advanced_stats');p.add_argument('--timeout',type=int,default=20);p.add_argument('--fetch',action='store_true',help='Explicitly enable network request');args=p.parse_args()
    cutoff=datetime.date.fromisoformat(args.cutoff) if args.cutoff else datetime.datetime.now(datetime.timezone.utc).date()-datetime.timedelta(days=1)
    start=int(args.season[:4]);assert args.season==f'{start}-{(start+1)%100:02d}', 'Season must be YYYY-YY'
    if cutoff>datetime.datetime.now(datetime.timezone.utc).date():p.error('Cutoff cannot be in the future')
    if cutoff<datetime.date(start,10,1):p.error('Cutoff predates season start')
    print(f'Season={args.season}; cutoff={cutoff}; source=NBA Stats Advanced; output={args.out}')
    if not args.fetch:
        print('DRY RUN: no request sent, no data written. Add --fetch to collect.');return
    try: rows=collect(args.season,cutoff,args.timeout)
    except Exception as e:
        print(f'FAILED: {type(e).__name__}: {e}. No placeholder data created.',file=sys.stderr);sys.exit(1)
    out=pathlib.Path(args.out);out.mkdir(parents=True,exist_ok=True)
    dest=out/f'teams_advanced_{args.season}_{cutoff.isoformat()}.csv'
    if dest.exists(): print('Existing snapshot preserved:',dest);return
    with dest.open('x',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=['season','cutoff_date']+FIELDS);writer.writeheader();writer.writerows(rows)
    print('SAVED',dest,'rows=',len(rows))
    print('NOTE: historical cutoff query is a retrospective reconstruction, not proof of original publication time.')
if __name__=='__main__':main()
