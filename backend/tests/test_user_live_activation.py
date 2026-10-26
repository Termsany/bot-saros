"""Per-user live-enable consent/audit — behavioral regression tests (TDD)."""
import sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app import user_live_activation as ula


class UserLiveActivationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.path = Path(self.tmp.name) / "user_live_activation.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def test_enable_requires_exact_consent_text(self):
        with self.assertRaises(PermissionError):
            ula.enable_user_live(self.path, user_id="u1", exchange="binance",
                                  confirm="yes I agree", actor="u1", ip="1.2.3.4")
        self.assertFalse(ula.is_user_live_enabled(self.path, user_id="u1"))

    def test_enable_with_consent_defaults_leverage_and_risk(self):
        ula.enable_user_live(self.path, user_id="u1", exchange="binance",
                              confirm=ula.CONSENT_TEXT, actor="u1", ip="1.2.3.4")
        rec = ula.get_user_live_record(self.path, user_id="u1")
        self.assertTrue(rec["enabled"])
        self.assertEqual(rec["leverage"], 2)
        self.assertEqual(rec["risk_per_trade_pct"], 0.25)
        self.assertEqual(rec["max_aggregate_risk_pct"], 1.0)
        self.assertEqual(rec["consent_text"], ula.CONSENT_TEXT)
        self.assertEqual(rec["actor"], "u1")
        self.assertEqual(rec["ip"], "1.2.3.4")
        self.assertTrue(rec["consented_at"])

    def test_enable_audit_records_actor_ip_timestamp(self):
        ula.enable_user_live(self.path, user_id="u2", exchange="bybit",
                              confirm=ula.CONSENT_TEXT, actor="user2@example.com", ip="9.9.9.9")
        rec = ula.get_user_live_record(self.path, user_id="u2")
        self.assertEqual(rec["actor"], "user2@example.com")
        self.assertEqual(rec["ip"], "9.9.9.9")
        self.assertIsNotNone(rec["consented_at"])

    def test_custom_risk_within_safe_bounds_accepted(self):
        ula.enable_user_live(self.path, user_id="u3", exchange="binance", confirm=ula.CONSENT_TEXT,
                              actor="u3", leverage=3, risk_per_trade_pct=0.5, max_aggregate_risk_pct=1.5)
        rec = ula.get_user_live_record(self.path, user_id="u3")
        self.assertEqual(rec["leverage"], 3)
        self.assertEqual(rec["risk_per_trade_pct"], 0.5)

    def test_leverage_outside_safe_bounds_rejected(self):
        with self.assertRaises(ValueError):
            ula.enable_user_live(self.path, user_id="u4", exchange="binance",
                                  confirm=ula.CONSENT_TEXT, actor="u4", leverage=50)

    def test_risk_per_trade_cannot_exceed_aggregate_cap(self):
        with self.assertRaises(ValueError):
            ula.enable_user_live(self.path, user_id="u5", exchange="binance", confirm=ula.CONSENT_TEXT,
                                  actor="u5", risk_per_trade_pct=2.0, max_aggregate_risk_pct=1.0)

    def test_disable_turns_off_without_deleting_audit_history(self):
        ula.enable_user_live(self.path, user_id="u6", exchange="binance", confirm=ula.CONSENT_TEXT, actor="u6")
        self.assertTrue(ula.is_user_live_enabled(self.path, user_id="u6"))
        ula.disable_user_live(self.path, user_id="u6", reason="changed mind")
        self.assertFalse(ula.is_user_live_enabled(self.path, user_id="u6"))
        rec = ula.get_user_live_record(self.path, user_id="u6")
        self.assertEqual(rec["disabled_reason"], "changed mind")
        self.assertEqual(rec["consent_text"], ula.CONSENT_TEXT)  # history retained

    def test_users_are_isolated_in_the_activation_ledger(self):
        ula.enable_user_live(self.path, user_id="u7", exchange="binance", confirm=ula.CONSENT_TEXT, actor="u7")
        self.assertFalse(ula.is_user_live_enabled(self.path, user_id="u8"))  # u8 never enabled anything
        ula.disable_user_live(self.path, user_id="u8")  # no-op, must not raise or affect u7
        self.assertTrue(ula.is_user_live_enabled(self.path, user_id="u7"))

    def test_exchange_mismatch_is_not_enabled(self):
        ula.enable_user_live(self.path, user_id="u9", exchange="binance", confirm=ula.CONSENT_TEXT, actor="u9")
        self.assertFalse(ula.is_user_live_enabled(self.path, user_id="u9", exchange="bybit"))
        self.assertTrue(ula.is_user_live_enabled(self.path, user_id="u9", exchange="binance"))


if __name__ == "__main__":
    unittest.main()
