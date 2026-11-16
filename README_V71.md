# V7.1 AI PRO ACCURACY
以 V7.0 原始碼為基礎，保留七個頁籤。新增時間加權、波動、賽程密度、梯度提升模型、正則化候選及校準診斷。沿用時間切割及 Brier 選模。校準診斷不是重新校準。歷史傷兵、球員貢獻、真實 Pace 未取得，不假造資料。未驗證線上 API 或真實準確度改善。
部署：先匯出原網站 CSV；在原 GitHub repository/main 覆蓋 app.py、db_odds.py、requirements.txt。保留原 Streamlit app 與 Secrets，不要新建 app。雲端與背景排程仍須另行設定。
