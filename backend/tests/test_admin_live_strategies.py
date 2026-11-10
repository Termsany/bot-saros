"""Yes/no per strategy on the admin's own live account (2026-10-30): every live strategy runs as its own bot on the
same Binance account; the activation record says which may enter. Bots must not take each other's positions for
strangers."""
import json
import os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "backend")); sys.path.insert(0, str(Path(__file__).resolve().parent))
import bot as botmod
from backend.app import risk_manager as rm
from test_trend_live import FakeBinance
from test_security import ApiAuthTests


def trusted_evidence(strategies):
    fields = ("adapter_implemented", "recovery_tests", "security_approved", "testnet_validated")
    from app.testnet_readiness import evidence_artifact_sha256
    doc = {"schema_version": 2, "provenance": {"reviewed_commit_sha": "a" * 40, "evidence_artifact_sha256": "",
            "evidence_id": "test-evidence-20261102", "producer": "testnet-readiness-job", "owner": "readiness-owner",
            "independent_review": {"reviewers": ["reviewer-a", "reviewer-b"], "open_findings": 0}},
            "strategies": {s: {f: {"value": True, "verified": True} for f in fields} for s in strategies}}
    doc["provenance"]["evidence_artifact_sha256"] = evidence_artifact_sha256(doc)
    return doc


class SameAccountTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._saved = (botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH, dict(botmod.CONFIG))
        botmod.STATE_PATH = Path(self.td.name) / "s.json"; botmod.LOG_PATH = Path(self.td.name) / "l.log"
        botmod.RISK_PATH = Path(self.td.name) / "r.json"
        rm.save_risk_state(botmod.RISK_PATH, rm._default_state())
        botmod.CONFIG.update({"paper_trading": False, "enabled_strategies": ["vol_breakout"]})
        botmod._ENTRY_BLOCK["reason"] = ""
        p = mock.patch.object(botmod, "notify"); p.start(); self.addCleanup(p.stop)

    def tearDown(self):
        botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH, cfg = self._saved
        botmod.CONFIG.clear(); botmod.CONFIG.update(cfg); botmod._ENTRY_BLOCK["reason"] = ""
        self.td.cleanup()

    def test_another_strategys_position_does_not_block_entries(self):
        rm.register_open_risk(botmod.RISK_PATH, strategy="trend_daily", symbol="BTC/USDT:USDT", side="long", risk_usdt=1, notional_usdt=10)
        ex = FakeBinance(); ex.positions["BTC/USDT"] = 0.5
        state = botmod.load_state(); botmod.reconcile_live(state, ex)
        self.assertEqual(botmod._ENTRY_BLOCK["reason"], "")

    def test_a_position_no_strategy_holds_still_blocks(self):
        ex = FakeBinance(); ex.positions["BTC/USDT"] = 0.5
        state = botmod.load_state(); botmod.reconcile_live(state, ex)
        self.assertIn("BTC/USDT", botmod._ENTRY_BLOCK["reason"])

    def test_basket_bots_write_their_live_status_whatever_path_the_cycle_took(self):
        for strat, fn in (("momentum_ls", "run_once_momentum"), ("ratio_trend", "run_once_ratio"), ("listing_short", "run_once_listing")):
            botmod.CONFIG["enabled_strategies"] = [strat]
            with mock.patch.object(botmod, "strategy_exchange", return_value=mock.Mock()), \
                 mock.patch.object(botmod, fn, side_effect=RuntimeError("cycle failed")), \
                 mock.patch.object(botmod, "write_live_status") as w:
                with self.assertRaises(RuntimeError): botmod.run_once()
            w.assert_called_once()

    def test_basket_bots_carry_out_the_sites_close_button(self):
        # the 3 basket runners never read their close requests: the site's close waited unanswered
        for fn in ("run_once_momentum", "run_once_ratio", "run_once_listing"):
            with mock.patch.object(botmod, "reconcile_live"), mock.patch.object(botmod, "process_manual_closes", side_effect=RuntimeError("called")) as pmc:
                with self.assertRaises(RuntimeError): getattr(botmod, fn)(mock.Mock())
            pmc.assert_called_once()

    def test_api_and_bot_list_the_same_live_strategies(self):
        import app.main as m
        self.assertEqual(set(m.LIVE_STRATEGIES), botmod.LIVE_READY_STRATEGIES)


class StrategyTogglesApiTests(ApiAuthTests):
    def setUp(self):
        super().setUp()
        import app.main as m; self.m = m
        self.p = mock.patch.object(m, "LIVE_ACTIVATION_PATH", Path(self.tmp.name) / "act.sqlite3"); self.p.start()
        self.p_dir = mock.patch.object(m, "BOT_DIR", Path(self.tmp.name)); self.p_dir.start()   # the audit log
        (Path(self.tmp.name) / "readiness_evidence.json").write_text(
            json.dumps(trusted_evidence(m.LIVE_STRATEGIES)), encoding="utf-8")

    def tearDown(self):
        self.p.stop(); self.p_dir.stop(); super().tearDown()

    def put(self, strategies):
        return self.c.post("/api/live/strategies", headers=self.h("admin-token"), json={"account": "main", "strategies": strategies})

    def test_refused_while_the_server_switch_is_off(self):
        with mock.patch.dict(os.environ, {"ALLOW_LIVE_TRADING": ""}):
            self.assertEqual(self.put(["trend_daily"]).status_code, 403)

    def test_readiness_is_not_taken_from_the_request(self):
        from app import live_activation as la
        (Path(self.tmp.name) / "readiness_evidence.json").unlink()
        with mock.patch.dict(os.environ, {"ALLOW_LIVE_TRADING": "true", "READINESS_EXPECTED_COMMIT_SHA": "a" * 40}):
            r = self.c.post("/api/live/strategies", headers=self.h("admin-token"), json={
                "account": "main", "strategies": ["trend_daily"],
                "readiness": {"trend_daily": True}, "risk_allocation": {"trend_daily": 1.0}})
            self.assertEqual(r.status_code, 422)
            self.assertIsNone(la.active_record(self.m.LIVE_ACTIVATION_PATH))

    def test_yes_no_per_strategy(self):
        from app import live_activation as la
        path = self.m.LIVE_ACTIVATION_PATH
        with mock.patch.dict(os.environ, {"ALLOW_LIVE_TRADING": "true", "READINESS_EXPECTED_COMMIT_SHA": "a" * 40}):
            self.assertEqual(self.put(["trend_daily", "momentum_ls"]).status_code, 200)
            self.assertTrue(la.live_activation_allowed(path, strategy="momentum_ls", account="main")[0])
            self.assertFalse(la.live_activation_allowed(path, strategy="ratio_trend", account="main")[0])
            rows = {r["id"]: r["on"] for r in self.c.get("/api/live/strategies", headers=self.h("admin-token")).json()["strategies"]}
            self.assertEqual({k for k, v in rows.items() if v}, {"trend_daily", "momentum_ls"})
            self.put(["ratio_trend"])                                            # a new choice replaces the old one
            self.assertFalse(la.live_activation_allowed(path, strategy="momentum_ls", account="main")[0])
            self.put([])                                                         # all off
            self.assertFalse(la.live_activation_allowed(path, strategy="ratio_trend", account="main")[0])
        self.assertEqual(self.put(["ict"]).status_code, 400)

    def test_demo_yes_no_needs_no_server_switch_and_never_touches_the_live_record(self):
        from app import live_activation as la
        demo = Path(self.tmp.name) / "demo" / "live_activation.sqlite3"
        with mock.patch.object(self.m, "DEMO_ACTIVATION_PATH", demo), mock.patch.dict(os.environ, {"ALLOW_LIVE_TRADING": ""}):
            rows = self.c.get("/api/live/strategies?env=demo", headers=self.h("admin-token")).json()["strategies"]
            self.assertTrue(all(r["on"] for r in rows))                         # nothing chosen yet: all may enter
            r = self.c.post("/api/live/strategies", headers=self.h("admin-token"), json={"env": "demo", "strategies": ["momentum_ls"]})
            self.assertEqual(r.status_code, 200)
            self.assertTrue(la.demo_strategy_allowed(demo, strategy="momentum_ls")[0])
            self.assertFalse(la.demo_strategy_allowed(demo, strategy="trend_daily")[0])
            self.assertIsNone(la.active_record(self.m.LIVE_ACTIVATION_PATH))   # real money untouched


class DemoGateTests(unittest.TestCase):
    def test_demo_bot_obeys_the_demo_choice(self):
        from app import live_activation as la
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d, mock.patch.dict(os.environ, {"BINANCE_ENV": "demo"}), \
             mock.patch.object(botmod, "ACTIVATION_PATH", Path(d) / "live_activation.sqlite3"):
            self.assertTrue(botmod._live_activation_gate("ratio_trend")[0])     # nothing chosen: allowed, file not created
            self.assertFalse((Path(d) / "live_activation.sqlite3").exists())
            la.set_demo_strategies(botmod.ACTIVATION_PATH, strategies=["trend_daily"], set_by="t")
            self.assertFalse(botmod._live_activation_gate("ratio_trend")[0])
            self.assertTrue(botmod._live_activation_gate("trend_daily")[0])


if __name__ == "__main__":
    unittest.main()
