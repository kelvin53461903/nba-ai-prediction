import streamlit as st
import pandas as pd
import numpy as np
import requests, time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.metrics import accuracy_score, mean_absolute_error, brier_score_loss

st.set_page_config(page_title='NBA AI V3.0', page_icon='🏀', layout='wide')
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
        for subset in [records[-5:],records[-15:], [r for r in records if r[4]==loc][-10:]]:
            if not subset: subset=records[-5:]
            ar=np.array([r[1:4] for r in subset]); result.extend(ar.mean(axis=0))
        result.append(min(10,max(0,(day-records[-1][0]).days)))
    return result

@st.cache_resource(show_spinner=False,max_entries=4)
def train(rows):
    clean=[]; seen=set()
    for g in rows:
        if not final(g) or g.get('id') in seen: continue
        try:
            ts=stamp(g); d=ts.date() if not pd.isna(ts) else pd.Timestamp(g['date']).date()
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
    X=np.array(X); Y=np.array(Y); boundary=days[int(len(X)*.8)]; split=sum(d<boundary for d in days)
    classifiers={'Logistic Regression':make_pipeline(StandardScaler(),LogisticRegression(max_iter=500)), 'Random Forest':RandomForestClassifier(n_estimators=80,max_depth=8,min_samples_leaf=12,n_jobs=1,random_state=42)}
    regressors={'Ridge':make_pipeline(StandardScaler(),Ridge(alpha=10)), 'Random Forest':RandomForestRegressor(n_estimators=80,max_depth=9,min_samples_leaf=10,n_jobs=1,random_state=42)}
    metrics=[]
    for n,m in classifiers.items():
        m.fit(X[:split],Y[:split,0]); p=m.predict_proba(X[split:])[:,1]; metrics.append({'模型':n,'準確率':accuracy_score(Y[split:,0],p>=.5),'Brier':brier_score_loss(Y[split:,0],p)})
    scores=[]
    for n,m in regressors.items():
        m.fit(X[:split],Y[:split,1:]); p=m.predict(X[split:]); scores.append({'模型':n,'主隊 MAE':mean_absolute_error(Y[split:,1],p[:,0]),'客隊 MAE':mean_absolute_error(Y[split:,2],p[:,1])})
    cn=min(metrics,key=lambda r:r['Brier'])['模型']; rn=min(scores,key=lambda r:r['主隊 MAE']+r['客隊 MAE'])['模型']
    c=classifiers[cn].fit(X,Y[:,0]); reg=regressors[rn].fit(X,Y[:,1:])
    return c,reg,hist,metrics,scores,len(X),clean[-1][0],cn,rn,boundary

st.title('🏀 NBA AI Prediction Platform V3.0')
st.caption('香港時間｜自動歷史資料｜每日賽事預測｜傷兵風險')
try: saved=st.secrets.get('BDL_API_KEY','')
except Exception: saved=''
with st.sidebar:
    key=saved or st.text_input('BALLDONTLIE API Key',type='password')
    auto=st.checkbox('每 10 分鐘更新畫面',True)
    if st.button('立即重新讀取賽程'): fetch.clear()
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
    injuries=[]; injury_ok=False; injury_error=''; injury_time=''
    if games:
        try: injuries,injury_time=fetch(key,'player_injuries',()); injury_ok=True
        except Exception as e: injury_error=str(e)
    def related(tid): return [r for r in injuries if (r.get('player') or {}).get('team_id')==tid or ((r.get('player') or {}).get('team') or {}).get('id')==tid]
    def risk(tid):
        if not injury_ok: return '未能查核'
        rr=related(tid); statuses=[str(r.get('status','')).lower() for r in rr]
        return f'Out {statuses.count("out")} / Doubtful {statuses.count("doubtful")} / Questionable {statuses.count("questionable")}' if rr else '未列出紀錄（非健康確認）'
    model=None; history_time=''; error=''
    try:
        with st.spinner('自動取得歷史賽事並訓練模型；首次使用可能需數分鐘…'):
            rows,history_time=history(key,season); model=train(rows)
    except Exception as e: error=str(e)
    with tabs[0]:
        if error: st.warning('模型暫不可用：'+error)
        if model: st.caption(f'歷史資料截至 {model[6]}（UTC 日期）；讀取時間 {history_time}；預測只使用賽前資料')
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
                    x=features(hist,h['id'],a['id'],ts.tz_convert('UTC').date())
                    stale=(ts.tz_convert('UTC').date()-model[6]).days>14
                    if x is None or stale: st.warning('近期資料不足或過舊，暫不預測。')
                    else:
                        p=float(c.predict_proba([x])[0,1]); hp,ap=reg.predict([x])[0]
                        l,r=st.columns(2); l.metric(name(a),f'{ap:.0f} 分',f'勝率 {1-p:.1%}'); r.metric(name(h),f'{hp:.0f} 分',f'勝率 {p:.1%}'); st.progress(p,text=f'主隊勝率 {p:.1%}'); st.write('預測勝方：'+name(h if p>=.5 else a))
                st.caption(f'客隊傷兵：{risk(a["id"])}｜主隊傷兵：{risk(h["id"])}（未納入勝率）')
    with tabs[1]:
        st.markdown('[NBA 官方傷兵報告](https://official.nba.com/)')
        if not injury_ok: st.warning('傷兵資料未能查核：'+(injury_error or '沒有當日賽程'))
        else:
            st.caption('API 讀取時間：'+injury_time+'（不等於官方發布時間）')
            display=[]
            for r in injuries:
                p=r.get('player') or {}; display.append({'球員':f'{p.get("first_name", "")} {p.get("last_name", "")}','球隊 ID':p.get('team_id'),'狀態':r.get('status'),'說明':r.get('description'),'預計回歸':r.get('return_date')})
            st.dataframe(display,width='stretch',hide_index=True)
            st.caption('未列出球員不代表健康；傷兵數量不是球員影響分數。')
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
            st.caption('按時間切分 80/20；同一測試集用於模型選擇，因此不是獨立最終驗證。Brier 越低越好。')
        st.caption('模型使用近期 5、15 場得失分、勝率、主客場戰績及休息日。不含歷史傷兵、陣容或盤口。資料由 BALLDONTLIE 提供；預測非投注建議。')
dashboard()
