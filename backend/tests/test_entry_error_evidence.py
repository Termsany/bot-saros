"""An entry order that raises must not be written off on one flat position reading (follow-up from PR #16).

The reservation is released only when the position is flat, the exchange confirms the order itself didn't fill
(not found / cancelled / rejected with nothing filled), and the position is still flat a moment later — the same
standard close_live_position applies before believing a flat exchange. Everything else is recovery: the risk
reservation stays, recovery_required is recorded and new entries stop."""
import json, os, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import ccxt
import bot as botmod
from backend.app import risk_manager as riskmgr_mod
from test_trend_live import FakeBinance, SIG_ON

SYM = "SOL/USDT:USDT"


class EntryErrorExchange(FakeBinance):
    """The entry order raises; what the exchange then says about the position and the order is scripted."""
    def __init__(self, positions_after=(0.0, 0.0), order=None, order_error=None):
        super().__init__()
        self.reads = list(positions_after)      # successive position readings for SOL after the error
        self.order, self.order_error = order, order_error
        self.lookups = []

    def create_order(self, sym, typ, side, qty, price, params):
        if "stopLossPrice" not in (params or {}) and not (params or {}).get("reduceOnly"):
            self.orders.append({"symbol": sym, "side": side, "qty": float(qty), "params": dict(params or {})})
            raise ccxt.NetworkError("binanceusdm timed out")              # the answer to the entry never arrives
        return super().create_order(sym, typ, side, qty, price, params)

    def fetch_positions(self, syms=None):
        q = self.reads.pop(0) if self.reads else 0.0
        return [{"symbol": SYM, "contracts": q, "side": "long"}] if q else []

    def fetch_order(self, oid, sym, params=None):
        self.lookups.append((oid, dict(params or {})))
        if self.order_error: raise self.order_error
        return {**self.order, "clientOrderId": oid}


class Base(unittest.TestCase):
    def setUp(self):
        self._cfg = dict(botmod.CONFIG); self._env = os.environ.get("BINANCE_ENV"); os.environ["BINANCE_ENV"] = "demo"
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._paths = (botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH, botmod.ENTRY_RECHECK_S)
        botmod.STATE_PATH = Path(self.td.name) / "state.json"; botmod.LOG_PATH = Path(self.td.name) / "t.log"
        botmod.RISK_PATH = Path(self.td.name) / "risk_state.json"; botmod.ENTRY_RECHECK_S = 0
        riskmgr_mod.save_risk_state(botmod.RISK_PATH, riskmgr_mod._default_state({
            "risk_per_trade_pct": 100.0, "max_aggregate_risk_pct": 100.0, "max_correlated_risk_pct": 100.0,
            "max_daily_loss_pct": 100.0, "max_drawdown_pct": 100.0}))
        botmod.CONFIG.update({"paper_trading": False, "market": "future", "leverage": 5, "trade_amount_usdt": 100,
                              "enabled_strategies": ["trend_daily"], "max_open_positions": 10, "use_percent_risk": False})
        botmod._ENTRY_BLOCK["reason"] = ""
        self.state = botmod.load_state()

    def tearDown(self):
        botmod.CONFIG.clear(); botmod.CONFIG.update(self._cfg)
        if self._env is None: os.environ.pop("BINANCE_ENV", None)
        else: os.environ["BINANCE_ENV"] = self._env
        botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH, botmod.ENTRY_RECHECK_S = self._paths
        self.td.cleanup()


class TrendEntryErrorTests(Base):
    def enter(self, ex):
        botmod.try_enter(SYM, SIG_ON, self.state, ex)

    def assert_recovery(self):
        self.assertIn(SYM, self.state.get("recovery_required", {}))
        self.assertTrue(botmod._ENTRY_BLOCK["reason"])

    def test_order_never_reached_the_exchange_is_released(self):
        ex = EntryErrorExchange(order_error=ccxt.OrderNotFound('binanceusdm {"code":-2013,"msg":"Order does not exist."}'))
        self.enter(ex)
        self.assertNotIn(SYM, self.state.get("recovery_required", {}))
        self.assertNotIn(SYM, self.state.get("pending_orders", {}))
        self.assertNotIn(SYM, self.state["positions"])
        self.assertTrue(ex.lookups and ex.lookups[0][1].get("origClientOrderId"))   # looked up by its client id

    def test_cancelled_order_with_nothing_filled_is_released(self):
        self.enter(EntryErrorExchange(order={"status": "canceled", "filled": 0}))
        self.assertNotIn(SYM, self.state.get("recovery_required", {}))

    def test_order_that_did_fill_is_recorded_not_dropped(self):
        # the answer was lost but the order filled: place_order finds it by its client id and the trade is kept
        ex = EntryErrorExchange(positions_after=(5.0, 5.0, 5.0), order={"status": "closed", "filled": 5.0, "average": 100.0})
        self.enter(ex)
        self.assertIn(SYM, self.state["positions"])
        self.assertEqual(ex.lookups[0][1].get("origClientOrderId"), ex.lookups[0][0])

    def test_order_lookup_failure_is_recovery(self):
        self.enter(EntryErrorExchange(order_error=ccxt.NetworkError("timeout")))
        self.assert_recovery()

    def test_position_showing_up_on_the_second_reading_is_recovery(self):
        self.enter(EntryErrorExchange(positions_after=(0.0, 5.0), order_error=ccxt.OrderNotFound("-2013")))
        self.assert_recovery()

    def test_open_order_still_working_is_recovery(self):
        self.enter(EntryErrorExchange(order={"status": "open", "filled": 0}))
        self.assert_recovery()


class SingleLegEntryErrorTests(Base):
    """The shared entry used by the other single-leg strategies (vol_breakout, rsi2_pullback, trend_breakout, ...)."""
    def enter(self, ex):
        return botmod._single_leg_live_entry(ex, self.state, SYM, "long", 100.0, 100.0, 60.0, None, "rsi2_pullback")

    def test_released_only_with_proof(self):
        self.assertIsNone(self.enter(EntryErrorExchange(order_error=ccxt.OrderNotFound("-2013"))))
        self.assertNotIn(SYM, self.state.get("recovery_required", {}))

    def test_one_flat_reading_with_unknown_order_is_recovery(self):
        self.assertIsNone(self.enter(EntryErrorExchange(order_error=ccxt.NetworkError("timeout"))))
        self.assertIn(SYM, self.state.get("recovery_required", {}))
        self.assertEqual(botmod._ENTRY_BLOCK["reason"], "live entry outcome requires recovery")

    def test_filled_order_is_kept(self):
        pos = self.enter(EntryErrorExchange(positions_after=(1.0, 1.0, 1.0), order={"status": "closed", "filled": 1.0, "average": 100.0}))
        self.assertIsNotNone(pos)
        self.assertNotIn(SYM, self.state.get("recovery_required", {}))

    def test_flat_reading_but_order_filled_on_a_non_timeout_error_is_recovery(self):
        # a non-network error skips place_order's own lookup: one flat reading + a filled order must not be released
        ex = EntryErrorExchange(order={"status": "closed", "filled": 1.0})
        ex.create_order = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("margin check failed"))
        self.assertIsNone(self.enter(ex))
        self.assertIn(SYM, self.state.get("recovery_required", {}))


class OutcomeTests(unittest.TestCase):
    def test_outcomes(self):
        class Ex:
            def __init__(self, r): self.r = r
            def fetch_order(self, oid, sym, params=None):
                if isinstance(self.r, Exception): raise self.r
                return {**self.r, "clientOrderId": oid}
        f = lambda r: botmod._entry_order_outcome(Ex(r), SYM, "raqm-x")
        self.assertEqual(f(ccxt.OrderNotFound("x")), "not_found")
        self.assertEqual(f(Exception('{"code":-2013,"msg":"Order does not exist."}')), "not_found")
        self.assertEqual(f(ccxt.NetworkError("x")), "unknown")
        self.assertEqual(f({"status": "canceled", "filled": 0}), "not_filled")
        self.assertEqual(f({"status": "expired", "filled": None}), "not_filled")
        self.assertEqual(f({"status": "canceled", "filled": 0.3}), "filled")       # a partial fill is a fill
        self.assertEqual(f({"status": "open", "filled": 0}), "unknown")
        self.assertEqual(f({"status": "closed", "filled": "junk"}), "unknown")


if __name__ == "__main__":
    unittest.main()
