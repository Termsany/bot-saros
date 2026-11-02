import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend.app import live_activation
from backend.app import risk_manager
import bot


def limits(**overrides):
    """A funded plan: $30 margin at x2 with the 40 % stop is 0.02 % of $100k, well under every default limit."""
    base = {**risk_manager.DEFAULT_LIMITS, "capital_usdt": 100_000, "capital_margin_override_usdt": 30.0}
    base.update(overrides)
    return base


def evidence(*strategies):
    """A trusted, fully verified readiness document (the only thing activation may derive readiness from)."""
    fields = ("adapter_implemented", "recovery_tests", "security_approved", "testnet_validated")
    return {
        "schema_version": 1,
        "provenance": {"source": "trusted-readiness", "verified": True},
        "strategies": {s: {f: {"value": True, "verified": True} for f in fields} for s in strategies},
    }


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
                    strategies=["trend_daily"], risk_allocation={"trend_daily": 0.25}, risk_limits=limits(), equity_usdt=100_000, readiness_evidence=evidence("trend_daily"))

    def test_activation_requires_every_gate(self):
        with mock.patch.dict(os.environ, {"ALLOW_LIVE_TRADING": "true"}):
            with self.assertRaises(ValueError):
                live_activation.activate(self.path, environment="live", account="live-main", approved_by="admin",
                    strategies=["trend_daily", "wave_flats"], risk_allocation={"trend_daily": 0.25},
                    risk_limits=limits(), equity_usdt=100_000, readiness_evidence=evidence("trend_daily"))

    def test_readiness_cannot_be_self_declared(self):
        # The old call passed readiness={"trend_daily": True}; now only verified evidence can satisfy the gate.
        with mock.patch.dict(os.environ, {"ALLOW_LIVE_TRADING": "true"}):
            with self.assertRaises(ValueError):
                live_activation.activate(self.path, environment="live", account="live-main", approved_by="admin",
                    strategies=["trend_daily"], risk_allocation={"trend_daily": 0.25},
                    risk_limits=limits(), equity_usdt=100_000, readiness_evidence={})
            self.assertIsNone(live_activation.active_record(self.path))

    def test_activation_requires_the_ledger_limits(self):
        with mock.patch.dict(os.environ, {"ALLOW_LIVE_TRADING": "true"}):
            with self.assertRaises(ValueError) as raised:
                live_activation.activate(self.path, environment="live", account="live-main", approved_by="admin",
                    strategies=["trend_daily"], risk_allocation={"trend_daily": 0.25},
                    readiness_evidence=evidence("trend_daily"))
            self.assertIn("ledger limits", str(raised.exception))
            self.assertIsNone(live_activation.active_record(self.path))

    def test_activation_refuses_a_plan_that_cannot_fund_one_trade(self):
        with mock.patch.dict(os.environ, {"ALLOW_LIVE_TRADING": "true"}):
            with self.assertRaises(ValueError) as raised:
                live_activation.activate(self.path, environment="live", account="live-main", approved_by="admin",
                    strategies=["trend_daily"], risk_allocation={"trend_daily": 1.0},
                    risk_limits=limits(capital_usdt=1_000, capital_margin_override_usdt=None), equity_usdt=1_000,
                    readiness_evidence=evidence("trend_daily"))
            self.assertIn("risk_per_trade_pct", str(raised.exception))
            self.assertIsNone(live_activation.active_record(self.path))

    def test_activation_refuses_without_a_capital_plan(self):
        with mock.patch.dict(os.environ, {"ALLOW_LIVE_TRADING": "true"}):
            with self.assertRaises(ValueError) as raised:
                live_activation.activate(self.path, environment="live", account="live-main", approved_by="admin",
                    strategies=["trend_daily"], risk_allocation={"trend_daily": 1.0},
                    risk_limits=limits(capital_usdt=None, capital_margin_override_usdt=None), equity_usdt=100_000,
                    readiness_evidence=evidence("trend_daily"))
            self.assertIn("no capital plan", str(raised.exception))

    def test_activation_matches_account_strategy_and_readiness(self):
        with mock.patch.dict(os.environ, {"ALLOW_LIVE_TRADING": "true"}):
            aid = live_activation.activate(self.path, environment="live", account="live-main", approved_by="admin",
                strategies=["trend_daily"], risk_allocation={"trend_daily": 0.25},
                risk_limits=limits(), equity_usdt=100_000, readiness_evidence=evidence("trend_daily"))
            self.assertTrue(aid.startswith("act-"))
            self.assertEqual(live_activation.live_activation_allowed(self.path, strategy="trend_daily", account="live-main"), (True, None))
            self.assertFalse(live_activation.live_activation_allowed(self.path, strategy="wave_flats", account="live-main")[0])
            self.assertFalse(live_activation.live_activation_allowed(self.path, strategy="trend_daily", account="other")[0])
            self.assertEqual(live_activation.strategy_risk_share(self.path, strategy="trend_daily", account="live-main"), 0.25)
            self.assertIsNone(live_activation.strategy_risk_share(self.path, strategy="trend_daily", account="other"))

    def test_allocation_defaults_to_an_equal_split_and_is_recorded(self):
        with mock.patch.dict(os.environ, {"ALLOW_LIVE_TRADING": "true"}):
            live_activation.activate(self.path, environment="live", account="live-main", approved_by="admin",
                strategies=["trend_daily", "momentum_ls"],
                risk_limits=limits(), equity_usdt=100_000, readiness_evidence=evidence("trend_daily", "momentum_ls"))
            record = live_activation.active_record(self.path)
            self.assertEqual(record["risk_allocation"], {"trend_daily": 0.5, "momentum_ls": 0.5})
            self.assertEqual(record["readiness"], {"trend_daily": True, "momentum_ls": True})

    def test_allocations_may_not_exceed_the_aggregate_budget(self):
        with mock.patch.dict(os.environ, {"ALLOW_LIVE_TRADING": "true"}):
            with self.assertRaises(ValueError):
                live_activation.activate(self.path, environment="live", account="live-main", approved_by="admin",
                    strategies=["trend_daily", "momentum_ls"],
                    risk_allocation={"trend_daily": 0.7, "momentum_ls": 0.7},
                    risk_limits=limits(), equity_usdt=100_000, readiness_evidence=evidence("trend_daily", "momentum_ls"))

    def test_revoke_is_immediate_and_audited(self):
        with mock.patch.dict(os.environ, {"ALLOW_LIVE_TRADING": "true"}):
            aid = live_activation.activate(self.path, environment="live", account="live-main", approved_by="admin",
                strategies=["trend_daily"], risk_allocation={"trend_daily": 0.25},
                risk_limits=limits(), equity_usdt=100_000, readiness_evidence=evidence("trend_daily"))
            live_activation.revoke(self.path, activation_id=aid, reason="test revoke")
            self.assertFalse(live_activation.live_activation_allowed(self.path, strategy="trend_daily", account="live-main")[0])
            self.assertIsNone(live_activation.strategy_risk_share(self.path, strategy="trend_daily", account="live-main"))

    def test_bot_live_gate_requires_audit_record(self):
        old_path = bot.ACTIVATION_PATH
        try:
            bot.ACTIVATION_PATH = self.path
            with mock.patch.dict(os.environ, {"BINANCE_ENV": "live", "ALLOW_LIVE_TRADING": "true", "BINANCE_LIVE_ACCOUNT": "live-main"}):
                allowed, reason = bot._live_activation_gate("trend_daily")
                self.assertEqual(bot._live_risk_share("trend_daily"), 0.0)   # no record: uncapped is never assumed
            self.assertFalse(allowed)
            self.assertIn("approval", reason)
        finally:
            bot.ACTIVATION_PATH = old_path


if __name__ == "__main__":
    unittest.main()
