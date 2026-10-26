import tempfile, unittest, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "backend"))
from app import admin_control, risk_manager

class AdminControlPersistenceTests(unittest.TestCase):
    def test_pause_is_persistent_and_audited(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            value=admin_control.set_entry_pause(root, True, "admin@example.com", "maintenance")
            self.assertTrue(value["paused"])
            self.assertTrue(admin_control.read_state(root)["entry_paused"]["paused"])
            self.assertEqual(admin_control.list_audit(root)[0]["action"], "entry_pause")

    def test_strategy_updates_are_paper_only(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            result=admin_control.update_strategy(root, "trend_daily", {"enabled": False, "mode": "live"}, "admin")
            self.assertFalse(result["enabled"])
            self.assertEqual(result["mode"], "paper")

    def test_risk_kill_switch_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d) / "risk_state.json"
            risk_manager.trip_kill_switch(root, "operator test", by="admin")
            self.assertTrue(risk_manager.load_risk_state(root)["kill_switch"]["tripped"])
            risk_manager.reset_kill_switch(root, operator="admin")
            self.assertFalse(risk_manager.load_risk_state(root)["kill_switch"]["tripped"])

if __name__ == "__main__": unittest.main()
