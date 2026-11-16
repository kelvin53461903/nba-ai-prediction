import streamlit as st
import pandas as pd
import numpy as np
import requests
from datetime import date, timedelta
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import accuracy_score, mean_absolute_error

st.set_page_config(page_title="NBA AI Predictor", page_icon="🏀", layout="wide")
BASE = "https://api.balldontlie.io/v1"

st.title("🏀 NBA AI Prediction Platform")
st.caption("賽程・球員・傷兵・AI 勝負及比分預測 | 資料以 API 回傳時間為準")

with st.sidebar:
    st.header("資料連線")
    api_key = st.text_input("BALLDONTLIE API Key", type="password",
                            help="API key 只在本次 Streamlit session 使用；不要公開分享。")
    st.markdown("[申請 API Key](https://app.balldontlie.io/)")
    st.caption("Free：球隊、球員基本資料、賽程。球員比賽數據及傷兵資料需要付費權限。")
    st.divider()
    st.header("預測設定")
    form_n = st.slider("近期比賽樣本數", 3, 15, 8)
    st.caption("模型會用歷史賽果建立近期球隊狀態。")

def api_get(path, params=None):
    if not api_key:
        raise RuntimeError("請先在左側輸入 BALLDONTLIE API Key。")
    r = requests.get(f"{BASE}/{path.lstrip('/')}",
                     headers={"Authorization": api_key},
                     params=params or {}, timeout=25)
    if r.status_code == 401:
        raise RuntimeError("API Key 無效，或你的方案沒有此 API 權限（HTTP 401）。")
    if r.status_code == 429:
        raise RuntimeError("API 請求次數已達上限（HTTP 429），請稍後再試。")
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=600, show_spinner=False)
def cached_api_get(path, params_tuple, key_fingerprint):
    # key_fingerprint separates cached results per API key without storing the key in cache key display.
    params = dict(params_tuple)
    return api_get(path, params)

def get_data(path, params=None):
    return cached_api_get(path, tuple(sorted((params or {}).items())), hash(api_key))

def records(payload):
    d = payload.get("data", [])
    return d if isinstance(d, list) else ([d] if d else [])

def team_frame():
    return pd.DataFrame(records(get_data("teams")))

def games_for_day(day):
    return pd.DataFrame(records(get_data("games", {"dates[]": day.isoformat(), "per_page": 100})))

def injuries_data():
    return pd.DataFrame(records(get_data("player_injuries", {"per_page": 100})))

def player_search(term):
    return pd.DataFrame(records(get_data("players/active", {"search": term, "per_page": 100})))

def team_name(team):
    return team.get("full_name", team.get("abbreviation", "Unknown"))

def fmt_game(row):
    h = row.get("home_team", {}) or {}
    a = row.get("visitor_team", {}) or {}
    return f"{a.get('abbreviation','?')} @ {h.get('abbreviation','?')}"

if not api_key:
    st.info("請先在左側輸入 API Key。你可以先申請免費 Key，免費方案可讀取球隊、球員基本資料及賽程。")
    st.markdown("**API 申請：** [BALLDONTLIE](https://app.balldontlie.io/)")
    st.stop()

tabs = st.tabs(["📅 今日賽程", "🏥 傷兵中心", "👤 球員搜尋", "🤖 AI 比賽預測", "⚙️ 資料與模型"])

# --- schedule ---
with tabs[0]:
    st.subheader("NBA 賽程")
    chosen_day = st.date_input("選擇比賽日期", value=date.today())
    if st.button("更新賽程", key="refresh_games"):
        st.cache_data.clear()
    try:
        games = games_for_day(chosen_day)
        if games.empty:
            st.info("該日期沒有找到賽事，或資料供應商尚未更新。")
        else:
            view = []
            for _, g in games.iterrows():
                h = g.get("home_team") or {}
                a = g.get("visitor_team") or {}
                view.append({
                    "客隊": team_name(a), "主隊": team_name(h),
                    "客隊得分": g.get("visitor_team_score"),
                    "主隊得分": g.get("home_team_score"),
                    "狀態": g.get("status_state", g.get("status", "未知")),
                    "開賽時間": g.get("datetime", g.get("date", ""))
                })
            st.dataframe(pd.DataFrame(view), use_container_width=True, hide_index=True)
            st.caption("賽程及即時比分由 BALLDONTLIE API 提供；實際更新頻率視供應商而定。")
    except Exception as e:
        st.error(f"讀取賽程失敗：{e}")

# --- injuries ---
with tabs[1]:
    st.subheader("傷兵中心")
    st.write("傷兵資料需 API 帳戶具有 Player Injuries 權限。官方 NBA 傷兵報告亦會持續更新。")
    st.markdown("[NBA 官方 2026–27 傷兵報告](https://official.nba.com/nba-injury-report-2026-27-season/)")
    if st.button("載入傷兵名單", key="load_injuries"):
        st.cache_data.clear()
    try:
        inj = injuries_data()
        if inj.empty:
            st.info("目前 API 沒有回傳傷兵紀錄。")
        else:
            out = []
            for _, x in inj.iterrows():
                p = x.get("player") or {}
                out.append({
                    "球員": f"{p.get('first_name','')} {p.get('last_name','')}".strip(),
                    "球隊 ID": p.get("team_id"),
                    "狀態": x.get("status", "未提供"),
                    "預計回歸": x.get("return_date", "未提供"),
                    "傷病／備註": x.get("description", "")
                })
            st.dataframe(pd.DataFrame(out), use_container_width=True, hide_index=True)
            st.warning("傷兵狀態可能隨時改變；預測前請再次核對官方報告。")
    except Exception as e:
        st.error(f"無法讀取傷兵資料：{e}")
        st.info("BALLDONTLIE 的 Player Injuries 並非免費方案功能。可先查看 NBA 官方傷兵報告。")

# --- player search ---
with tabs[2]:
    st.subheader("球員資料搜尋")
    q = st.text_input("輸入球員英文名字，例如 Stephen Curry")
    if st.button("搜尋球員", key="search_player") and q.strip():
        try:
            players = player_search(q.strip())
            if players.empty:
                st.info("找不到球員。")
            else:
                out = []
                for _, p in players.iterrows():
                    t = p.get("team") or {}
                    out.append({
                        "球員": f"{p.get('first_name','')} {p.get('last_name','')}".strip(),
                        "位置": p.get("position", ""),
                        "球衣號碼": p.get("jersey_number", ""),
                        "球隊": team_name(t) if t else "未提供",
                        "球員 ID": p.get("id")
                    })
                st.dataframe(pd.DataFrame(out), use_container_width=True, hide_index=True)
        except Exception as e:
            st.error(f"搜尋失敗：{e}")
    st.caption("免費 API 可搜尋球員基本資料；詳細比賽統計及賽季平均數據視 API 方案而定。")

# --- model / prediction ---
with tabs[3]:
    st.subheader("AI 比賽預測")
    st.write("上傳歷史賽事 CSV，模型會使用每隊近期表現建立預測。若未上傳資料，暫時不能產生可信的 AI 預測。")
    hist_file = st.file_uploader("上傳歷史 NBA games.csv", type=["csv"], key="hist_upload")
    required = ["GAME_DATE_EST", "HOME_TEAM_ID", "VISITOR_TEAM_ID", "PTS_home", "PTS_away", "HOME_TEAM_WINS"]
    if hist_file is not None:
        try:
            raw = pd.read_csv(hist_file)
            missing = [c for c in required if c not in raw.columns]
            if missing:
                st.error("CSV 欠缺欄位：" + ", ".join(missing))
            else:
                raw = raw[required].copy()
                raw["GAME_DATE_EST"] = pd.to_datetime(raw["GAME_DATE_EST"], errors="coerce")
                for c in required[1:]:
                    raw[c] = pd.to_numeric(raw[c], errors="coerce")
                raw = raw.dropna().sort_values("GAME_DATE_EST")
                hist = {}
                rows = []
                for dt, day_games in raw.groupby("GAME_DATE_EST", sort=True):
                    pending = []
                    for _, g in day_games.iterrows():
                        h, a = int(g.HOME_TEAM_ID), int(g.VISITOR_TEAM_ID)
                        def team_stats(t):
                            seq = hist.get(t, [])[-form_n:]
                            if not seq:
                                return [0.5, 110, 110]
                            return [np.mean([z[0] for z in seq]),
                                    np.mean([z[1] for z in seq]),
                                    np.mean([z[2] for z in seq])]
                        hs, aws = team_stats(h), team_stats(a)
                        rows.append({
                            "home_id": h, "away_id": a,
                            "home_win_rate": hs[0], "home_for": hs[1], "home_against": hs[2],
                            "away_win_rate": aws[0], "away_for": aws[1], "away_against": aws[2],
                            "home_win": int(g.HOME_TEAM_WINS),
                            "home_pts": float(g.PTS_home), "away_pts": float(g.PTS_away)
                        })
                        pending.append((h, a, int(g.HOME_TEAM_WINS), float(g.PTS_home), float(g.PTS_away)))
                    for h, a, w, hp, ap in pending:
                        hist.setdefault(h, []).append((w, hp, ap))
                        hist.setdefault(a, []).append((1-w, ap, hp))
                train = pd.DataFrame(rows)
                feats = ["home_win_rate", "home_for", "home_against", "away_win_rate", "away_for", "away_against"]
                if len(train) < 50:
                    st.warning("歷史賽事少於 50 場，模型結果可能不穩定。")
                if len(train) >= 20:
                    cut = max(1, int(len(train)*0.8))
                    Xtr, Xte = train[feats].iloc[:cut], train[feats].iloc[cut:]
                    clf = RandomForestClassifier(n_estimators=250, random_state=42, class_weight="balanced")
                    rh = RandomForestRegressor(n_estimators=250, random_state=42)
                    ra = RandomForestRegressor(n_estimators=250, random_state=42)
                    clf.fit(Xtr, train.home_win.iloc[:cut])
                    rh.fit(Xtr, train.home_pts.iloc[:cut])
                    ra.fit(Xtr, train.away_pts.iloc[:cut])
                    if len(Xte):
                        st.metric("按時間切分測試準確率", f"{accuracy_score(train.home_win.iloc[cut:], clf.predict(Xte)):.1%}")
                        st.caption(f"測試集主隊 MAE {mean_absolute_error(train.home_pts.iloc[cut:], rh.predict(Xte)):.1f} 分；客隊 MAE {mean_absolute_error(train.away_pts.iloc[cut:], ra.predict(Xte)):.1f} 分")
                    st.session_state["nba_model"] = (clf, rh, ra, hist, feats)
                    st.success(f"模型訓練完成：{len(train):,} 場歷史比賽。")
        except Exception as e:
            st.error(f"無法處理歷史 CSV：{e}")

    model = st.session_state.get("nba_model")
    if model:
        clf, rh, ra, hist, feats = model
        try:
            teams = team_frame()
            if not teams.empty:
                team_options = {f"{r['full_name']} ({r['abbreviation']})": int(r["id"]) for _, r in teams.iterrows()}
                c1, c2 = st.columns(2)
                with c1:
                    home_label = st.selectbox("主場球隊", list(team_options.keys()), key="pred_home")
                with c2:
                    away_choices = [x for x in team_options if x != home_label]
                    away_label = st.selectbox("客場球隊", away_choices, key="pred_away")
                def stats_for(tid):
                    arr = hist.get(tid, [])[-form_n:]
                    if not arr:
                        return [0.5, 110, 110]
                    return [np.mean([z[0] for z in arr]), np.mean([z[1] for z in arr]), np.mean([z[2] for z in arr])]
                if st.button("開始 AI 預測", type="primary"):
                    hs, aws = stats_for(team_options[home_label]), stats_for(team_options[away_label])
                    sample = pd.DataFrame([{
                        "home_win_rate": hs[0], "home_for": hs[1], "home_against": hs[2],
                        "away_win_rate": aws[0], "away_for": aws[1], "away_against": aws[2]
                    }])[feats]
                    pr = clf.predict_proba(sample)[0]
                    home_prob = float(pr[list(clf.classes_).index(1)]) if 1 in clf.classes_ else 0.5
                    home_pts = max(0, float(rh.predict(sample)[0]))
                    away_pts = max(0, float(ra.predict(sample)[0]))
                    a, b = st.columns(2)
                    a.metric(home_label, f"{home_pts:.0f} 分", f"勝率 {home_prob:.1%}")
                    b.metric(away_label, f"{away_pts:.0f} 分", f"勝率 {1-home_prob:.1%}")
                    st.success("預測勝方：" + (home_label if home_prob >= 0.5 else away_label))
                    st.caption("此版本模型使用歷史球隊近期數據；傷兵資料會獨立顯示，尚未自動轉換成球員缺陣分數。")
        except Exception as e:
            st.error(f"準備預測時發生錯誤：{e}")
    else:
        st.info("請先上傳歷史賽事 CSV 並完成模型訓練。")

# --- settings ---
with tabs[4]:
    st.subheader("資料來源及模型說明")
    st.markdown("""
    **資料來源**
    - BALLDONTLIE NBA API：球隊、球員、賽程、比分及（視方案而定）球員統計、傷兵資料。
    - NBA 官方傷兵報告：可作為傷兵狀態的交叉核對來源。

    **模型**
    - Random Forest 分類器：預測主隊勝出機率。
    - Random Forest 回歸器：分別預測主隊及客隊得分。
    - 特徵：每隊最近 N 場勝率、得分及失分平均。
    - 按日期排序並以較早賽事訓練、較後賽事測試，避免隨機切分造成未來資料洩漏。

    **注意**
    - 目前不是醫療／傷病診斷工具；傷兵狀態可能變動。
    - 未有可靠的球員出賽分鐘或先發名單時，不會假裝已量化傷兵對比分的影響。
    - 不保證預測正確，亦不應視為投注建議。
    """)
    st.markdown("[BALLDONTLIE API 文件](https://docs.balldontlie.io/) · [NBA 官方傷兵報告](https://official.nba.com/nba-injury-report-2026-27-season/)")

