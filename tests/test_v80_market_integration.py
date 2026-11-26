import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "v80_market_integration.py"
spec = importlib.util.spec_from_file_location("v80_market_integration", MODULE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class V80ReleaseGateTests(unittest.TestCase):
    def make_manifest(self, root):
        files = {}
        for market in mod.REQUIRED_MARKETS:
            path = root / f"{market}.bin"
            path.write_bytes(b"test-model-placeholder")
            files[market] = {"status": "VALIDATED", "model_file": path.name}
        return {
            "release_status": "APPROVED",
            "gates": {
                "phase5_dataset_validated": True,
                "phase6_oos_backtest_passed": True,
                "phase7_calibration_passed": True,
                "source_license_cleared": True,
            },
            "markets": files,
        }

    def test_fail_closed_when_feature_flag_off(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertFalse(mod.market_release_ready(self.make_manifest(root), feature_enabled=False, artifact_root=root))

    def test_fail_closed_when_gate_missing(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            m = self.make_manifest(root)
            m["gates"]["phase6_oos_backtest_passed"] = False
            self.assertFalse(mod.market_release_ready(m, feature_enabled=True, artifact_root=root))

    def test_fail_closed_when_model_file_missing(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            m = self.make_manifest(root)
            (root / "spread.bin").unlink()
            self.assertFalse(mod.market_release_ready(m, feature_enabled=True, artifact_root=root))

    def test_pass_only_when_all_gates_and_models_exist(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertTrue(mod.market_release_ready(self.make_manifest(root), feature_enabled=True, artifact_root=root))

    def test_reject_path_traversal(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            m = self.make_manifest(root)
            m["markets"]["moneyline"]["model_file"] = "../outside.bin"
            self.assertFalse(mod.market_release_ready(m, feature_enabled=True, artifact_root=root))


if __name__ == "__main__":
    unittest.main()
