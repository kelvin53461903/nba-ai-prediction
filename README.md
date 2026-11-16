# NBA AI Prediction Platform（繁體中文版）

這是一個 Streamlit 網站原型，包含：
- NBA 指定日期賽程及比分
- 球員基本資料搜尋
- 傷兵名單（需 API 權限）
- Random Forest 勝負機率及比分預測
- 模型測試準確率及 MAE

## 1. 安裝及啟動（Mac）

先安裝 Python 3.10 或以上版本，解壓縮後在 Terminal 進入此資料夾：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

瀏覽器通常會自動開啟 `http://localhost:8501`。

## 2. API Key

到 https://app.balldontlie.io/ 建立帳戶並取得 NBA API Key。在網站左側貼上 Key。

目前 BALLDONTLIE 文件列明：
- Free：Teams、Players、Games
- ALL-STAR（文件列價 US$9.99/月）：再包括 Game Player Stats、Active Players、Player Injuries
- GOAT（文件列價 US$39.99/月）：再包括 Season Averages、Team Season Averages、Advanced Stats 等

價錢及權限可能變更，申請前請在官方文件確認：https://docs.balldontlie.io/

## 3. 訓練預測模型

在「AI 比賽預測」分頁上傳歷史 NBA `games.csv`，必須包含：
- `GAME_DATE_EST`
- `HOME_TEAM_ID`
- `VISITOR_TEAM_ID`
- `PTS_home`
- `PTS_away`
- `HOME_TEAM_WINS`

可用的歷史資料例子：https://www.kaggle.com/datasets/nathanlauga/nba-games

上傳後，模型會按日期建立球隊近期狀態，再以較早比賽訓練、較後比賽測試。選擇主客隊並按「開始 AI 預測」。

## 4. 傷兵資料

BALLDONTLIE 的 Player Injuries endpoint 需要有相應權限。網站亦提供 NBA 官方 2026–27 傷兵報告連結供核對：
https://official.nba.com/nba-injury-report-2026-27-season/

目前傷兵狀態會顯示在傷兵中心，但不會未經驗證就假設球員一定缺陣，也不會將傷兵直接轉成任意分數。要進一步建立球員影響模型，需要加入球員近期比賽數據、預計上場時間及先發名單。

## 5. 部署上網

本機測試成功後，可部署到 Streamlit Community Cloud 或其他支援 Streamlit 的主機。部署時將 API Key 放入主機的 Secrets，不要寫死在程式碼，也不要把 Key 放進公開 GitHub repository。

## 重要限制

這是可運行的進階原型，不是已經完成驗證的專業預測服務。預測品質取決於歷史 CSV 的完整性、API 權限及資料更新情況。傷兵、輪休、交易、臨場先發等都可能改變比賽結果。
