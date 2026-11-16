import streamlit as st
import pandas as pd
from datetime import datetime
from PIL import Image

def render(games, model, now, name, stamp, features, ET, HK):
    st.subheader('DB 體育賠率統計比較')
    st.caption('截圖供人工核對；不連接投注網站，不提供下注建議。')
    upload=st.file_uploader('匯入 DB 體育截圖',type=['png','jpg','jpeg'],key='db_image')
    if upload:
        try: st.image(Image.open(upload),caption='原始截圖（請核對日期、主客隊及全場欄位）',width=400)
        except Exception: st.warning('無法讀取圖片。')
    if not games:
        st.info('請先選擇截圖所屬香港日期。'); return
    if 'db_rows' not in st.session_state: st.session_state.db_rows=[]
    options={str(g['id']):g for g in games}
    selected=st.selectbox('配對賽事',list(options),format_func=lambda k:f"{name(options[k]['visitor_team'])} @ {name(options[k]['home_team'])} · {stamp(options[k]).tz_convert(HK):%H:%M}")
    g=options[selected]; h=g['home_team']; a=g['visitor_team']
    with st.form('db_'+selected):
        st.caption('依照截圖輸入十進制賠率；主客隊按下列標示，不按截圖上下順序。')
        c,d=st.columns(2)
        hm=c.number_input(name(h)+' 獨贏',min_value=1.01,value=None,step=.01,format='%.2f')
        am=d.number_input(name(a)+' 獨贏',min_value=1.01,value=None,step=.01,format='%.2f')
        sp=c.number_input('主隊讓分（負數代表讓分）',value=None,step=.5)
        total=d.number_input('全場大小分界線',min_value=0.,value=None,step=.5)
        verified=st.checkbox('已核對截圖及賽事配對')
        submit=st.form_submit_button('計算及保存本次比較')
    if submit:
        if not verified or any(v is None for v in (hm,am,sp,total)) or total<=0:
            st.warning('請核對並填妥全部欄位。')
        else:
            raw=1/hm+1/am; market=(1/hm)/raw
            row={'賽事ID':selected,'主隊':name(h),'客隊':name(a),'開賽時間':stamp(g).tz_convert(HK).isoformat(),'匯入時間':datetime.now(HK).isoformat(),'主隊賠率':hm,'客隊賠率':am,'市場主勝率':market,'市場客勝率':1-market,'原始隱含率合計':raw,'主隊讓分':sp,'大小分界線':total}
            ts=stamp(g); p=hp=ap=None
            if model and ts>pd.Timestamp(now) and not g.get('postponed') and (ts.tz_convert(ET).date()-model[6]).days<=14:
                c,reg,hist,*_=model
                x=features(hist,h['id'],a['id'],ts.tz_convert(ET).date())
                if x is not None: p=float(c.predict_proba([x])[0,1]); hp,ap=map(float,reg.predict([x])[0])
            row.update({'AI主勝率':p,'AI客勝率':None if p is None else 1-p,'AI預測主客分差':None if hp is None else hp-ap,'AI預測總分':None if hp is None else hp+ap})
            st.session_state.db_rows.append(row)
    backup=st.file_uploader('還原先前匯出的賠率 CSV（目前工作階段）',type=['csv'],key='db_backup')
    if backup is not None and st.button('還原 CSV',key='restore_odds'):
        try:
            restored=pd.read_csv(backup,dtype={'賽事ID':str})
            required={'賽事ID','主隊','客隊','開賽時間','匯入時間','主隊賠率','客隊賠率','市場主勝率','市場客勝率','原始隱含率合計','主隊讓分','大小分界線','AI主勝率','AI客勝率','AI預測主客分差','AI預測總分'}
            if not required.issubset(restored.columns): raise ValueError('CSV 欄位不完整')
            merged=pd.concat([pd.DataFrame(st.session_state.db_rows),restored[list(sorted(required))]],ignore_index=True).drop_duplicates(subset=['賽事ID','匯入時間'],keep='first')
            st.session_state.db_rows=merged.to_dict('records')
            st.success('已還原至目前工作階段')
        except Exception as e: st.warning('還原失敗：'+str(e))
    data=pd.DataFrame(st.session_state.db_rows)
    if not data.empty:
        current=data[data['賽事ID']==selected]
        if len(current):
            r=current.iloc[-1]; st.write('最近匯入：'+r['匯入時間']); st.dataframe(pd.DataFrame({'球隊':[r['主隊'],r['客隊']],'市場隱含勝率（去水）':[r['市場主勝率'],r['市場客勝率']],'AI勝率':[r['AI主勝率'],r['AI客勝率']]}),hide_index=True,column_config={'市場隱含勝率（去水）':st.column_config.NumberColumn(format='percent'),'AI勝率':st.column_config.NumberColumn(format='percent')})
            st.write(f"市場主隊讓分：{r['主隊讓分']:+g}；市場大小分：{r['大小分界線']:g}")
            if pd.notna(r['AI預測總分']): st.write(f"AI 主客分差：{r['AI預測主客分差']:+.1f}；AI 預測總分：{r['AI預測總分']:.1f}")
        st.dataframe(data,hide_index=True)
        st.download_button('匯出賠率比較 CSV',data.to_csv(index=False).encode('utf-8-sig'),'db_odds.csv','text/csv')
    st.caption('賠率是手動核對的截圖快照，非即時資料；比較紀錄只保留於目前工作階段，請匯出。原有預測雲端紀錄不受影響。')
