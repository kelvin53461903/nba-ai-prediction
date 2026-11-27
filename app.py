import streamlit as st
import pandas as pd
import numpy as np
import requests, time, re, io
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import pdfplumber
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict
import sqlite3, os, gzip, json
from pathlib import Path
from sklearn.ensemble import VotingClassifier, VotingRegressor
from sklearn.base import clone
from sklearn.multioutput import MultiOutputRegressor
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor, HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.metrics import accuracy_score, mean_absolute_error, brier_score_loss

if not os.environ.get('NBA_WORKER'): st.set_page_config(page_title='NBA AI V8.0 Beta', page_icon='🏀', layout='wide')
HK=ZoneInfo('Asia/Hong_Kong')
BASE='https://api.balldontlie.io/v1/'
NBA_LOGO_IDS = {'ATL': 1610612737, 'BOS': 1610612738, 'BKN': 1610612751, 'CHA': 1610612766, 'CHI': 1610612741, 'CLE': 1610612739, 'DAL': 1610612742, 'DEN': 1610612743, 'DET': 1610612765, 'GSW': 1610612744, 'HOU': 1610612745, 'IND': 1610612754, 'LAC': 1610612746, 'LAL': 1610612747, 'MEM': 1610612763, 'MIA': 1610612748, 'MIL': 1610612749, 'MIN': 1610612750, 'NOP': 1610612740, 'NYK': 1610612752, 'OKC': 1610612760, 'ORL': 1610612753, 'PHI': 1610612755, 'PHX': 1610612756, 'POR': 1610612757, 'SAC': 1610612758, 'SAS': 1610612759, 'TOR': 1610612761, 'UTA': 1610612762, 'WAS': 1610612764}

def show_team_logo(column, team):
    abbr = str(team.get("abbreviation", "")).upper()
    abbr = {"BRK":"BKN", "PHO":"PHX", "NO":"NOP", "NY":"NYK", "GS":"GSW", "SA":"SAS", "UTAH":"UTA", "WSH":"WAS"}.get(abbr, abbr)
    logo_id = NBA_LOGO_IDS.get(abbr)
    with column:
        if logo_id:
            st.markdown(f'<img src="https://cdn.nba.com/logos/nba/{logo_id}/primary/L/logo.svg" alt="{abbr} logo" width="90" height="90" style="object-fit:contain" />', unsafe_allow_html=True)
        else:
            st.caption("🏀 NBA")
        st.caption(display_team(team))

from api_cache import fetch_cached, RateLimited

def fetch(key, endpoint, pairs):
    return fetch_cached(key, BASE, endpoint, pairs, worker=bool(os.environ.get('NBA_WORKER')))

def shared_history(season):
    """Public, compressed game-history snapshot produced by the scheduled worker.

    Never silently treat stale current-season data as current.
    """
    url = (f'https://raw.githubusercontent.com/kelvin53461903/'
           f'nba-ai-prediction/main/data/history_{season}.json.gz')
    r = requests.get(url, timeout=25, headers={'Cache-Control': 'no-cache'})
    if r.status_code != 200:
        raise ValueError(f'背景歷史資料尚未發布 (HTTP {r.status_code})')
    obj = json.loads(gzip.decompress(r.content))
    if obj.get('season') != season or not isinstance(obj.get('games'), list):
        raise ValueError('背景歷史資料格式或賽季不符')
    updated = pd.Timestamp(obj['updated'])
    age = pd.Timestamp.now(tz='UTC') - updated
    if age < pd.Timedelta(0) or age > pd.Timedelta(hours=36):
        raise ValueError('背景歷史資料超過 36 小時未更新')
    if len(obj['games']) < 200:
        raise ValueError('背景歷史資料不足，拒絕訓練')
    return obj['games'], obj['updated']


def publish_history_snapshot(season, rows):
    """Worker writes public NBA game data only; never credentials or predictions."""
    folder = Path('data')
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f'history_{season}.json.gz'
    obj = dict(season=season,
               updated=datetime.now(ZoneInfo('UTC')).isoformat(),
               games=rows)
    # gzip mtime=0 makes compression deterministic apart from the updated field.
    payload = gzip.compress(json.dumps(obj, separators=(',', ':'),
                                       ensure_ascii=False).encode(), mtime=0)
    temp = target.with_suffix('.tmp')
    temp.write_bytes(payload)
    temp.replace(target)
    print(f'Published history snapshot: {target} ({len(rows)} games, {len(payload)} bytes)')


def history(key, season):
    rows=[]; times=[]
    for y in range(season-2,season+1):
        part, updated=fetch_cached(key,BASE,'games',(('seasons[]',y),),worker=bool(os.environ.get('NBA_WORKER')),ttl=21600 if y==season else 2592000)
        rows.extend(part); times.append(updated)
    return rows,min(times)

def stamp(g): return pd.to_datetime(g.get('datetime'),utc=True,errors='coerce')
def name(t): return t.get('full_name',t.get('abbreviation','?'))
TEAM_ZH = {'Atlanta Hawks': '亞特蘭大鷹隊', 'Boston Celtics': '波士頓塞爾特人', 'Brooklyn Nets': '布魯克林籃網', 'Charlotte Hornets': '夏洛特黃蜂', 'Chicago Bulls': '芝加哥公牛', 'Cleveland Cavaliers': '克里夫蘭騎士', 'Dallas Mavericks': '達拉斯獨行俠', 'Denver Nuggets': '丹佛金塊', 'Detroit Pistons': '底特律活塞', 'Golden State Warriors': '金州勇士', 'Houston Rockets': '侯斯頓火箭', 'Indiana Pacers': '印第安納溜馬', 'LA Clippers': '洛杉磯快艇', 'Los Angeles Clippers': '洛杉磯快艇', 'Los Angeles Lakers': '洛杉磯湖人', 'Memphis Grizzlies': '孟菲斯灰熊', 'Miami Heat': '邁阿密熱火', 'Milwaukee Bucks': '密爾沃基公鹿', 'Minnesota Timberwolves': '明尼蘇達木狼', 'New Orleans Pelicans': '新奧爾良鵜鶘', 'New York Knicks': '紐約人', 'Oklahoma City Thunder': '奧克拉荷馬城雷霆', 'Orlando Magic': '奧蘭多魔術', 'Philadelphia 76ers': '費城76人', 'Phoenix Suns': '鳳凰城太陽', 'Portland Trail Blazers': '波特蘭拓荒者', 'Sacramento Kings': '薩克拉門托帝王', 'San Antonio Spurs': '聖安東尼奧馬刺', 'Toronto Raptors': '多倫多速龍', 'Utah Jazz': '猶他爵士', 'Washington Wizards': '華盛頓巫師'}
def display_team(t):
    english = name(t) if isinstance(t, dict) else str(t)
    chinese = TEAM_ZH.get(english)
    return f'{english}（{chinese}）' if chinese else english

def final(g): return str(g.get('status','')).lower().startswith('final') and not g.get('postponed')
def features(hist,h,a,day):
    result=[]
    for tid,loc in [(h,1),(a,0)]:
        records=hist[tid]
        if len(records)<5: return None
        for subset in [records[-5:],records[-10:], [r for r in records if r[4]==loc][-10:]]:
            if not subset: subset=records[-5:]
            ar=np.array([r[1:4] for r in subset]); result.extend(ar.mean(axis=0))
        gap=(day-records[-1][0]).days
        result.extend([min(10,max(0,gap-1)),int(gap==1)])
        recent=np.array([r[1:4] for r in records[-20:]],dtype=float)
        w=np.exp(-np.arange(len(recent)-1,-1,-1)/6)
        result.extend(np.average(recent,axis=0,weights=w))
        margin=recent[:,0]-recent[:,1]
        result.extend([margin.mean(),margin.std(),recent[:,0].std(),recent[:,1].std(),sum(0<(day-r[0]).days<=7 for r in records[-15:])])
    result.extend([elo_rating(hist[h]),elo_rating(hist[a]),elo_rating(hist[h])-elo_rating(hist[a])])
    return result

def elo_rating(records):
    return records[-1][5] if records else 1500.0

def simulate(hp,ap,residuals,seed):
    rng=np.random.default_rng(seed)
    draws=np.maximum(0,np.rint(np.array([hp,ap])+residuals[rng.integers(0,len(residuals),10000)]))
    return draws

def cloud_config():
    return None  # Beta: never connect to production storage

def _disabled_production_cloud_config():
    try:
        url=os.environ.get('SUPABASE_URL') or st.secrets['SUPABASE_URL']
        key=os.environ.get('SUPABASE_SERVICE_KEY') or st.secrets['SUPABASE_SERVICE_KEY']
        return str(url).strip().rstrip('/'),str(key).strip()
    except Exception: return None

def cloud_request(method, **kwargs):
    url,key=cloud_config()
    headers={'apikey':key,'Authorization':'Bearer '+key,'Content-Type':'application/json','Prefer':'resolution=ignore-duplicates,return=minimal'}
    if key.startswith('sb_secret_'): headers.pop('Authorization',None)
    r=requests.request(method,url+'/rest/v1/nba_predictions',headers=headers,timeout=20,**kwargs)
    if not r.ok: raise ValueError('雲端紀錄操作失敗 HTTP '+str(r.status_code))
    return r

def ledger(game, ts, p, hp, ap):
    return  # Beta: no persistent prediction writes

def _disabled_ledger(game, ts, p, hp, ap):
    captured=datetime.now(HK)
    if captured>=ts or final(game) or game.get('postponed'): return
    row=dict(id=int(game['id']),tip=ts.isoformat(),captured=captured.isoformat(),home=name(game['home_team']),away=name(game['visitor_team']),probability=float(p),hp=float(hp),ap=float(ap))
    if cloud_config(): cloud_request('POST',json=row,params={'on_conflict':'id'}); return
    with sqlite3.connect(os.environ.get('NBA_LEDGER','nba_predictions.sqlite'),timeout=10) as db:
        db.execute('CREATE TABLE IF NOT EXISTS predictions(id INTEGER PRIMARY KEY, tip TEXT, captured TEXT, home TEXT, away TEXT, probability REAL, hp REAL, ap REAL, actual INTEGER)')
        db.execute('INSERT OR IGNORE INTO predictions VALUES(?,?,?,?,?,?,?,?,NULL)',tuple(row.values()))

def ledger_results(rows):
    cols=['id','tip','captured','home','away','probability','hp','ap','actual']
    if cloud_config():
        records=[]
        for offset in range(0,100000,500):
            page=cloud_request('GET',params={'select':'*','order':'id.asc','limit':500,'offset':offset}).json(); records.extend(page)
            if len(page)<500: break
        else: raise ValueError('雲端紀錄超過讀取上限')
        pending={r['id'] for r in records if r.get('actual') is None}
        for g in rows:
            if g.get('id') in pending and final(g) and g.get('home_team_score') and g.get('visitor_team_score'):
                actual=int(g['home_team_score']>g['visitor_team_score']); cloud_request('PATCH',params={'id':'eq.'+str(g['id'])},json={'actual':actual})
                for r in records:
                    if r['id']==g['id']: r['actual']=actual; break
        return pd.DataFrame(records,columns=cols).sort_values('tip',ascending=False)
    with sqlite3.connect(os.environ.get('NBA_LEDGER','nba_predictions.sqlite'),timeout=10) as db:
        db.execute('CREATE TABLE IF NOT EXISTS predictions(id INTEGER PRIMARY KEY, tip TEXT, captured TEXT, home TEXT, away TEXT, probability REAL, hp REAL, ap REAL, actual INTEGER)')
        for g in rows:
            if final(g) and g.get('home_team_score') and g.get('visitor_team_score'):
                db.execute('UPDATE predictions SET actual=? WHERE id=?',(int(g['home_team_score']>g['visitor_team_score']),g['id']))
        return pd.read_sql_query('SELECT * FROM predictions ORDER BY tip DESC',db)

class ProbabilityAdjustedModel:
    """A fitted classifier with a conservative validation-chosen probability shrink."""
    def __init__(self, base, shrink=1.0):
        self.base = base
        self.shrink = float(shrink)

    def predict_proba(self, X):
        raw = self.base.predict_proba(X)
        p = np.clip(0.5 + self.shrink * (raw[:, 1] - 0.5), 0.001, 0.999)
        return np.column_stack((1-p, p))


@st.cache_resource(show_spinner=False,max_entries=4)
def train(rows):
    clean=[]; seen=set()
    for g in rows:
        if not final(g) or g.get('id') in seen: continue
        try:
            ts=stamp(g); d=ts.tz_convert(ET).date() if not pd.isna(ts) else pd.Timestamp(g['date']).date()
            h=g['home_team']['id']; a=g['visitor_team']['id']; hp=int(g['home_team_score']); ap=int(g['visitor_team_score'])
            if hp<=0 or ap<=0 or hp==ap: continue
        except (KeyError,TypeError,ValueError): continue
        seen.add(g['id']); clean.append((d,h,a,hp,ap))
    clean.sort(); hist=defaultdict(list); X=[]; Y=[]; days=[]
    for day in sorted({r[0] for r in clean}):
        batch=[r for r in clean if r[0]==day]
        for _,h,a,hp,ap in batch:
            x=features(hist,h,a,day)
            if x is not None: X.append(x); Y.append([int(hp>ap),hp,ap]); days.append(day)
        # Same-day games use a frozen pre-day Elo snapshot; no intra-day leakage.
        pre_day_elo = {tid: elo_rating(rec) for tid,rec in hist.items()}
        for _,h,a,hp,ap in batch:
            eh,ea=pre_day_elo.get(h,1500.0),pre_day_elo.get(a,1500.0)
            expected=1/(1+10**((ea-eh-65)/400)); change=20*(int(hp>ap)-expected)
            hist[h].append((day,hp,ap,int(hp>ap),1,eh+change)); hist[a].append((day,ap,hp,int(ap>hp),0,ea-change))
    if len(X)<200: raise ValueError('有效歷史樣本不足 200 場')
    X=np.array(X); Y=np.array(Y)
    boundary=days[int(len(X)*.8)]; split=sum(d<boundary for d in days)
    valday=days[int(len(X)*.65)]; val=sum(d<valday for d in days)
    if val < 100 or split-val < 30 or len(X)-split < 30:
        raise ValueError('時間切分後樣本不足，暫不顯示不可靠的回測')
    classifiers={'Logistic Regression':make_pipeline(StandardScaler(),LogisticRegression(max_iter=500)), 'Random Forest':RandomForestClassifier(n_estimators=80,max_depth=8,min_samples_leaf=12,n_jobs=1,random_state=42)}
    regressors={'Ridge':make_pipeline(StandardScaler(),Ridge(alpha=10)), 'Random Forest':RandomForestRegressor(n_estimators=80,max_depth=9,min_samples_leaf=10,n_jobs=1,random_state=42)}
    classifiers['HistGradientBoosting']=HistGradientBoostingClassifier(max_iter=100,max_leaf_nodes=15,l2_regularization=2,random_state=42)
    classifiers['Logistic L2 強正則']=make_pipeline(StandardScaler(),LogisticRegression(C=.1,max_iter=500))
    regressors['HistGradientBoosting']=MultiOutputRegressor(HistGradientBoostingRegressor(max_iter=100,max_leaf_nodes=15,l2_regularization=5,random_state=42))
    classifiers["融合模型"]=VotingClassifier([(str(i),clone(m)) for i,m in enumerate(classifiers.values())],voting="soft")
    metrics=[]
    calibration={}
    # Choose the model and conservative calibration on the validation window only.
    # Never tune against the final chronological test window.
    for n,m in classifiers.items():
        m.fit(X[:val],Y[:val,0]); raw=m.predict_proba(X[val:split])[:,1]
        options=[(brier_score_loss(Y[val:split,0],np.clip(.5+k*(raw-.5),.001,.999)),k) for k in (0.65,0.8,1.0)]
        best_brier,shrink=min(options)
        calibration[n]=shrink
        metrics.append({'模型':n,'準確率':accuracy_score(Y[val:split,0],raw>=.5),'Brier':best_brier,'勝率縮放':shrink})
    scores=[]
    for n,m in regressors.items():
        m.fit(X[:val],Y[:val,1:]); p=m.predict(X[val:split]); scores.append({'模型':n,'主隊 MAE':mean_absolute_error(Y[val:split,1],p[:,0]),'客隊 MAE':mean_absolute_error(Y[val:split,2],p[:,1])})
    cn=min(metrics,key=lambda r:r['Brier'])['模型']; rn=min(scores,key=lambda r:r['主隊 MAE']+r['客隊 MAE'])['模型']
    c=ProbabilityAdjustedModel(classifiers[cn].fit(X[:split],Y[:split,0]),calibration[cn])
    reg=regressors[rn].fit(X[:split],Y[:split,1:])
    pp=c.predict_proba(X[split:])[:,1]; ss=reg.predict(X[split:]); actual=Y[split:,0]
    audit=pd.DataFrame({"日期":days[split:],"主隊預測勝率":pp,"主隊實際勝出":actual,"預測正確":(pp>=.5)==actual})
    audit['預測主客分差']=ss[:,0]-ss[:,1]
    audit['實際主客分差']=Y[split:,1]-Y[split:,2]
    audit['分差絕對誤差']=(audit['預測主客分差']-audit['實際主客分差']).abs()
    report=(accuracy_score(actual,pp>=.5),brier_score_loss(actual,pp),mean_absolute_error(Y[split:,1],ss[:,0]),mean_absolute_error(Y[split:,2],ss[:,1]),audit)
    residuals=Y[split:,1:]-ss
    c.base.fit(X,Y[:,0]); reg.fit(X,Y[:,1:])
    return c,reg,hist,metrics,scores,len(X),clean[-1][0],cn,rn,boundary,report,residuals

ET=ZoneInfo('America/New_York')
TEAMS=['Atlanta Hawks','Boston Celtics','Brooklyn Nets','Charlotte Hornets','Chicago Bulls','Cleveland Cavaliers','Dallas Mavericks','Denver Nuggets','Detroit Pistons','Golden State Warriors','Houston Rockets','Indiana Pacers','LA Clippers','Los Angeles Lakers','Memphis Grizzlies','Miami Heat','Milwaukee Bucks','Minnesota Timberwolves','New Orleans Pelicans','New York Knicks','Oklahoma City Thunder','Orlando Magic','Philadelphia 76ers','Phoenix Suns','Portland Trail Blazers','Sacramento Kings','San Antonio Spurs','Toronto Raptors','Utah Jazz','Washington Wizards']
STATUS=re.compile(r'\b(Out|Doubtful|Questionable|Probable|Available)\b')
MATCH=re.compile(r'\b([A-Z]{2,3})\s*@\s*([A-Z]{2,3})\b')
FILE=re.compile(r'Injury-Report_(\d{4}-\d{2}-\d{2})_(\d{2})_(\d{2})(AM|PM)\.pdf',re.I)
def parse_report(blob):
    records=[]; team=None; matchup=None; game_date=None; last=None
    with pdfplumber.open(io.BytesIO(blob)) as pdf:
        for page in pdf.pages:
            for line in (page.extract_text(x_tolerance=2,y_tolerance=3) or '').splitlines():
                line=' '.join(line.split())
                dm=re.search(r'\b(\d{2}/\d{2}/\d{4})\b',line)
                if dm: game_date=datetime.strptime(dm.group(1),'%m/%d/%Y').date()
                mm=MATCH.search(line)
                if mm: matchup='@'.join(mm.groups()); team=None; last=None
                found=next((t for t in TEAMS if t in line),None)
                if found: team=found; line=line.split(found,1)[1].strip(); last=None
                if not team or not matchup or not game_date: continue
                special=re.search(r'NOT YET SUBMITTED|NOT SUBMITTED|NONE',line,re.I)
                if special:
                    records.append(dict(team=team,matchup=matchup,date=game_date,player='',status=special.group().upper(),reason='')); last=None; continue
                m=STATUS.search(line)
                if m:
                    player=line[:m.start()].strip(' -'); reason=line[m.end():].strip(' -')
                    if ',' not in player: continue
                    last=dict(team=team,matchup=matchup,date=game_date,player=player,status=m.group(),reason=reason); records.append(last)
                elif last and line and not re.search(r'Page|Injury Report|Game Date|Current Status',line,re.I) and not mm and not dm and not found:
                    last['reason']+=' '+line
    if not records: raise ValueError('官方 PDF 未能辨識，可能需要更新解析器')
    return records
@st.cache_data(ttl=300,show_spinner=False)
def official_report(season):
    url=f'https://official.nba.com/nba-injury-report-{season}-{str(season+1)[-2:]}-season/'
    headers={'User-Agent':'Mozilla/5.0 NBA injury report reader'}
    r=requests.get(url,headers=headers,timeout=20); r.raise_for_status()
    candidates=[]
    for a in BeautifulSoup(r.text,'html.parser').find_all('a',href=True):
        link=urljoin(url,a['href']); m=FILE.search(link)
        if not m or urlparse(link).hostname not in ('ak-static.cms.nba.com','official.nba.com','cdn.nba.com'): continue
        d,h,mi,ap=m.groups(); ts=datetime.strptime(f'{d} {h}:{mi}{ap.upper()}','%Y-%m-%d %I:%M%p').replace(tzinfo=ET)
        if ts<=datetime.now(ET): candidates.append((ts,link))
    if not candidates: raise ValueError('官方網站未找到可辨識 PDF 連結')
    ts,link=max(candidates); r=requests.get(link,headers=headers,timeout=30); r.raise_for_status()
    return parse_report(r.content),ts.astimezone(HK),link,datetime.now(HK)

def background_job():
    key=os.environ['BDL_API_KEY']
    if not cloud_config(): raise RuntimeError('Cloud credentials required')
    now=datetime.now(HK); day=now.date(); season=day.year if day.month>=9 else day.year-1
    games,_=fetch(key,'games',tuple(('dates[]',(day+timedelta(days=i)).isoformat()) for i in range(-3,3)))
    records=ledger_results(games)
    # Explicitly fetch older pending games, including postponed games.
    pending=records[records.actual.isna() & (pd.to_datetime(records.tip,utc=True,errors='coerce') < pd.Timestamp(now)-pd.Timedelta(hours=4))]
    known={g.get('id') for g in games}
    for gid in pending.id.tolist():
        if gid in known: continue
        detail,_=fetch_cached(key,BASE,'games/'+str(int(gid)),(),worker=True,ttl=600)
        ledger_results(detail)
    upcoming=[g for g in games if not pd.isna(stamp(g)) and now<stamp(g)<=now+timedelta(hours=30) and not final(g) and not g.get('postponed') and g['id'] not in set(records.id)]
    rows,_=history(key,season)
    publish_history_snapshot(season,rows)
    if upcoming:
        model=train(rows); c,reg,hist,*_=model
        for g in upcoming:
            ts=stamp(g).tz_convert(HK); gd=ts.tz_convert(ET).date()
            x=features(hist,g['home_team']['id'],g['visitor_team']['id'],gd)
            if x is None or not 0<=(gd-model[6]).days<=14: continue
            prob=float(c.predict_proba([x])[0,1]); hp,ap=reg.predict([x])[0]
            ledger(g,ts,prob,hp,ap)
    print('Scheduled run completed; cloud ledger checked.')

if os.environ.get('NBA_WORKER'):
    raise SystemExit('Beta worker disabled')

# Use Streamlit native theme rather than conflicting global CSS.

st.title('NBA AI Prediction Platform V8.0 Beta')
st.warning('獨立測試版：沿用原有模型；AXLE 新模型尚未完成正式驗收。永久儲存及正式資料庫接駁停用。')
st.caption('香港時間｜GitHub Actions 共用歷史資料｜每日賽事預測｜傷兵風險')
def configured_key():
    for field in ('BDL_API_KEY','BALLDONTLIE_API_KEY'):
        value=os.environ.get(field)
        if value and value.strip(): return value.strip()
        try:
            value=st.secrets.get(field,'')
            if value and str(value).strip(): return str(value).strip()
        except Exception: pass
    return ''
saved=configured_key()
with st.sidebar:
    key=saved or st.text_input('BALLDONTLIE API Key',type='password',key='manual_api_key').strip()
    if saved: st.success('已自動載入 API Key')
    else: st.caption('可在 Streamlit Secrets 設定 BDL_API_KEY，免重複輸入。')
    auto=st.checkbox('每 10 分鐘更新畫面',True)
    st.caption('賽程快取每 10 分鐘更新；限流時保留上次資料。')
    st.markdown('[API 申請](https://app.balldontlie.io/)')


def render_ledger(now):
    st.caption('雲端模式：排程需另啟用。匯入請使用自己先前匯出的原始 CSV。' if cloud_config() else '尚未設定雲端，請先備份 CSV。')
    # Import is deliberately disabled on public UI; use owner-only migration workflow.
    try:
        log=ledger_results([]); done=log.dropna(subset=['actual']); st.metric('已結算命中率',f"{((done.probability>=.5)==done.actual.astype(bool)).mean():.1%}" if len(done) else '尚無'); st.dataframe(log.assign(tip=pd.to_datetime(log.tip,utc=True,errors='coerce').dt.tz_convert(HK).dt.strftime('%Y-%m-%d %H:%M HKT'),captured=pd.to_datetime(log.captured,utc=True,errors='coerce').dt.tz_convert(HK).dt.strftime('%Y-%m-%d %H:%M HKT')).rename(columns={'id':'賽事編號','tip':'開賽時間','captured':'預測時間','home':'主隊','away':'客隊','probability':'主隊勝率','hp':'主隊預測分','ap':'客隊預測分','actual':'主隊實際勝出'}),hide_index=True,width='stretch'); st.download_button('匯出預測紀錄',log.to_csv(index=False).encode('utf-8-sig'),'predictions.csv','text/csv'); st.caption('已讀取 '+str(len(log))+' 筆紀錄'); st.caption('雲端資料庫讀取成功' if cloud_config() else '本機暫存模式：重新部署可能遺失，請匯出。'); dates=pd.to_datetime(done['tip'],utc=True,errors='coerce'); cc=st.columns(3)
        for col,n in zip(cc,[7,30,None]):
            subset=done if n is None else done[dates>=pd.Timestamp(now)-pd.Timedelta(days=n)]
            col.metric(('全部' if n is None else f'近 {n} 天')+'命中率',f'{((subset.probability>=.5)==subset.actual.astype(bool)).mean():.1%}' if len(subset) else '尚無',f'{len(subset)} 場',delta_color='off')
    except Exception as e: st.warning(str(e))


@st.fragment(run_every=600 if auto else None)
def dashboard():
    now=datetime.now(HK); today=now.date(); season=today.year if today.month>=9 else today.year-1
    labels=['每日賽程與預測','傷兵中心','球員搜尋','模型評估','Elo 排名','預測紀錄','公開賠率 API 比較']
    page=st.radio('功能選擇',labels,index=0,horizontal=True,label_visibility='collapsed')
    if page==labels[5]:
        st.info('Beta 預測紀錄及永久儲存暫停。'); return
    if not key: st.info('請設定 BALLDONTLIE API Key。'); return
    day=st.date_input('比賽日期（香港時間）',today)
    games=[]; updated=''
    try:
        if page in (labels[0],labels[1],labels[6]): games,updated=fetch(key,'games',tuple(('dates[]',d.isoformat()) for d in [day-timedelta(days=1),day,day+timedelta(days=1)]))
        games=sorted([g for g in games if not pd.isna(stamp(g)) and stamp(g).tz_convert(HK).date()==day],key=stamp)
    except Exception as e: st.error(f'賽程讀取失敗：{e}'); return
    if updated:
        st.caption('賽程資料取得時間：'+updated)
        if now-pd.Timestamp(updated)>pd.Timedelta(minutes=10): st.warning('目前顯示快取賽程，並非即時資料。')
    injuries=[]; injury_ok=False; injury_error=''; injury_time=None; injury_url=''; read_time=None
    if games and page in (labels[0],labels[1]):
        try: injuries,injury_time,injury_url,read_time=official_report(season); injury_ok=True
        except Exception as e: injury_error=str(e)
    def related(g,t):
        match=g['visitor_team']['abbreviation']+'@'+g['home_team']['abbreviation']
        gd=stamp(g).tz_convert(ET).date()
        return [r for r in injuries if r['date']==gd and r['matchup']==match and r['team']==name(t)]
    def impact(g,t):
        rr=related(g,t)
        if not injury_ok or not rr or any('SUBMITTED' in r['status'] for r in rr) or (now-injury_time).total_seconds()>21600: return None
        weights={'Out':1.,'Doubtful':.75,'Questionable':.5,'Probable':.25,'Available':0.}
        return sum(weights.get(r['status'],0) for r in rr if r['player'] and not re.search(r'g[ -]?league|two.way|on assignment',r['reason'],re.I))
    def risk(g,t):
        if not injury_ok: return '未能查核'
        rr=related(g,t)
        if not rr or any('SUBMITTED' in r['status'] for r in rr): return '未提交或未能配對'
        ss=[r['status'] for r in rr if not r['reason'].lower().startswith('g league')]
        return f'Out {ss.count("Out")} / Doubtful {ss.count("Doubtful")} / Questionable {ss.count("Questionable")}（非健康確認）'
    model=None; rows=[]; history_time=''; error=''
    if page in (labels[0],labels[3],labels[4],labels[6]):
        try:
            with st.spinner('讀取歷史資料及快取模型…'):
                rows,history_time=shared_history(season); model=train(rows)
        except Exception as e: error=str(e)
        if error and page!=labels[0]: st.warning('模型暫不可用：'+error)
    from cloud_accuracy import load, settle, probabilities
    from odds_api import load_snapshot, match_event, best_market, home_spread, total_market
    public_odds=load_snapshot() if page in (labels[0],labels[6]) else None
    cloud_odds=[]
    # The daily prediction page also needs saved Pinnacle spreads.
    # Only the odds page performs settlement; daily predictions read snapshots only.
    if page in (labels[0],labels[6]) and cloud_config():
        try:
            cloud_odds=load(cloud_config())
            if page==labels[6]:
                cloud_odds=settle(cloud_config(),cloud_odds,(rows if model else [])+games,final)
        except Exception as e:
            st.warning('Pinnacle 雲端快照讀取／結算失敗：'+str(e))
    if page==labels[0]:
        if error: st.warning('模型暫不可用：'+error+'。請先確認 GitHub Actions 已完成背景歷史資料發布。')
        if model: st.caption(f'歷史資料截至 {model[6]}（美東賽事日期）；讀取時間 {history_time}；預測只使用賽前資料')
        if not games: st.info('該日期沒有已取得的賽事。')
        for g in games:
            h=g['home_team']; a=g['visitor_team']; ts=stamp(g).tz_convert(HK)
            with st.container(border=True):
                st.caption(f'{ts:%Y-%m-%d %H:%M} HKT · {g.get("status", "未知")}')
                is_final = final(g)
                if is_final and g.get('visitor_team_score') is not None and g.get('home_team_score') is not None:
                    away_score = int(g['visitor_team_score'])
                    home_score = int(g['home_team_score'])
                    st.subheader(f'{display_team(a)} {away_score} @ {display_team(h)} {home_score}')
                else:
                    st.subheader(f'{display_team(a)} @ {display_team(h)}')
                logo_left, logo_right = st.columns(2)
                show_team_logo(logo_left, a)
                show_team_logo(logo_right, h)
                if is_final:
                    if g.get('visitor_team_score') is not None and g.get('home_team_score') is not None:
                        away_result = '勝方' if away_score > home_score else ('平手' if away_score == home_score else '落敗')
                        home_result = '勝方' if home_score > away_score else ('平手' if home_score == away_score else '落敗')
                        score_left, score_right = st.columns(2)
                        score_left.metric(f'客隊 · {display_team(a)}', f'{away_score} 分', away_result, delta_color='off')
                        score_right.metric(f'主隊 · {display_team(h)}', f'{home_score} 分', home_result, delta_color='off')
                    else:
                        st.warning('賽事已完場，但比分資料尚未完整提供。')
                elif ts<=now or g.get('postponed'): st.write('已到開賽時間或延期；不產生賽前預測。')
                elif model:
                    c,reg,hist,*_=model
                    x=features(hist,h['id'],a['id'],ts.tz_convert(ET).date())
                    stale=(ts.tz_convert(ET).date()-model[6]).days>14
                    if x is None or stale: st.warning('近期資料不足或過舊，暫不預測。')
                    else:
                        p=float(c.predict_proba([x])[0,1]); hp,ap=reg.predict([x])[0]
                        l,r=st.columns(2)
                        l.metric(display_team(a),f'{ap:.0f} 分')
                        r.metric(display_team(h),f'{hp:.0f} 分')
                        st.markdown('**AI 獨贏勝率**')
                        left,right=st.columns(2)
                        left.write(f'{display_team(a)}（客隊）：{1-p:.1%}')
                        right.write(f'{display_team(h)}（主隊）：{p:.1%}')
                        st.markdown(f'<div style="display:flex;height:14px;border-radius:7px;overflow:hidden"><div style="width:{(1-p)*100:.6f}%;background:#3785ce"></div><div style="width:{p*100:.6f}%;background:#259569"></div></div>',unsafe_allow_html=True)
                        st.write('預測勝方：'+name(h if p>=.5 else a))
                        
                        # V7.9：AI 信心分級（實驗性）
                        higher_win_prob = max(float(p), 1.0 - float(p))

                        if higher_win_prob >= 0.75:
                            confidence_level = '高'
                        elif higher_win_prob >= 0.60:
                            confidence_level = '中'
                        else:
                            confidence_level = '低'

                        st.info(
                            f'AI 模型信心（實驗性）：{confidence_level} | '
                            f'較高一方原始預測勝率 {higher_win_prob:.1%}'
                        )
                        st.caption(
                            '分級門檻：低 50–<60%；中 60–<75%；高 ≥75%。'
                            '這只描述模型輸出強度，並非真實勝率、'
                            '可靠性認證或投注風險評級。'
                        )

                        
                
     

                        try: ledger(g,ts,p,hp,ap)
                        except Exception as e: st.caption('預測紀錄未保存：'+str(e))
                        draws=simulate(hp,ap,model[11],int(g['id']))
                        with st.expander('10,000 次比分模擬',expanded=True):
                            lo,hi=np.quantile(draws,[.1,.9],axis=0); total=draws.sum(axis=1); tl,th=np.quantile(total,[.1,.9]); mc=(np.sum(draws[:,0]>draws[:,1])+.5*np.sum(draws[:,0]==draws[:,1]))/len(draws)
                            st.write(f'主隊比分 80% 模擬區間：{lo[0]:.0f}–{hi[0]:.0f}；客隊：{lo[1]:.0f}–{hi[1]:.0f}')
                            st.write(f'預測總分：{hp+ap:.1f}；80% 模擬區間 {tl:.0f}–{th:.0f}；模擬主勝率 {mc:.1%}')
                            counts,edges=np.histogram(total,bins=20); st.bar_chart(pd.DataFrame({"總分":edges[:-1].astype(int),"次數":counts}).set_index("總分"))
                            st.caption('以歷史測試比分殘差成對抽樣；非保證覆蓋率，模擬勝率獨立於分類模型。')
                        st.markdown('**AI 全場大小分 Over／Under 機率**')
                        ou_quote = None
                        if public_odds:
                            event_ou = match_event(g, public_odds.get('events', []))
                            if event_ou:
                                book_ou, markets_ou = best_market(event_ou)
                                if markets_ou:
                                    candidate = total_market(markets_ou.get('totals'))
                                    try:
                                        fetched_ou = pd.to_datetime(public_odds['retrieved_at_utc'], utc=True)
                                        age_ou = pd.Timestamp(now) - fetched_ou
                                        if (candidate and pd.Timedelta(0) <= age_ou <= pd.Timedelta(hours=12)
                                                and fetched_ou < ts):
                                            ou_quote = (candidate, fetched_ou, book_ou.get('title', '未知'))
                                    except (KeyError, TypeError, ValueError):
                                        pass
                        if ou_quote:
                            quote_ou, fetched_ou, book_title_ou = ou_quote
                            line_ou = quote_ou['line']
                            totals_ou = draws.sum(axis=1)
                            over_ou = float(np.mean(totals_ou > line_ou))
                            under_ou = float(np.mean(totals_ou < line_ou))
                            push_ou = float(np.mean(totals_ou == line_ou))
                            over_col, under_col = st.columns(2)
                            over_col.metric(f'Over {line_ou:g}', f'{over_ou:.1%}')
                            under_col.metric(f'Under {line_ou:g}', f'{under_ou:.1%}')
                            st.write(f'AI 預測總分 {hp+ap:.1f}｜市場盤口 {line_ou:g}｜差距 {hp+ap-line_ou:+.1f} 分')
                            st.caption(f'The Odds API / {book_title_ou}；快照 {fetched_ou.tz_convert(HK):%Y-%m-%d %H:%M} HKT；走盤 {push_ou:.1%}。'
                                       '機率由 10,000 次歷史測試比分殘差模擬估算，未以歷史大小分盤口校準，並非已驗證的投注勝率。')
                        else:
                            st.caption('暫無已配對且 12 小時內更新的賽前全場大小分盤口，故不顯示 Over／Under 機率。')
                        st.markdown('**AI 讓分勝率**')
                        saved=[]
                        if public_odds:
                            event=match_event(g,public_odds['events'])
                            if event:
                                bookmaker,markets=best_market(event)
                                if markets:
                                    line=home_spread(markets['spreads'],name(h))
                                    try:
                                        captured=pd.Timestamp(public_odds['retrieved_at_utc'])
                                        if line is not None and captured<ts and captured<=pd.Timestamp(now):
                                            saved.append((captured,float(line),'The Odds API / '+str(bookmaker.get('title','?'))))
                                    except (ValueError,TypeError,KeyError): pass
                        for row in ([{'匯入時間':r['captured'],'主隊讓分':r['home_spread'],'賽事ID':r['game_id']} for r in cloud_odds]+st.session_state.get('pinnacle_rows',[])):
                            try:
                                captured=pd.to_datetime(row['匯入時間'],utc=True)
                                line=float(row['主隊讓分'])
                                if str(row['賽事ID'])==str(g['id']) and np.isfinite(line) and captured<=pd.Timestamp(now) and captured<ts:
                                    saved.append((captured,line,'Pinnacle historical'))
                            except (ValueError,TypeError,KeyError,OverflowError):
                                continue
                        if saved:
                            captured,line,source=max(saved,key=lambda v:v[0])
                            adjusted=draws[:,0]-draws[:,1]+line
                            cc=st.columns(2)
                            cc[0].metric(f'{display_team(h)} ({line:+g})',f'{np.mean(adjusted>0):.1%}')
                            cc[1].metric(f'{display_team(a)} ({-line:+g})',f'{np.mean(adjusted<0):.1%}')
                            st.caption(f'{source} 賠率快照 {captured.tz_convert(HK):%Y-%m-%d %H:%M} HKT；走盤 {np.mean(adjusted==0):.1%}。模擬比例未經歷史盤口校準；未單獨模擬加時。')
                        else:
                            st.caption('暫無已配對的賽前讓分資料；請檢查公開賠率 API 比較頁及最近一次 GitHub Actions 更新。')
                        with st.expander('近期戰績、主客場及休息分析',expanded=True):
                            details=[]
                            for t,loc in [(a,0),(h,1)]:
                                rec=hist[t['id']]; gap=(ts.tz_convert(ET).date()-rec[-1][0]).days
                                venue=[r for r in rec if r[4]==loc][-10:]
                                details.append({'球隊':name(t),'Elo':round(elo_rating(rec)), '近5場勝率':f'{np.mean([r[3] for r in rec[-5:]]):.0%}','近10場勝率':f'{np.mean([r[3] for r in rec[-10:]]):.0%}','近10場得分':round(np.mean([r[1] for r in rec[-10:]]),1),'近10場失分':round(np.mean([r[2] for r in rec[-10:]]),1),'相同主客場勝率':f'{np.mean([r[3] for r in venue]):.0%}' if venue else '不足','休息日':max(0,gap-1),'背靠背':'是' if gap==1 else '否'})
                            st.dataframe(details,width='stretch',hide_index=True)
                        with st.expander('歷史交手與球隊得失分分析'):
                            matches=[]
                            for old in rows:
                                if final(old) and not pd.isna(stamp(old)) and stamp(old)<stamp(g) and {old['home_team']['id'],old['visitor_team']['id']}=={h['id'],a['id']}:
                                    matches.append(old)
                            matches=sorted(matches,key=stamp,reverse=True)[:10]
                            st.dataframe([{'日期':stamp(o).tz_convert(HK).strftime('%Y-%m-%d'),'主隊':name(o['home_team']),'客隊':name(o['visitor_team']),'主隊得分':o['home_team_score'],'客隊得分':o['visitor_team_score']} for o in matches],hide_index=True)
                            st.caption('得失分並非每百回合攻防效率；免費賽果資料不足以計算真實 Pace。')
                        with st.expander('官方球員缺陣清單'):
                            st.dataframe([{'球隊':r['team'],'球員':r['player'],'狀態':r['status'],'原因':r['reason']} for t in (a,h) for r in related(g,t)],hide_index=True)
                            st.caption('未具備歷史球員出勤及貢獻資料，不推算球星個別勝率影響。')
                        st.caption(f'模型勝率距離五五波：{abs(p-.5):.1%}（不等於可靠度）')
                        ih,ia=impact(g,h),impact(g,a)
                        if ih is not None and ia is not None:
                            # Explicit unvalidated scenario, not learned player contribution.
                            delta=float(np.clip(ia-ih,-5,5)); adj=float(np.clip(p+.015*delta,.01,.99))
                            st.write(f'傷兵情境（示範）：主隊 {adj:.1%}｜客隊 {1-adj:.1%}；主隊勝率變動 {(adj-p)*100:+.1f} 個百分點')
                            st.caption('假設每單位缺陣風險改變 1.5 個百分點，上限 7.5；非回測校準，不改正式預測或比分。')
                        else: st.info('傷兵報告未完整或過期，不計算調整情境。')
                st.caption(f'客隊傷兵：{risk(g,a)}｜主隊傷兵：{risk(g,h)}（原始模型未納入傷兵）')
    if page==labels[1]:
        st.markdown(f'[NBA 官方傷兵報告](https://official.nba.com/nba-injury-report-{season}-{str(season+1)[-2:]}-season/)')
        if not injury_ok: st.warning('傷兵資料未能查核：'+(injury_error or '沒有當日賽程'))
        else:
            st.caption(f'官方發布時間：{injury_time:%Y-%m-%d %H:%M} HKT｜讀取：{read_time:%Y-%m-%d %H:%M} HKT')
            st.markdown(f'[查看原始 PDF]({injury_url})')
            if (now-injury_time).total_seconds()>21600: st.warning('官方報告已超過六小時，請注意時效。')
            display=[]
            for g in games:
                for t in (g['visitor_team'],g['home_team']):
                    rr=related(g,t)
                    if not rr: display.append({'球隊':name(t),'狀態':'未能配對／未列出','球員':'','原因':''})
                    for r in rr: display.append({'球隊':r['team'],'球員':r['player'],'狀態':r['status'],'原因':r['reason']})
            st.dataframe(display,width='stretch',hide_index=True)
            st.caption('只顯示所選賽事配對結果；未列出不代表健康。傷兵風險獨立顯示，未經歷史傷兵資料驗證，不調整模型勝率。')
    if page==labels[2]:
        q=st.text_input('球員英文名稱')
        if q.strip():
            try:
                players,_=fetch(key,'players',(('search',q.strip()),))
                if not players and ' ' in q.strip():
                    players,_=fetch(key,'players',(('search',q.strip().split()[-1]),)); players=[p for p in players if q.strip().casefold() in (p.get('first_name','')+' '+p.get('last_name','')).casefold()]
                st.dataframe([{'球員':p.get('first_name','')+' '+p.get('last_name',''),'球隊':name(p.get('team') or {}),'位置':p.get('position')} for p in players],width='stretch')
            except Exception as e: st.warning(str(e))
    if page==labels[3]:
        if model:
            st.write(f'有效樣本：{model[5]}｜測試起始日期：{model[9]}｜採用 {model[7]} / {model[8]}')
            st.dataframe(model[3],width='stretch'); st.dataframe(model[4],width='stretch')
            acc,brier,hmae,amae,audit=model[10]
            st.subheader('獨立歷史測試（最後約 20%）')
            c1,c2,c3=st.columns(3); c1.metric('勝方準確率',f'{acc:.1%}'); c2.metric('Brier',f'{brier:.3f}'); c3.metric('比分 MAE',f'{hmae:.1f} / {amae:.1f}')
            baseline=max(audit['主隊實際勝出'].mean(),1-audit['主隊實際勝出'].mean())
            st.write(f'獨立測試場數：{len(audit)}｜主隊全選基準：{audit["主隊實際勝出"].mean():.1%}｜較佳固定選邊基準：{baseline:.1%}')
            st.caption('勝率縮放只在驗證集選擇，獨立測試集不參與調參。是否真正改善需與相同測試日期的 V7.6 比較。')
            cal=audit.copy(); cal['機率區間']=pd.cut(cal['主隊預測勝率'],bins=np.linspace(0,1,11),include_lowest=True).astype(str)
            st.metric('獨立測試分差 MAE',f'{audit["分差絕對誤差"].mean():.2f} 分')
            st.subheader('勝率校準診斷')
            st.dataframe(cal.groupby('機率區間').agg(場數=('主隊實際勝出','size'),平均預測=('主隊預測勝率','mean'),實際主勝率=('主隊實際勝出','mean')).reset_index(),hide_index=True)
            st.line_chart(audit.assign(累積準確率=audit['預測正確'].expanding().mean()).reset_index(drop=True)['累積準確率'])
            st.download_button('下載歷史回測結果',audit.to_csv(index=False).encode('utf-8-sig'),'backtest.csv','text/csv')
            st.caption('前約65%訓練、15%選模與勝率縮放、最後20%獨立測試；正式模型再以所有資料訓練。這是歷史回測，不是已保存的真實賽前預測。')
        st.caption('模型使用近期 5、10 場得失分、勝率、主客場戰績、休息日、近20場時間加權表現、分差波動及近7日賽程密度。不含歷史傷兵、陣容或盤口。資料由 BALLDONTLIE 提供；預測非投注建議。')
    if page==labels[4]:
        if model:
            teams={t['id']:name(t) for g in rows for t in (g['home_team'],g['visitor_team'])}
            ranking=[{'球隊':teams.get(t,str(t)),'Elo':round(elo_rating(rec))} for t,rec in model[2].items() if rec]
            st.dataframe(pd.DataFrame(ranking).sort_values('Elo',ascending=False),hide_index=True,width='stretch')
            st.caption('Elo 初始1500、K=20、主場優勢65；設定未獨立調優。')
    if page==labels[6]:
        from odds_api import render
        render(games, public_odds, HK)

dashboard()
