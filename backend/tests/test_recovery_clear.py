"""Audited recovery resolution: the API only queues a request; the live bot clears a mark only after proving flat."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "backend")); sys.path.insert(0, str(Path(__file__).resolve().parent))

import bot as botmod
from backend.app import admin_control
from backend.app import risk_manager as rm
from backend.app.multi_leg_execution import MultiLegExecutionEngine
from test_security import ApiAuthTests
from test_trend_live import FakeBinance


class RecoveryClearApiTests(ApiAuthTests):
    def setUp(self):
        super().setUp()
        import app.main as m
        self.m = m
        self.ipc = Path(self.tmp.name) / "ipc"
        self.p_ipc = mock.patch.object(m, "IPC_DIR", self.ipc); self.p_ipc.start()
        self.p_dir = mock.patch.object(m, "BOT_DIR", Path(self.tmp.name)); self.p_dir.start()

    def tearDown(self):
        self.p_ipc.stop(); self.p_dir.stop()
        super().tearDown()

    def status(self, strategy="ratio_trend", positions=(), review=None, running=True):
        d = self.ipc / strategy; d.mkdir(parents=True, exist_ok=True)
        (d / "live_status.json").write_text(json.dumps({
            "updated": datetime.now(timezone.utc).isoformat(), "running": running,
            "positions": list(positions), "review": review or {},
        }), encoding="utf-8")

    def clear(self, **body):
        payload = {"strategy": "ratio_trend", "key": "BTC/USDT:USDT", "reason": "checked on the exchange",
                   "confirm": True, **body}
        return self.c.post("/api/admin/recovery/clear", headers=self.h("admin-token"), json=payload)

    def test_confirmation_and_reason_are_required(self):
        self.status(review={"BTC/USDT:USDT": {"reason": "x"}})
        self.assertEqual(self.clear(confirm=False).status_code, 400)
        self.assertEqual(self.clear(reason="").status_code, 422)

    def test_refused_when_the_bot_is_not_running(self):
        self.status(review={"BTC/USDT:USDT": {"reason": "x"}}, running=False)
        self.assertEqual(self.clear().status_code, 409)

    def test_refused_for_an_unknown_review_key(self):
        self.status(review={"ETH/USDT:USDT": {"reason": "x"}})
        self.assertEqual(self.clear().status_code, 404)

    def test_refused_while_the_bot_still_holds_the_coin(self):
        self.status(positions=[{"symbol": "BTC/USDT"}], review={"BTC/USDT:USDT": {"reason": "x"}})
        r = self.clear()
        self.assertEqual(r.status_code, 409)
        self.assertIn("still holds", r.json()["detail"])

    def test_queues_an_audited_resolve_request(self):
        self.status(review={"BTC/USDT:USDT": {"reason": "x"}})
        r = self.clear()
        self.assertEqual(r.status_code, 200)
        rid = r.json()["id"]
        command = json.loads((self.ipc / "ratio_trend" / "commands" / f"resolve-{rid}.json").read_text(encoding="utf-8"))
        self.assertEqual(command["key"], "BTC/USDT:USDT")
        self.assertEqual(command["reason"], "checked on the exchange")
        self.assertEqual(command["by"], "admin@example.com")
        con = admin_control.connect(Path(self.tmp.name))
        try:
            row = con.execute("SELECT action,result,details FROM admin_audit WHERE action='recovery_clear'").fetchone()
        finally:
            con.close()
        self.assertEqual(row["result"], "requested")
        self.assertIn("checked on the exchange", row["details"])
        self.assertEqual(self.c.get(f"/api/admin/recovery/ratio_trend/{rid}", headers=self.h("admin-token")).json(),
                         {"done": False, "pending": True})

    def test_recovery_list_includes_each_live_bot_review(self):
        self.status(review={"BTC/USDT:USDT": {"reason": "x"}})
        data = self.c.get("/api/admin/recovery", headers=self.h("admin-token")).json()
        self.assertEqual(data["live"]["ratio_trend"]["review"], {"BTC/USDT:USDT": {"reason": "x"}})
        self.assertTrue(data["live"]["ratio_trend"]["running"])


class RecoveryClearBotTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.td.name)
        self.ipc = self.root / "ipc"
        self._saved = (botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH, dict(botmod.CONFIG),
                       os.environ.get("RAQM_IPC_DIR"), os.environ.get("BINANCE_ENV"))
        botmod.STATE_PATH = self.root / "state.json"; botmod.LOG_PATH = self.root / "l.log"
        botmod.RISK_PATH = self.root / "risk.json"
        rm.save_risk_state(botmod.RISK_PATH, rm._default_state())
        botmod.CONFIG.update({"paper_trading": False, "enabled_strategies": ["ratio_trend"]})
        os.environ["RAQM_IPC_DIR"] = str(self.ipc); os.environ["BINANCE_ENV"] = "demo"
        p = mock.patch.object(botmod, "notify"); p.start(); self.addCleanup(p.stop)

    def tearDown(self):
        (botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH, cfg,
         ipc, env) = self._saved
        botmod.CONFIG.clear(); botmod.CONFIG.update(cfg)
        if ipc is None: os.environ.pop("RAQM_IPC_DIR", None)
        else: os.environ["RAQM_IPC_DIR"] = ipc
        if env is None: os.environ.pop("BINANCE_ENV", None)
        else: os.environ["BINANCE_ENV"] = env
        self.td.cleanup()

    def drop(self, key, reason="checked", rid="a" * 32):
        d = self.ipc / "commands"; d.mkdir(parents=True, exist_ok=True)
        path = d / f"resolve-{rid}.json"
        path.write_text(json.dumps({"id": rid, "key": key, "reason": reason,
                                    "at_epoch": datetime.now(timezone.utc).timestamp(), "by": "admin@example.com"}),
                        encoding="utf-8")
        return path

    def result(self, rid="a" * 32):
        return json.loads((self.ipc / "results" / f"{rid}.json").read_text(encoding="utf-8"))

    def state_with(self, key):
        state = botmod.load_state()
        state.setdefault("recovery_required", {})[key] = {"reason": "manual test",
                                                          "at": datetime.now(timezone.utc).isoformat()}
        botmod.save_state(state)
        return state

    @staticmethod
    def holding(*legs):
        """FakeBinance whose position read returns the given open contracts for the requested symbol."""
        ex = FakeBinance()
        rows = [{"symbol": leg, "contracts": qty} for leg, qty in legs]
        ex.fetch_positions = lambda syms=None: [r for r in rows if not syms or r["symbol"] in syms]
        return ex

    def test_symbol_mark_is_cleared_only_when_the_exchange_is_flat(self):
        state = self.state_with("BTC/USDT:USDT")
        ex = self.holding(("BTC/USDT:USDT", 0.5))
        self.drop("BTC/USDT:USDT")
        botmod.process_manual_closes(state, ex, {})
        self.assertIn("BTC/USDT:USDT", state["recovery_required"])
        self.assertFalse(self.result()["ok"])

    def test_bot_state_holding_the_coin_is_refused_even_if_the_exchange_read_is_flat(self):
        state = self.state_with("BTC/USDT:USDT")
        state["positions"]["BTC/USDT:USDT"] = {"side": "long", "entry": 100.0, "qty": 1.0}
        botmod.save_state(state)
        self.drop("BTC/USDT:USDT", rid="b" * 32)
        botmod.process_manual_closes(state, FakeBinance(), {})
        self.assertIn("BTC/USDT:USDT", state["recovery_required"])
        self.assertFalse(self.result("b" * 32)["ok"])

    def test_flat_symbol_mark_is_cleared_and_recorded(self):
        state = self.state_with("BTC/USDT:USDT")
        self.drop("BTC/USDT:USDT", rid="c" * 32)
        botmod.process_manual_closes(state, FakeBinance(), {})
        self.assertNotIn("BTC/USDT:USDT", state["recovery_required"])
        out = self.result("c" * 32)
        self.assertTrue(out["ok"], out)
        self.assertFalse((self.ipc / "commands" / f"resolve-{'c' * 32}.json").exists())

    def execution(self, execution_id="exec-test0001", symbol="BTC/USDT:USDT"):
        engine = botmod._phase2_engine(botmod.load_state())
        engine._write_execution(execution_id, "ratio_trend", "entry", "recovery_required",
                                {"legs": [{"symbol": symbol, "side": "long", "action": "entry"}],
                                 "intent": "entry", "cycle_token": "tok-1"},
                                [{"leg": {"symbol": symbol}, "reason": "residual"}])
        state = self.state_with(f"execution:{execution_id}")
        state["recovery_required"][f"execution:{execution_id}"]["execution_id"] = execution_id
        state.setdefault("_execution_cycles", {})["ratio_trend:entry"] = "tok-1"
        botmod.save_state(state)
        return engine, state

    def test_execution_mark_refuses_an_open_residual_leg(self):
        engine, state = self.execution()
        ex = self.holding(("BTC/USDT:USDT", 0.5))
        self.drop("execution:exec-test0001", rid="d" * 32)
        botmod.process_manual_closes(state, ex, {})
        self.assertIn("execution:exec-test0001", state["recovery_required"])
        self.assertTrue(engine.pending())
        self.assertFalse(self.result("d" * 32)["ok"])

    def test_execution_mark_is_cleared_only_after_flat_and_stops_pending(self):
        engine, state = self.execution()
        self.drop("execution:exec-test0001", rid="e" * 32)
        botmod.process_manual_closes(state, FakeBinance(), {})
        self.assertNotIn("execution:exec-test0001", state["recovery_required"])
        # reconcile must not resurrect it from the durable journal
        self.assertEqual(engine.pending(), [])
        self.assertNotIn("ratio_trend:entry", state.get("_execution_cycles", {}))
        self.assertTrue(self.result("e" * 32)["ok"])


class ManualResolveJournalTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.td.name)
        self.engine = MultiLegExecutionEngine(self.root / "state.json", risk_manager=rm,
                                              risk_path=self.root / "risk.json")

    def tearDown(self):
        self.td.cleanup()

    def test_requires_a_reason_and_exchange_confirmation(self):
        with self.assertRaises(ValueError):
            self.engine.resolve_manually("exec-1", reason="", confirmed_flat=True)
        with self.assertRaises(ValueError):
            self.engine.resolve_manually("exec-1", reason="checked", confirmed_flat=False)

    def test_unknown_execution_is_refused(self):
        with self.assertRaises(KeyError):
            self.engine.resolve_manually("exec-missing", reason="checked", confirmed_flat=True)

    def test_resolution_is_terminal_and_audited(self):
        self.engine._write_execution("exec-1", "ratio_trend", "entry", "recovery_required",
                                     {"legs": [{"symbol": "BTC/USDT:USDT", "side": "long", "action": "entry"}]},
                                     [{"leg": {"symbol": "BTC/USDT:USDT"}}])
        con = self.engine._connect()
        try:   # the durable residual row the real execute() path writes with the execution
            con.execute("INSERT OR REPLACE INTO execution_residuals VALUES(?,?,?,?,?)",
                        ("exec-1", json.dumps([{"leg": {"symbol": "BTC/USDT:USDT"}}]), "open",
                         datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()))
        finally:
            con.close()
        out = self.engine.resolve_manually("exec-1", reason="flat on Binance", actor="admin", confirmed_flat=True)
        self.assertEqual(out["status"], "manually_resolved")
        self.assertEqual(self.engine.pending(), [])
        con = self.engine._connect()
        try:
            row = con.execute("SELECT status,residual FROM executions WHERE execution_id='exec-1'").fetchone()
            residual = con.execute("SELECT status FROM execution_residuals WHERE execution_id='exec-1'").fetchone()
        finally:
            con.close()
        self.assertEqual(row["status"], "manually_resolved")
        self.assertIn("flat on Binance", row["residual"])
        self.assertEqual(residual["status"], "resolved")


if __name__ == "__main__":
    unittest.main()
