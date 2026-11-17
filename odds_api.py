"""The Odds API: public, pre-game NBA odds snapshots; no secrets stored."""
import os, json, requests
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ENDPOINT = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds/"
SNAPSHOT = Path("data/odds_latest.json")

def update_snapshot():
    key = os.environ.get("THE_ODDS_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Missing THE_ODDS_API_KEY GitHub Actions secret")
    response = requests.get(ENDPOINT, params={"regions":"us", "markets":"h2h,spreads,totals", "oddsFormat":"decimal", "dateFormat":"iso"}, headers={"x-api-key":key}, timeout=30)
    response.raise_for_status()
    events = response.json()
    if not isinstance(events, list):
        raise ValueError("Unexpected odds API response")
    now = datetime.now(timezone.utc)
    upcoming = []
    for event in events:
        try:
            tip = datetime.fromisoformat(event["commence_time"].replace("Z", "+00:00"))
        except (KeyError, ValueError, TypeError):
            continue
        if tip <= now:
            continue
        upcoming.append(event)
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    payload = {"source":"The Odds API", "retrieved_at_utc":now.isoformat(), "regions":"us", "markets":["h2h","spreads","totals"], "events":upcoming}
    temp = SNAPSHOT.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temp.replace(SNAPSHOT)
    print("The Odds API snapshot saved: %d upcoming events; credits remaining %s" % (len(upcoming), response.headers.get("x-requests-remaining", "unknown")))

def load_snapshot():
    try:
        url="https://raw.githubusercontent.com/kelvin53461903/nba-ai-prediction/main/data/odds_latest.json"
        r=requests.get(url, timeout=15, headers={"Cache-Control":"no-cache"})
        r.raise_for_status()
        obj=r.json()
        if obj.get("source") != "The Odds API" or not isinstance(obj.get("events"),list):
            return None
        return obj
    except (requests.RequestException, ValueError, TypeError):
        return None

def match_event(game, events):
    home=game["home_team"]["full_name"].casefold()
    away=game["visitor_team"]["full_name"].casefold()
    from pandas import Timestamp
    tip=Timestamp(game["datetime"])
    for e in events:
        if str(e.get("home_team","")).casefold()!=home or str(e.get("away_team","")).casefold()!=away:
            continue
        try:
            other=Timestamp(e["commence_time"])
            if abs((tip-other).total_seconds())<=7200:
                return e
        except (ValueError,TypeError,KeyError):
            pass
    return None

def best_market(event):
    # One coherent bookmaker per snapshot: never combine unmatched prices/lines.
    for book in event.get("bookmakers",[]):
        markets={m.get("key"):m for m in book.get("markets",[])}
        if all(k in markets for k in ("h2h","spreads","totals")):
            return book,markets
    return None,None

def home_spread(market, home):
    for item in market.get("outcomes",[]):
        if item.get("name")==home:
            return item.get("point")
    return None

def render(games, snapshot, hk):
    import streamlit as st
    import pandas as pd
    st.subheader("公開賠率 API 比較")
    st.caption("來源：The Odds API（美國地區博彩公司）；非 Pinnacle。僅顯示賽前快照，不提供下注建議。")
    if not snapshot:
        st.warning("尚未取得公開賠率快照。請先在 GitHub Actions 執行 NBA Odds Update。"); return
    captured=pd.Timestamp(snapshot["retrieved_at_utc"])
    age=pd.Timestamp.now(tz="UTC")-captured
    st.caption(f"資料取得：{captured.tz_convert(hk):%Y-%m-%d %H:%M} HKT（{age.total_seconds()/3600:.1f} 小時前）")
    if age.total_seconds()>12*3600: st.warning("賠率快照超過 12 小時，可能已過時。")
    records=[]
    for g in games:
        e=match_event(g,snapshot["events"])
        if not e: continue
        book,markets=best_market(e)
        if not book: continue
        h=g["home_team"]["full_name"]; a=g["visitor_team"]["full_name"]
        ml={x.get("name"):x.get("price") for x in markets["h2h"].get("outcomes",[])}
        total=next((x.get("point") for x in markets["totals"].get("outcomes",[]) if x.get("name")=="Over"),None)
        records.append({"賽事":f"{a} @ {h}","博彩公司":book.get("title"),"客隊獨贏":ml.get(a),"主隊獨贏":ml.get(h),"主隊讓分":home_spread(markets["spreads"],h),"全場大小分":total,"開賽 HKT":pd.Timestamp(e["commence_time"]).tz_convert(hk).strftime("%m-%d %H:%M")})
    if records: st.dataframe(pd.DataFrame(records),hide_index=True,width="stretch")
    else: st.info("所選日期未找到完整且可配對的賽前獨贏／讓分／大小分報價。")
    st.caption("展示同一博彩公司的一組盤口；不同博彩公司可能有不同數值。舊 Pinnacle 歷史紀錄保持獨立。")
