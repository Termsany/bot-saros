import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend.app import live_activation
from backend.app.testnet_readiness import evidence_artifact_sha256
import bot


def evidence(*strategies):
    """A trusted, fully verified readiness document (the only thing activation may derive readiness from)."""
    fields = ("adapter_implemented", "recovery_tests", "security_approved", "testnet_validated")
    doc = {"schema_version": 2,
           "provenance": {"reviewed_commit_sha": "a" * 40, "evidence_artifact_sha256": "",
                          "evidence_id": "evidence-20261102-001", "producer": "testnet-readiness-job",
                          "owner": "readiness-owner", "independent_review": {"reviewers": ["a", "b"], "open_findings": 0}},
           "strategies": {s: {f: {"value": True, "verified": True} for f in fields} for s in strategies}}
    doc["provenance"]["evidence_artifact_sha256"] = evidence_artifact_sha256(doc)
    return doc


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
                    strategies=["trend_daily"], risk_allocation={"trend_daily": 0.25}, readiness_evidence=evidence("trend_daily"), expected_reviewed_commit_sha="a" * 40)

    def test_activation_requires_every_gate(self):
        with mock.patch.dict(os.environ, {"ALLOW_LIVE_TRADING": "true", "READINESS_EXPECTED_COMMIT_SHA": "a" * 40}):
            with self.assertRaises(ValueError):
                live_activation.activate(self.path, environment="live", account="live-main", approved_by="admin",
                    strategies=["trend_daily", "wave_flats"], risk_allocation={"trend_daily": 0.25},
                    readiness_evidence=evidence("trend_daily"), expected_reviewed_commit_sha="a" * 40)

    def test_readiness_cannot_be_self_declared(self):
        # The old call passed readiness={"trend_daily": True}; now only verified evidence can satisfy the gate.
        with mock.patch.dict(os.environ, {"ALLOW_LIVE_TRADING": "true", "READINESS_EXPECTED_COMMIT_SHA": "a" * 40}):
            with self.assertRaises(ValueError):
                live_activation.activate(self.path, environment="live", account="live-main", approved_by="admin",
                    strategies=["trend_daily"], risk_allocation={"trend_daily": 0.25}, readiness_evidence={})
            self.assertIsNone(live_activation.active_record(self.path))

    def test_activation_matches_account_strategy_and_readiness(self):
        with mock.patch.dict(os.environ, {"ALLOW_LIVE_TRADING": "true", "READINESS_EXPECTED_COMMIT_SHA": "a" * 40}):
            aid = live_activation.activate(self.path, environment="live", account="live-main", approved_by="admin",
                strategies=["trend_daily"], risk_allocation={"trend_daily": 0.25},
                readiness_evidence=evidence("trend_daily"), expected_reviewed_commit_sha="a" * 40)
            self.assertTrue(aid.startswith("act-"))
            self.assertEqual(live_activation.live_activation_allowed(self.path, strategy="trend_daily", account="live-main"), (True, None))
            self.assertFalse(live_activation.live_activation_allowed(self.path, strategy="wave_flats", account="live-main")[0])
            self.assertFalse(live_activation.live_activation_allowed(self.path, strategy="trend_daily", account="other")[0])
            self.assertEqual(live_activation.strategy_risk_share(self.path, strategy="trend_daily", account="live-main"), 0.25)
            self.assertIsNone(live_activation.strategy_risk_share(self.path, strategy="trend_daily", account="other"))

    def test_allocation_defaults_to_an_equal_split_and_is_recorded(self):
        with mock.patch.dict(os.environ, {"ALLOW_LIVE_TRADING": "true", "READINESS_EXPECTED_COMMIT_SHA": "a" * 40}):
            live_activation.activate(self.path, environment="live", account="live-main", approved_by="admin",
                strategies=["trend_daily", "momentum_ls"],
                readiness_evidence=evidence("trend_daily", "momentum_ls"))
            record = live_activation.active_record(self.path)
            self.assertEqual(record["risk_allocation"], {"trend_daily": 0.5, "momentum_ls": 0.5})
            self.assertEqual(record["readiness"], {"trend_daily": True, "momentum_ls": True})

    def test_allocations_may_not_exceed_the_aggregate_budget(self):
        with mock.patch.dict(os.environ, {"ALLOW_LIVE_TRADING": "true", "READINESS_EXPECTED_COMMIT_SHA": "a" * 40}):
            with self.assertRaises(ValueError):
                live_activation.activate(self.path, environment="live", account="live-main", approved_by="admin",
                    strategies=["trend_daily", "momentum_ls"],
                    risk_allocation={"trend_daily": 0.7, "momentum_ls": 0.7},
                    readiness_evidence=evidence("trend_daily", "momentum_ls"))

    def test_revoke_is_immediate_and_audited(self):
        with mock.patch.dict(os.environ, {"ALLOW_LIVE_TRADING": "true", "READINESS_EXPECTED_COMMIT_SHA": "a" * 40}):
            aid = live_activation.activate(self.path, environment="live", account="live-main", approved_by="admin",
                strategies=["trend_daily"], risk_allocation={"trend_daily": 0.25},
                readiness_evidence=evidence("trend_daily"), expected_reviewed_commit_sha="a" * 40)
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
