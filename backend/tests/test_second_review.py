"""Fixes from the second pre-production review (2026-10-29, at 8bf8ee2): each test reproduces a finding.

Single-leg: a position known to have no stop was never closed again; a close that raised but filled left its stop
on the exchange; a refused stop made the bot buy and sell every cycle; a stop was sized on the fills visible so far;
a crash between entry and stop left the position bare. Baskets: a ratio pair kept a leg the exchange had closed; a
failed leg with an unreadable position never got a stop; a retried basket reused its order ids."""
import os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "backend")); sys.path.insert(0, str(Path(__file__).resolve().parent))
import bot as botmod
from backend.app import risk_manager as rm
from test_trend_live import FakeBinance
from test_live_ratio_trend import RatioFakeBinance, A, B

S = "SOL/USDT:USDT"


class Base(unittest.TestCase):
    def setUp(self):
        self._cfg = dict(botmod.CONFIG); self._env = os.environ.get("BINANCE_ENV"); os.environ["BINANCE_ENV"] = "demo"
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._saved = (botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH, botmod.ENTRY_RECHECK_S, botmod.FILL_LOOKUP_WAITS, dict(botmod.RATIO))
        botmod.STATE_PATH = Path(self.td.name) / "s.json"; botmod.LOG_PATH = Path(self.td.name) / "l.log"
        botmod.RISK_PATH = Path(self.td.name) / "r.json"; botmod.ENTRY_RECHECK_S = 0; botmod.FILL_LOOKUP_WAITS = (0.0,)
        rm.save_risk_state(botmod.RISK_PATH, rm._default_state({"risk_per_trade_pct": 100.0, "max_aggregate_risk_pct": 100.0,
            "max_correlated_risk_pct": 100.0, "max_daily_loss_pct": 100.0, "max_drawdown_pct": 100.0}))
        botmod.CONFIG.update({"paper_trading": False, "market": "future", "leverage": 2, "trade_amount_usdt": 100,
                              "max_open_positions": 50, "use_percent_risk": False, "public_dir": None})
        botmod._ENTRY_BLOCK["reason"] = ""
        self.notified = []
        for target, value in (("notify", self.notified.append), ("_live_activation_gate", lambda s: (True, ""))):
            p = mock.patch.object(botmod, target, value); p.start(); self.addCleanup(p.stop)
        self.state = botmod.load_state()

    def tearDown(self):
        botmod.CONFIG.clear(); botmod.CONFIG.update(self._cfg)
        if self._env is None: os.environ.pop("BINANCE_ENV", None)
        else: os.environ["BINANCE_ENV"] = self._env
        (botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH, botmod.ENTRY_RECHECK_S, botmod.FILL_LOOKUP_WAITS, ratio) = self._saved
        botmod.RATIO.clear(); botmod.RATIO.update(ratio); botmod._ENTRY_BLOCK["reason"] = ""
        self.td.cleanup()

    @staticmethod
    def stops(ex, sym=None):
        return [o for o in ex.orders if "stopLossPrice" in o["params"] and (sym is None or o["symbol"] == sym)
                and "stop-" + o["params"]["clientOrderId"] not in ex.cancelled]

    def enter(self, ex):
        return botmod._single_leg_live_entry(ex, self.state, S, "long", 100, 100.0, 60.0, None, "vol_breakout")


class SingleLegTests(Base):
    def test_position_without_a_stop_is_closed_when_it_can_be(self):
        ex = FakeBinance(fail_stop=True, fail_close=True)
        self.assertIsNone(self.enter(ex))
        self.assertTrue(self.state["positions"][S]["unprotected"])
        ex.fail_close = False; ex.fetch_ticker = lambda s: {"last": 50.0}          # network back, price through the stop
        botmod._guard_stops(ex, self.state, {}, "t")
        self.assertEqual(ex.positions["SOL/USDT"], 0.0)

    def test_stop_is_retried_every_cycle_until_it_is_there(self):
        ex = FakeBinance(fail_stop=True, fail_close=True)
        self.enter(ex)
        ex.fail_stop = False
        botmod.reconcile_live(self.state, ex)
        stop, = self.stops(ex, S)
        self.assertEqual(stop["qty"], 2.0); self.assertTrue(stop["params"]["reduceOnly"])
        self.assertFalse(self.state["positions"][S]["unprotected"]); self.assertTrue(self.notified)

    def test_close_that_raised_but_filled_removes_its_stop(self):
        ex = FakeBinance(); self.assertIsNotNone(self.enter(ex))
        orig = ex.create_order
        def timeout_after_fill(sym, typ, side, qty, price, params):
            r = orig(sym, typ, side, qty, price, params)
            if params.get("reduceOnly") and "stopLossPrice" not in params: raise Exception("binanceusdm RequestTimeout")
            return r
        ex.create_order = timeout_after_fill
        self.assertTrue(botmod._single_leg_live_exit(ex, self.state, S, 110.0, "signal"))
        self.assertEqual(self.stops(ex, S), [])

    def test_refused_stop_is_not_retried_on_that_coin_today(self):
        ex = FakeBinance(fail_stop=True)
        for _ in range(3): self.assertIsNone(self.enter(ex))
        self.assertEqual([(o["side"], o["qty"]) for o in ex.orders if "stopLossPrice" not in o["params"]], [("buy", 2.0), ("sell", 2.0)])

    def test_refused_stops_on_three_coins_stop_entries(self):
        ex = FakeBinance(fail_stop=True)
        for sym in ("SOL/USDT:USDT", "ETH/USDT:USDT", "XRP/USDT:USDT"):
            botmod._single_leg_live_entry(ex, self.state, sym, "long", 100, 100.0, 60.0, None, "vol_breakout")
        self.assertTrue(botmod._ENTRY_BLOCK["reason"]); self.assertIn("stop_refused", self.state["recovery_required"])

    def test_stop_is_not_sized_on_part_of_the_fills(self):
        class Ex:
            def fetch_my_trades(self, sym, params=None):
                return [{"order": "1", "amount": 2.0, "price": 100.0, "fee": {"cost": 0.08, "currency": "USDT"}}]
        out = botmod._fill_from_trades(Ex(), S, {"id": "1", "filled": 5.0, "average": None})
        self.assertEqual(out["filled"], 5.0); self.assertIsNone(out.get("average"))   # unknown: fails closed downstream

    def test_crash_between_entry_and_stop_gets_a_stop_after_restart(self):
        ex = FakeBinance()
        botmod._expect_stop(self.state, S, "long", 60.0, "raqm-" + "c" * 27)           # saved before the order...
        ex.positions["SOL/USDT"] = 2.0                                                  # ...which filled; then the crash
        state = botmod.load_state(); botmod.reconcile_live(state, ex)
        stop, = self.stops(ex, S)
        self.assertEqual((stop["qty"], stop["params"]["stopLossPrice"]), (2.0, 60.0))
        self.assertIn(S, state["recovery_required"]); self.assertTrue(botmod._ENTRY_BLOCK["reason"])
        botmod.reconcile_live(state, ex)
        self.assertEqual(len(self.stops(ex, S)), 1)                                     # not placed twice

    def test_a_normal_entry_leaves_nothing_expected(self):
        ex = FakeBinance(); self.assertIsNotNone(self.enter(ex))
        self.assertNotIn(S, self.state.get("protect", {}))


class BasketTests(Base):
    def setUp(self):
        super().setUp()
        botmod.CONFIG["enabled_strategies"] = ["ratio_trend"]; botmod.RATIO["top"] = 2

    def run_ratio(self, ex, sig):
        with mock.patch.object(botmod, "ratio_members", return_value=[A, B]), mock.patch.object(botmod, "ratio_signal", return_value=sig):
            botmod.run_once_ratio(ex)

    def test_pair_with_a_leg_closed_on_the_exchange_is_closed_whole(self):
        ex = RatioFakeBinance(); self.run_ratio(ex, 1)
        st = botmod.load_state(); self.assertEqual(len(st["pairs"]), 1)
        ex.positions[A.split(":")[0]] = 0.0                                             # A's stop filled
        botmod.reconcile_live(st, ex); botmod.reconcile_live(st, ex)
        st = botmod.load_state(); st["ratio_day"] = None; botmod.save_state(st)
        n = len(ex.orders); self.run_ratio(ex, 1)                                       # signal unchanged
        st = botmod.load_state()
        closes = [o for o in ex.orders[n:] if o["params"].get("reduceOnly") and "stopLossPrice" not in o["params"]]
        self.assertEqual([o["symbol"] for o in closes], [B])                            # the lone leg was closed...
        self.assertEqual(set(st["positions"]), {A, B})                                  # ...and the pair opened afresh, both legs
        self.assertEqual(len(st["pairs"]), 1); self.assertFalse(st.get("recovery_required"))

    def test_failed_leg_with_an_unreadable_position_gets_a_stop_when_it_can(self):
        class Flaky(RatioFakeBinance):
            broken = False
            def create_order(s, sym, typ, side, qty, price, params):
                r = super().create_order(sym, typ, side, qty, price, params)
                if sym == B and "stopLossPrice" not in params and not params.get("reduceOnly"):
                    s.broken = True; raise Exception("binance 503")                     # filled, but an error came back
                return r
            def fetch_positions(s, syms=None):
                if s.broken: raise Exception("binance 503")
                return super().fetch_positions(syms)
            def fetch_order(s, oid, sym, params=None):
                if s.broken: raise Exception("503")
                return super().fetch_order(oid, sym, params)
        ex = Flaky(); self.run_ratio(ex, 1)
        self.assertEqual(self.stops(ex, B), []); self.assertTrue(self.notified)
        ex.broken = False                                                               # the exchange answers again
        st = botmod.load_state(); botmod.reconcile_live(st, ex)
        self.assertEqual(len(self.stops(ex, B)), 1)

    def test_retry_after_an_unfilled_basket_uses_new_order_ids(self):
        class Rejects(RatioFakeBinance):
            def create_order(s, sym, typ, side, qty, price, params):
                if sym == B and "stopLossPrice" not in params and not params.get("reduceOnly"): raise Exception("rejected")
                return super().create_order(sym, typ, side, qty, price, params)
        ex = Rejects(); self.run_ratio(ex, 1)
        first = {o["params"].get("clientOrderId") for o in ex.orders}
        st = botmod.load_state(); st["ratio_day"] = None; botmod.save_state(st)
        n = len(ex.orders); self.run_ratio(ex, 1)
        again = {o["params"].get("clientOrderId") for o in ex.orders[n:]}
        self.assertTrue(again); self.assertFalse(first & again)


if __name__ == "__main__":
    unittest.main()
