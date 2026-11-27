"""NBA AI V8.0 release gate for the Streamlit application.

This module intentionally does not generate predictions. The V8.0 model
artifacts are not release-ready until Phase 5 data construction, Phase 6
chronological out-of-sample testing, Phase 7 calibration/risk review, and
source licensing review are complete.

The UI remains fail-closed: missing or malformed manifests never enable markets.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_MANIFEST = Path("artifacts/v80/market_model_manifest.json")
REQUIRED_MARKETS = ("moneyline", "spread", "total")


def load_manifest(path: str | Path = DEFAULT_MANIFEST) -> dict[str, Any] | None:
    """Return a JSON manifest, or None if unavailable/invalid."""
    try:
        obj = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None


def market_release_ready(
    manifest: dict[str, Any] | None,
    *,
    feature_enabled: bool,
    artifact_root: str | Path = ".",
) -> bool:
    """Require explicit release approval, completed gates and model files."""
    if not feature_enabled or not isinstance(manifest, dict):
        return False
    if manifest.get("release_status") != "APPROVED":
        return False
    gates = manifest.get("gates")
    if not isinstance(gates, dict):
        return False
    required_gates = (
        "phase5_dataset_validated",
        "phase6_oos_backtest_passed",
        "phase7_calibration_passed",
        "source_license_cleared",
    )
    if not all(gates.get(k) is True for k in required_gates):
        return False
    markets = manifest.get("markets")
    if not isinstance(markets, dict):
        return False
    root = Path(artifact_root)
    for market in REQUIRED_MARKETS:
        item = markets.get(market)
        if not isinstance(item, dict) or item.get("status") != "VALIDATED":
            return False
        rel = item.get("model_file")
        if not isinstance(rel, str) or not rel.strip():
            return False
        candidate = (root / rel).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            return False
        if not candidate.is_file():
            return False
    return True


def render_v80_market_status(st) -> None:
    """Render a truthful readiness panel; never invent probabilities."""
    manifest_path = os.environ.get("NBA_V80_MARKET_MANIFEST", str(DEFAULT_MANIFEST))
    manifest = load_manifest(manifest_path)
    enabled = os.environ.get("NBA_V80_MARKETS_ENABLED", "").strip().lower() in {
        "1", "true", "yes", "on"
    }
    root = Path(manifest_path).resolve().parent
    ready = market_release_ready(
        manifest, feature_enabled=enabled, artifact_root=root
    )

    st.subheader("NBA AI V8.0｜三市場整合")
    st.caption("Moneyline 獨贏・Spread 讓球・Over/Under 大小分")
    if ready:
        st.success("V8.0 三市場模型已通過發布閘門。")
        st.info("模型載入及逐場預測介面須由已驗證的模型推論模組提供；本頁不會以空值或市場線冒充 AI 機率。")
        return

    st.warning("V8.0 三市場尚未開放正式預測。")
    st.write(
        "正式網站會保留現有 V7.8 功能。只有在歷史資料、樣本外回測、"
        "機率校準及資料授權全部通過後，才會啟用 V8.0。"
    )
    status = manifest.get("gates", {}) if isinstance(manifest, dict) else {}
    rows = [
        ("Phase 5：歷史市場資料集驗證", "通過" if status.get("phase5_dataset_validated") is True else "待驗證"),
        ("Phase 6：時間序列樣本外回測", "通過" if status.get("phase6_oos_backtest_passed") is True else "待驗證"),
        ("Phase 7：機率校準及風險審核", "通過" if status.get("phase7_calibration_passed") is True else "待驗證"),
        ("資料來源授權審核", "通過" if status.get("source_license_cleared") is True else "待審核"),
        ("V8.0 啟用開關", "已開啟" if enabled else "關閉"),
    ]
    st.table([{"驗收項目": name, "狀態": value} for name, value in rows])
    st.caption("未取得經驗證的模型檔案前，不顯示預測勝率、讓球勝率或大小分勝率。")
