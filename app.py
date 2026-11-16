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
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.metrics import accuracy_score, mean_absolute_error, brier_score_loss

st.set_page_config(page_title='NBA AI V4.0 PRO', page_icon='🏀', layout='wide')
HK=ZoneInfo('Asia/Hong_Kong')
BASE='https://api.balldontlie.io/v1/'
@st.cache_data(ttl=300, show_spinner=False)
def fetch(key, endpoint, pairs):
    rows=[]; cursor=None; seen=set()
    for _ in range(250):
        params=list(pairs)+[('per_page',100)]
        if cursor is not None: params.append(('cursor',cursor))
        for attempt in range(4):
            r=requests.get(BASE+endpoint,params=params,headers={'Authorization':key},timeout=30)
            if r.status_code!=429: break
            if attempt<3: time.sleep(65)
        if r.status_code in (401,403): raise ValueError('API Key 無效或方案未授權此功能。')
        if r.status_code==429: raise ValueError('API 次數限制，請稍後再試。')
        if not r.ok: raise ValueError(f'API 錯誤 HTTP {r.status_code}')
        obj=r.json(); rows.extend(obj['data']); cursor=obj.get('meta',{}).get('next_cursor')
        if cursor is None: return rows, datetime.now(HK).isoformat(timespec='seconds')
        if cursor in seen: raise ValueError('API 分頁異常')
        seen.add(cursor)
    raise ValueError('API 分頁未完整，未使用不完整資料')

@st.cache_data(ttl=21600, show_spinner=False)
def history(key, season):
    return fetch(key,'games',tuple(('seasons[]',s) for s in range(season-2,season+1)))

def stamp(g): return pd.to_datetime(g.get('datetime'),utc=True,errors='coerce')
def name(t): return t.get('full_name',t.get('abbreviation','?'))
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
    return result

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
        for _,h,a,hp,ap in batch:
            hist[h].append((day,hp,ap,int(hp>ap),1)); hist[a].append((day,ap,hp,int(ap>hp),0))
    if len(X)<200: raise ValueError('有效歷史樣本不足 200 場')
    X=np.array(X); Y=np.array(Y); boundary=days[int(len(X)*.8)]; split=sum(d<boundary for d in days); valday=days[int(len(X)*.65)]; val=sum(d<valday for d in days)
    classifiers={'Logistic Regression':make_pipeline(StandardScaler(),LogisticRegression(max_iter=500)), 'Random Forest':RandomForestClassifier(n_estimators=80,max_depth=8,min_samples_leaf=12,n_jobs=1,random_state=42)}
    regressors={'Ridge':make_pipeline(StandardScaler(),Ridge(alpha=10)), 'Random Forest':RandomForestRegressor(n_estimators=80,max_depth=9,min_samples_leaf=10,n_jobs=1,random_state=42)}
    metrics=[]
    for n,m in classifiers.items():
        m.fit(X[:val],Y[:val,0]); p=m.predict_proba(X[val:split])[:,1]; metrics.append({'模型':n,'準確率':accuracy_score(Y[val:split,0],p>=.5),'Brier':brier_score_loss(Y[val:split,0],p)})
    scores=[]
    for n,m in regressors.items():
        m.fit(X[:val],Y[:val,1:]); p=m.predict(X[val:split]); scores.append({'模型':n,'主隊 MAE':mean_absolute_error(Y[val:split,1],p[:,0]),'客隊 MAE':mean_absolute_error(Y[val:split,2],p[:,1])})
    cn=min(metrics,key=lambda r:r['Brier'])['模型']; rn=min(scores,key=lambda r:r['主隊 MAE']+r['客隊 MAE'])['模型']
    c=classifiers[cn].fit(X[:split],Y[:split,0]); reg=regressors[rn].fit(X[:split],Y[:split,1:])
    pp=c.predict_proba(X[split:])[:,1]; ss=reg.predict(X[split:]); actual=Y[split:,0]
    audit=pd.DataFrame({"日期":days[split:],"主隊預測勝率":pp,"主隊實際勝出":actual,"預測正確":(pp>=.5)==actual})
    report=(accuracy_score(actual,pp>=.5),brier_score_loss(actual,pp),mean_absolute_error(Y[split:,1],ss[:,0]),mean_absolute_error(Y[split:,2],ss[:,1]),audit)
    c.fit(X,Y[:,0]); reg.fit(X,Y[:,1:])
    return c,reg,hist,metrics,scores,len(X),clean[-1][0],cn,rn,boundary,report

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

st.title('🏀 NBA AI Prediction Platform V4.0 PRO')
st.caption('香港時間｜自動歷史資料｜每日賽事預測｜傷兵風險')
try: saved=st.secrets.get('BDL_API_KEY','')
except Exception: saved=''
with st.sidebar:
    key=saved or st.text_input('BALLDONTLIE API Key',type='password')
    auto=st.checkbox('每 10 分鐘更新畫面',True)
    if st.button('立即重新讀取賽程'): fetch.clear(); official_report.clear()
    st.markdown('[API 申請](https://app.balldontlie.io/)')
if not key: st.info('請輸入 API Key，毋須上傳 CSV。'); st.stop()

@st.fragment(run_every=600 if auto else None)
def dashboard():
    now=datetime.now(HK); today=now.date(); season=today.year if today.month>=9 else today.year-1
    day=st.date_input('比賽日期（香港時間）',today)
    try:
        games,updated=fetch(key,'games',tuple(('dates[]',d.isoformat()) for d in [day-timedelta(days=1),day,day+timedelta(days=1)]))
        games=sorted([g for g in games if not pd.isna(stamp(g)) and stamp(g).tz_convert(HK).date()==day],key=stamp)
    except Exception as e: st.error(f'賽程讀取失敗：{e}'); return
    st.caption('賽程讀取時間：'+updated)
    tabs=st.tabs(['每日賽程與預測','傷兵中心','球員搜尋','模型評估'])
    injuries=[]; injury_ok=False; injury_error=''; injury_time=None; injury_url=''; read_time=None
    if games:
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
    model=None; history_time=''; error=''
    try:
        with st.spinner('自動取得歷史賽事並訓練模型；首次使用可能需數分鐘…'):
            rows,history_time=history(key,season); model=train(rows)
    except Exception as e: error=str(e)
    with tabs[0]:
        if error: st.warning('模型暫不可用：'+error)
        if model: st.caption(f'歷史資料截至 {model[6]}（美東賽事日期）；讀取時間 {history_time}；預測只使用賽前資料')
        if not games: st.info('該日期沒有已取得的賽事。')
        for g in games:
            h=g['home_team']; a=g['visitor_team']; ts=stamp(g).tz_convert(HK)
            with st.container(border=True):
                st.caption(f'{ts:%Y-%m-%d %H:%M} HKT · {g.get("status", "未知")}')
                st.subheader(f'{name(a)} @ {name(h)}')
                if final(g): st.write(f'完場：{g.get("visitor_team_score")} – {g.get("home_team_score")}')
                elif ts<=now or g.get('postponed'): st.write('已到開賽時間或延期；不產生賽前預測。')
                elif model:
                    c,reg,hist,*_=model
                    x=features(hist,h['id'],a['id'],ts.tz_convert(ET).date())
                    stale=(ts.tz_convert(ET).date()-model[6]).days>14
                    if x is None or stale: st.warning('近期資料不足或過舊，暫不預測。')
                    else:
                        p=float(c.predict_proba([x])[0,1]); hp,ap=reg.predict([x])[0]
                        l,r=st.columns(2); l.metric(name(a),f'{ap:.0f} 分',f'勝率 {1-p:.1%}'); r.metric(name(h),f'{hp:.0f} 分',f'勝率 {p:.1%}'); st.progress(p,text=f'主隊勝率 {p:.1%}'); st.write('預測勝方：'+name(h if p>=.5 else a))
                        with st.expander('近期戰績、主客場及休息分析',expanded=True):
                            details=[]
                            for t,loc in [(a,0),(h,1)]:
                                rec=hist[t['id']]; gap=(ts.tz_convert(ET).date()-rec[-1][0]).days
                                venue=[r for r in rec if r[4]==loc][-10:]
                                details.append({'球隊':name(t),'近5場勝率':f'{np.mean([r[3] for r in rec[-5:]]):.0%}','近10場勝率':f'{np.mean([r[3] for r in rec[-10:]]):.0%}','近10場得分':round(np.mean([r[1] for r in rec[-10:]]),1),'近10場失分':round(np.mean([r[2] for r in rec[-10:]]),1),'相同主客場勝率':f'{np.mean([r[3] for r in venue]):.0%}' if venue else '不足','休息日':max(0,gap-1),'背靠背':'是' if gap==1 else '否'})
                            st.dataframe(details,width='stretch',hide_index=True)
                        st.caption(f'模型勝率距離五五波：{abs(p-.5):.1%}（不等於可靠度）')
                        ih,ia=impact(g,h),impact(g,a)
                        if ih is not None and ia is not None:
                            # Explicit unvalidated scenario, not learned player contribution.
                            delta=float(np.clip(ia-ih,-5,5)); adj=float(np.clip(p+.015*delta,.01,.99))
                            st.write(f'傷兵情境（示範）：主隊 {adj:.1%}｜客隊 {1-adj:.1%}；主隊勝率變動 {(adj-p)*100:+.1f} 個百分點')
                            st.caption('假設每單位缺陣風險改變 1.5 個百分點，上限 7.5；非回測校準，不改正式預測或比分。')
                        else: st.info('傷兵報告未完整或過期，不計算調整情境。')
                st.caption(f'客隊傷兵：{risk(g,a)}｜主隊傷兵：{risk(g,h)}（原始模型未納入傷兵）')
    with tabs[1]:
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
    with tabs[2]:
        q=st.text_input('球員英文名稱')
        if q.strip():
            try:
                players,_=fetch(key,'players',(('search',q.strip()),)); st.dataframe([{'球員':p.get('first_name','')+' '+p.get('last_name',''),'球隊':name(p.get('team') or {}),'位置':p.get('position')} for p in players],width='stretch')
            except Exception as e: st.warning(str(e))
    with tabs[3]:
        if model:
            st.write(f'有效樣本：{model[5]}｜測試起始日期：{model[9]}｜採用 {model[7]} / {model[8]}')
            st.dataframe(model[3],width='stretch'); st.dataframe(model[4],width='stretch')
            acc,brier,hmae,amae,audit=model[10]
            st.subheader('獨立歷史測試（最後約 20%）')
            c1,c2,c3=st.columns(3); c1.metric('勝方準確率',f'{acc:.1%}'); c2.metric('Brier',f'{brier:.3f}'); c3.metric('比分 MAE',f'{hmae:.1f} / {amae:.1f}')
            st.line_chart(audit.assign(累積準確率=audit['預測正確'].expanding().mean()).reset_index(drop=True)['累積準確率'])
            st.download_button('下載歷史回測結果',audit.to_csv(index=False).encode('utf-8-sig'),'backtest.csv','text/csv')
            st.caption('前約65%訓練、15%選模、最後20%獨立測試；正式模型再以所有資料訓練。這是歷史回測，不是已保存的真實賽前預測。')
        st.caption('模型使用近期 5、10 場得失分、勝率、主客場戰績及休息日。不含歷史傷兵、陣容或盤口。資料由 BALLDONTLIE 提供；預測非投注建議。')
dashboard()
