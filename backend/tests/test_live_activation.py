import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend.app import live_activation
import bot


class LiveActivationTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.path = Path(self.td.name) / "activation.sqlite3"

    def tearDown(self):
        self.td.cleanup()

    def test_default_environment_is_locked(self):
        with mock.patch.dict(os.environ, {"ALLOW_LIVE_TRADING": "false"}):
            with self.assertRaises(PermissionError):
                live_activation.activate(self.path, environment="live", account="live-main", approved_by="admin",
                    strategies=["trend_daily"], risk_allocation={"trend_daily": 0.25}, readiness={"trend_daily": True})

    def test_activation_requires_every_gate(self):
        with mock.patch.dict(os.environ, {"ALLOW_LIVE_TRADING": "true"}):
            with self.assertRaises(ValueError):
                live_activation.activate(self.path, environment="live", account="live-main", approved_by="admin",
                    strategies=["trend_daily", "wave_flats"], risk_allocation={"trend_daily": 0.25}, readiness={"trend_daily": True})

    def test_activation_matches_account_strategy_and_readiness(self):
        with mock.patch.dict(os.environ, {"ALLOW_LIVE_TRADING": "true"}):
            aid = live_activation.activate(self.path, environment="live", account="live-main", approved_by="admin",
                strategies=["trend_daily"], risk_allocation={"trend_daily": 0.25}, readiness={"trend_daily": True})
            self.assertTrue(aid.startswith("act-"))
            self.assertEqual(live_activation.live_activation_allowed(self.path, strategy="trend_daily", account="live-main"), (True, None))
            self.assertFalse(live_activation.live_activation_allowed(self.path, strategy="wave_flats", account="live-main")[0])
            self.assertFalse(live_activation.live_activation_allowed(self.path, strategy="trend_daily", account="other")[0])

    def test_revoke_is_immediate_and_audited(self):
        with mock.patch.dict(os.environ, {"ALLOW_LIVE_TRADING": "true"}):
            aid = live_activation.activate(self.path, environment="live", account="live-main", approved_by="admin",
                strategies=["trend_daily"], risk_allocation={"trend_daily": 0.25}, readiness={"trend_daily": True})
            live_activation.revoke(self.path, activation_id=aid, reason="test revoke")
            self.assertFalse(live_activation.live_activation_allowed(self.path, strategy="trend_daily", account="live-main")[0])

    def test_bot_live_gate_requires_audit_record(self):
        old_path = bot.ACTIVATION_PATH
        try:
            bot.ACTIVATION_PATH = self.path
            with mock.patch.dict(os.environ, {"BINANCE_ENV": "live", "ALLOW_LIVE_TRADING": "true", "BINANCE_LIVE_ACCOUNT": "live-main"}):
                allowed, reason = bot._live_activation_gate("trend_daily")
            self.assertFalse(allowed)
            self.assertIn("approval", reason)
        finally:
            bot.ACTIVATION_PATH = old_path


if __name__ == "__main__":
    unittest.main()
