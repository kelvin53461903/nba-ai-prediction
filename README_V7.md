# NBA AI V7.0 ULTIMATE
沿用 V6.2，僅 NBA。先匯出預測及賠率 CSV 備份。原 GitHub main 上傳本 ZIP 的 app.py、db_odds.py、requirements.txt；不要刪除原有其他檔案或建立新 Streamlit app。
Streamlit 原 app > Settings > Secrets，保留現有設定，新增 BDL_API_KEY = "你的金鑰"（或 BALLDONTLIE_API_KEY）。不要公開金鑰。如已使用 BDL_API_KEY，無須新增。GitHub Actions 仍使用原 BDL_API_KEY。原 Supabase 設定、排程及預測表保持不變。
賠率 CSV 現可手動還原至自己的工作階段；並非永久雲端儲存。截圖仍需人工核對。原預測雲端保存需已有 Supabase 設定；免費方案不保證永久服務。未進行外部 API、雲端及瀏覽器端整合測試，已通過 Python 語法檢查。
