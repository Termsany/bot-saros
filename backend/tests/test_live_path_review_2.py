"""Fixes from the pre-production review, part 2: baskets and the risk ledger (2026-10-29).

Baskets: a failed leg whose order went through was never unwound; an unconfirmed stop cancel counted as success;
a failed exit basket flagged the wrong coin and then blocked every later basket; restart reconciliation leaked the
reservations. Ledger: dashboard writes overwrote the bot's changes; the API and the bot used different files."""
import os, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "backend")); sys.path.insert(0, str(Path(__file__).resolve().parent))
import bot as botmod
from backend.app import risk_manager as rm
from test_trend_live import FakeBinance

LOOSE = {"risk_per_trade_pct": 100.0, "max_aggregate_risk_pct": 100.0, "max_correlated_risk_pct": 100.0,
         "max_daily_loss_pct": 100.0, "max_drawdown_pct": 100.0}
A, B, C = "A/USDT:USDT", "B/USDT:USDT", "C/USDT:USDT"


class Base(unittest.TestCase):
    def setUp(self):
        self._cfg = dict(botmod.CONFIG); self._env = os.environ.get("BINANCE_ENV"); os.environ["BINANCE_ENV"] = "demo"
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._saved = (botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH, botmod.ENTRY_RECHECK_S, botmod.FILL_LOOKUP_WAITS)
        botmod.STATE_PATH = Path(self.td.name) / "state.json"; botmod.LOG_PATH = Path(self.td.name) / "t.log"
        botmod.RISK_PATH = Path(self.td.name) / "risk.json"; botmod.ENTRY_RECHECK_S = 0; botmod.FILL_LOOKUP_WAITS = (0.0,)
        rm.save_risk_state(botmod.RISK_PATH, rm._default_state(LOOSE))
        botmod.CONFIG.update({"paper_trading": False, "market": "future", "leverage": 2, "trade_amount_usdt": 100,
                              "enabled_strategies": ["momentum_ls"], "max_open_positions": 50, "public_dir": None})
        botmod._ENTRY_BLOCK["reason"] = ""
        self.notified = []
        for target, value in (("notify", self.notified.append), ("_live_activation_gate", lambda s: (True, "")),
                              ("_refresh_funding_evidence", lambda *a, **k: None)):
            p = mock.patch.object(botmod, target, value); p.start(); self.addCleanup(p.stop)
        self.state = botmod.load_state()

    def tearDown(self):
        botmod.CONFIG.clear(); botmod.CONFIG.update(self._cfg)
        if self._env is None: os.environ.pop("BINANCE_ENV", None)
        else: os.environ["BINANCE_ENV"] = self._env
        (botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH, botmod.ENTRY_RECHECK_S, botmod.FILL_LOOKUP_WAITS) = self._saved
        botmod._ENTRY_BLOCK["reason"] = ""
        self.td.cleanup()

    def legs(self, *syms):
        return [botmod._phase2_leg(s, "long" if i == 0 else "short", 50, 10.0, 6.0 if i == 0 else 14.0, None, "momentum_ls", i)
                for i, s in enumerate(syms)]

    def risk_rows(self): return list(rm.load_risk_state(botmod.RISK_PATH)["open_risk"])
    def live_stops(self, ex, sym):
        return [o for o in ex.orders if o["symbol"] == sym and "stopLossPrice" in o["params"]
                and "stop-" + o["params"]["clientOrderId"] not in ex.cancelled]


class SilentLegB(FakeBinance):
    """Leg B fills on the exchange, but its answer has no filled quantity and its trades can't be read."""
    def create_order(self, sym, typ, side, qty, price, params):
        r = super().create_order(sym, typ, side, qty, price, params)
        if sym == B and "stopLossPrice" not in params and not params.get("reduceOnly"):
            return {"id": "e2", "clientOrderId": params.get("clientOrderId"), "filled": None, "status": "NEW"}
        return r
    def fetch_my_trades(self, sym, since=None, limit=20, params=None): raise Exception("timeout")


class FailedLegTests(Base):
    def test_leg_that_filled_before_failing_is_unwound(self):
        ex = SilentLegB()
        res = botmod._phase2_live_basket(ex, self.state, "momentum_ls", "t-entry", self.legs(A, B))
        self.assertEqual(res["status"], "compensated")
        self.assertEqual((ex.positions["A/USDT"], ex.positions["B/USDT"]), (0.0, 0.0))   # B was open: now closed
        self.assertEqual(self.live_stops(ex, A) + self.live_stops(ex, B), [])
        self.assertEqual(self.risk_rows(), []); self.assertEqual(self.state["positions"], {})

    def test_leg_with_unknown_position_stays_residual(self):
        class Blind(SilentLegB):
            def fetch_positions(self, syms=None):
                if syms and syms[0] == B: raise Exception("timeout")
                return super().fetch_positions(syms)
        res = botmod._phase2_live_basket(Blind(), self.state, "momentum_ls", "t-entry", self.legs(A, B))
        self.assertEqual(res["status"], "recovery_required")
        self.assertIn(B, [r["leg"]["symbol"] for r in res["residual"]])
        self.assertIn(B, self.state["recovery_required"]); self.assertTrue(botmod._ENTRY_BLOCK["reason"])

    def test_rejected_leg_is_proven_flat(self):
        class Rejects(FakeBinance):
            def create_order(self, sym, typ, side, qty, price, params):
                if sym == B and "stopLossPrice" not in params: raise Exception("rejected")
                return super().create_order(sym, typ, side, qty, price, params)
        res = botmod._phase2_live_basket(Rejects(), self.state, "momentum_ls", "t-entry", self.legs(A, B))
        self.assertEqual(res["status"], "compensated"); self.assertEqual(self.risk_rows(), [])


class UnconfirmedStopCancelTests(Base):
    def test_leg_closed_but_stop_not_cancelled_is_recovery_with_an_alert(self):
        class StuckStop(FakeBinance):
            def create_order(self, sym, typ, side, qty, price, params):
                if sym == B and "stopLossPrice" not in params: raise Exception("rejected")
                return super().create_order(sym, typ, side, qty, price, params)
            def fetch_open_orders(self, sym, *a):
                if a and isinstance(a[-1], dict): raise Exception("trigger view timeout")
                return super().fetch_open_orders(sym, *a)
        ex = StuckStop()
        res = botmod._phase2_live_basket(ex, self.state, "momentum_ls", "t-entry", self.legs(A, B))
        self.assertEqual(res["status"], "recovery_required")
        self.assertEqual(ex.positions["A/USDT"], 0.0)
        self.assertIn(A, self.state["recovery_required"]); self.assertTrue(self.notified)


class Closes(FakeBinance):
    fail = None
    def create_order(self, sym, typ, side, qty, price, params):
        if self.fail == sym and params.get("reduceOnly") and "stopLossPrice" not in params: raise Exception("close rejected")
        return super().create_order(sym, typ, side, qty, price, params)
    def fetch_my_trades(self, sym, since=None, limit=20, params=None):
        return [{"order": "c", "side": "sell", "price": 10.0, "amount": 10.0, "fee": {"cost": 0.04}}]


class FailedExitBasketTests(Base):
    def open_three(self, ex):
        legs = [botmod._phase2_leg(s, "long", 50, 10.0, 6.0, None, "momentum_ls", i) for i, s in enumerate((A, B, C))]
        self.assertEqual(botmod._phase2_live_basket(ex, self.state, "momentum_ls", "entry", legs)["status"], "filled")

    def exits(self, *syms):
        return [{"symbol": s, "side": "close_long", "action": "exit", "position": self.state["positions"][s], "price": 10.0,
                 "order": 0, "risk_usdt": 0, "notional_usdt": 0} for s in syms]

    def test_failed_leg_is_flagged_closed_leg_is_booked_later_exits_still_run(self):
        ex = Closes(); self.open_three(ex); ex.fail = B
        res = botmod._phase2_live_basket(ex, self.state, "momentum_ls", "rebalance-exit", self.exits(A, B, C), reserve=False)
        self.assertEqual(res["status"], "exit_retry")                               # nothing changed for B: retried, nothing pending
        self.assertEqual([r["leg"]["symbol"] for r in res["residual"]], [B])        # the coin still open
        self.assertNotIn(A, self.state["positions"])                                 # A really closed: booked
        self.assertNotIn(f"momentum_ls:{A}", self.risk_rows())
        self.assertNotIn(C, self.state["positions"]); self.assertEqual(ex.positions["C/USDT"], 0.0)   # tried after B: closed too
        # B's close was refused and B is exactly as it was: retried, not locked for a person (full review, 2026-10-30)
        self.assertNotIn(B, self.state.get("recovery_required", {})); self.assertTrue(self.notified)
        ex.fail = None; botmod._ENTRY_BLOCK["reason"] = ""
        later = botmod._phase2_live_basket(ex, self.state, "momentum_ls", "retry-exit", self.exits(B), reserve=False)
        self.assertEqual(later["status"], "filled"); self.assertEqual(ex.positions["B/USDT"], 0.0)

    def test_residual_clears_itself_once_flat_and_its_stops_are_gone(self):
        ex = Closes(); self.open_three(ex); ex.fail = B
        botmod._phase2_live_basket(ex, self.state, "momentum_ls", "rebalance-exit", self.exits(A, B, C), reserve=False)
        ex.fail = None
        ex.positions["B/USDT"] = 0.0; ex.positions["C/USDT"] = 0.0     # closed by hand on the exchange
        botmod._phase2_live_basket(ex, self.state, "momentum_ls", "nothing", [botmod._phase2_leg("D/USDT:USDT", "long", 50, 10.0, 6.0, None, "momentum_ls")])
        self.assertFalse([k for k in self.state.get("recovery_required", {}) if k.startswith("execution:")])


class RestartReconcileTests(Base):
    def crashed_row(self, ex):
        """A basket that reserved its risk and placed its stops, then the process died before recording it."""
        engine = botmod._phase2_engine(self.state)
        legs = self.legs(A, B)
        for n, leg in enumerate(legs): leg["client_order_id"] = f"raqm-crash{n:022d}"
        ok, _ = rm.pre_trade_gate_basket(botmod.RISK_PATH, strategy="momentum_ls", equity_usdt=1000.0,
            legs=[{k: leg[k] for k in ("symbol", "side", "risk_usdt", "notional_usdt", "correlation_group")} for leg in legs], equity_observed_at=rm._now())
        self.assertTrue(ok)
        engine._write_execution("exec-crash", "momentum_ls", "t-entry", "started", {"legs": legs, "cycle_token": "x"})
        for leg in legs:
            from backend.app.oco import place_oco_orders
            place_oco_orders(ex, leg["symbol"], leg["side"], 1.0, leg["sl"], None, paper=False, pos_id=leg["client_order_id"])
        return legs

    def test_flat_row_releases_its_reservations_and_stops(self):
        ex = FakeBinance(); self.crashed_row(ex)
        self.assertEqual(len(self.risk_rows()), 2)
        botmod._phase2_live_basket(ex, self.state, "momentum_ls", "next", self.legs("D/USDT:USDT"))
        self.assertEqual([r for r in self.risk_rows() if "D/" not in r], [])
        self.assertEqual(self.live_stops(ex, A) + self.live_stops(ex, B), [])
        self.assertNotIn("execution:exec-crash", self.state.get("recovery_required", {}))

    def test_flat_row_with_uncancellable_stops_stays_in_recovery(self):
        class StuckStop(FakeBinance):
            def fetch_open_orders(self, sym, *a):
                if a and isinstance(a[-1], dict): raise Exception("trigger view timeout")
                return super().fetch_open_orders(sym, *a)
        ex = StuckStop(); self.crashed_row(ex)
        self.assertIsNone(botmod._phase2_live_basket(ex, self.state, "momentum_ls", "next", self.legs("D/USDT:USDT")))
        self.assertIn("execution:exec-crash", self.state["recovery_required"])


class LedgerWriteTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.path = Path(self.td.name) / "risk.json"
        rm.save_risk_state(self.path, rm._default_state({**LOOSE, "max_drawdown_pct": 5.0}))
    def tearDown(self): self.td.cleanup()

    def test_dashboard_writes_keep_the_bots_changes(self):
        ok, _ = rm.pre_trade_gate(self.path, strategy="s", symbol="X", side="long", risk_usdt=1, notional_usdt=10,
                                  equity_usdt=1000, correlation_group="alts", equity_observed_at=rm._now())
        self.assertTrue(ok)
        rm.update_equity_and_check_kill_switch(self.path, 1000.0, equity_observed_at=rm._now()); rm.update_equity_and_check_kill_switch(self.path, 1.0, equity_observed_at=rm._now())   # trips
        rm.update_limits(self.path, {"risk_per_trade_pct": 0.5})
        rm.record_realized_pnl(self.path, -3.0)
        st = rm.load_risk_state(self.path)
        self.assertTrue(st["kill_switch"]["tripped"]); self.assertIn("s:X", st["open_risk"])
        self.assertEqual(st["limits"]["risk_per_trade_pct"], 0.5); self.assertEqual(st["daily"]["realized_pnl"], -3.0)

    def test_manual_trip_keeps_reservations(self):
        rm.pre_trade_gate(self.path, strategy="s", symbol="X", side="long", risk_usdt=1, notional_usdt=10, equity_usdt=1000, correlation_group="alts", equity_observed_at=rm._now())
        rm.trip_kill_switch(self.path, "operator")
        st = rm.load_risk_state(self.path)
        self.assertTrue(st["kill_switch"]["tripped"]); self.assertIn("s:X", st["open_risk"])


class SharedLedgerPathTests(unittest.TestCase):
    def test_api_and_bot_resolve_the_same_files(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d, mock.patch.dict(os.environ, {"RAQM_RISK_DIR": d}):
            from app import main as api
            self.assertEqual(api._risk_path(), Path(d) / "risk_state.json")
            self.assertEqual(rm.ledger_dir(ROOT) / "risk_state.json", Path(d) / "risk_state.json")   # bot.RISK_PATH's rule

    def _run(self, env):
        e = {k: v for k, v in os.environ.items() if k not in ("ALLOW_LIVE_TRADING", "BINANCE_ENV", "RAQM_RISK_DIR")}
        e.update(env); e["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run([sys.executable, str(ROOT / "bot.py"), "--live", "--strategy", "trend_daily", "--once"],
                              capture_output=True, text=True, env=e, cwd=tempfile.gettempdir(), timeout=60, encoding="utf-8")

    def test_real_money_needs_the_shared_ledger_dir(self):
        r = self._run({"BINANCE_ENV": "live", "ALLOW_LIVE_TRADING": "true"})
        self.assertNotEqual(r.returncode, 0); self.assertIn("RAQM_RISK_DIR", r.stderr)

    def test_unusable_ledger_stops_the_bot_at_start(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            blocker = Path(d) / "file"; blocker.write_text("x")             # a file where the folder should be
            r = self._run({"BINANCE_ENV": "demo", "RAQM_RISK_DIR": str(blocker / "ledger")})
        self.assertNotEqual(r.returncode, 0); self.assertIn("دفتر المخاطرة", r.stderr)


if __name__ == "__main__":
    unittest.main()
