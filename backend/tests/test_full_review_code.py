"""Full review (2026-10-30, at e7a7bf9), order path: one failure used to lock a coin or a basket for good, silently.

Single-leg: a close that changed nothing locked the coin (exits never retried); the review mark outlived a verified
close (every entry on every coin blocked). Baskets: an entry basket with a leg that always fails was sent again
every poll; a basket left in recovery stayed there after the account was flat; one failed exit leg stopped the
rest of a rebalance and the book stayed half-closed."""
import os, sqlite3, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "backend")); sys.path.insert(0, str(Path(__file__).resolve().parent))
import bot as botmod
from backend.app import risk_manager as rm
from test_trend_live import FakeBinance
from test_live_momentum_ls import MomentumFakeBinance, SYMS, ranked

S = "SOL/USDT:USDT"


class Base(unittest.TestCase):
    strategy = "vol_breakout"
    def setUp(self):
        self._cfg = dict(botmod.CONFIG); self._env = os.environ.get("BINANCE_ENV"); os.environ["BINANCE_ENV"] = "demo"
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._saved = (botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH, botmod.ENTRY_RECHECK_S, botmod.FILL_LOOKUP_WAITS)
        botmod.STATE_PATH = Path(self.td.name) / "s.json"; botmod.LOG_PATH = Path(self.td.name) / "l.log"
        botmod.RISK_PATH = Path(self.td.name) / "r.json"; botmod.ENTRY_RECHECK_S = 0; botmod.FILL_LOOKUP_WAITS = (0.0,)
        rm.save_risk_state(botmod.RISK_PATH, rm._default_state({"risk_per_trade_pct": 100.0, "max_aggregate_risk_pct": 100.0,
            "max_correlated_risk_pct": 100.0, "max_daily_loss_pct": 100.0, "max_drawdown_pct": 100.0}))
        botmod.CONFIG.update({"paper_trading": False, "market": "future", "leverage": 2, "trade_amount_usdt": 100,
                              "max_open_positions": 50, "use_percent_risk": False, "public_dir": None,
                              "enabled_strategies": [self.strategy]})
        botmod._ENTRY_BLOCK["reason"] = ""
        self.notified = []
        for target, value in (("notify", self.notified.append), ("_live_activation_gate", lambda s: (True, ""))):
            p = mock.patch.object(botmod, target, value); p.start(); self.addCleanup(p.stop)
        self.state = botmod.load_state()

    def tearDown(self):
        botmod.CONFIG.clear(); botmod.CONFIG.update(self._cfg)
        if self._env is None: os.environ.pop("BINANCE_ENV", None)
        else: os.environ["BINANCE_ENV"] = self._env
        (botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH, botmod.ENTRY_RECHECK_S, botmod.FILL_LOOKUP_WAITS) = self._saved
        botmod._ENTRY_BLOCK["reason"] = ""
        self.td.cleanup()


class SingleLegTests(Base):
    def test_exit_that_changed_nothing_is_retried_not_locked(self):
        ex = FakeBinance(); self.assertIsNotNone(botmod._single_leg_live_entry(ex, self.state, S, "long", 100, 100.0, 60.0, None, "vol_breakout"))
        real = ex.fetch_positions
        ex.fetch_positions = mock.Mock(side_effect=Exception("RequestTimeout"))
        self.assertFalse(botmod._single_leg_live_exit(ex, self.state, S, 110.0, "day open"))
        self.assertNotIn(S, self.state.get("recovery_required", {})); self.assertIn(S, self.state["exit_due"])
        self.assertTrue(self.notified)
        ex.fetch_positions = real; ex.fetch_ticker = lambda sym: {"last": 110.0}
        botmod._retry_due_exits(ex, self.state, "t")                         # the next cycle
        self.assertNotIn(S, self.state["positions"]); self.assertEqual(ex.positions["SOL/USDT"], 0.0)
        self.assertNotIn(S, self.state.get("exit_due", {}))

    def test_verified_close_clears_the_review_mark(self):
        ex = FakeBinance(fail_stop=True, fail_close=True)
        botmod._single_leg_live_entry(ex, self.state, S, "long", 100, 100.0, 60.0, None, "vol_breakout")
        self.assertIn(S, self.state["recovery_required"])
        ex.fail_close = False
        self.assertTrue(botmod._single_leg_live_exit(ex, self.state, S, 110.0, "signal"))
        self.assertNotIn(S, self.state["recovery_required"])
        ex2 = FakeBinance()
        botmod._ENTRY_BLOCK["reason"] = ""
        self.assertIsNotNone(botmod._single_leg_live_entry(ex2, self.state, "ETH/USDT:USDT", "long", 100, 100.0, 60.0, None, "rsi2_pullback"))

    def test_summed_fee_fails_closed(self):
        self.assertIsNone(botmod._summed_fee([{"fee": {"cost": 1.0, "currency": "USDT"}}, {"fee": {"cost": 0.001, "currency": "BNB"}}])["cost"])
        self.assertIsNone(botmod._summed_fee([{"fee": {"cost": 1.0, "currency": "USDT"}}, {}])["cost"])
        self.assertEqual(botmod._summed_fee([{"fee": {"cost": 1.0, "currency": "USDT"}}, {"fee": {"cost": 2.0, "currency": "USDT"}}]),
                         {"cost": 3.0, "currency": "USDT"})


class BasketTests(Base):
    strategy = "momentum_ls"

    def run_momentum(self, ex, ranking=None):
        with mock.patch.object(botmod, "momentum_rank", return_value=ranking or ranked()):
            botmod.run_once_momentum(ex)

    @staticmethod
    def entries(ex): return [o for o in ex.orders if "stopLossPrice" not in o["params"] and not o["params"].get("reduceOnly")]

    def test_basket_that_keeps_failing_is_not_sent_every_poll(self):
        ex = MomentumFakeBinance(fail_symbol=SYMS[-1])
        self.run_momentum(ex); first = len(self.entries(ex))
        for _ in range(2): self.run_momentum(ex)
        self.assertEqual(len(self.entries(ex)), first); self.assertTrue(self.notified)
        st = botmod.load_state(); self.assertEqual(st["basket_backoff"]["momentum_ls:momentum-rebalance-entry"]["count"], 1)

    def test_third_unwind_in_a_row_needs_a_person(self):
        ex = MomentumFakeBinance(fail_symbol=SYMS[-1])
        for _ in range(3):
            self.run_momentum(ex)
            st = botmod.load_state(); st.get("basket_backoff", {}).get("momentum_ls:momentum-rebalance-entry", {})["until"] = "2000-01-01T00:00:00+00:00"
            botmod.save_state(st)
        self.assertIn("basket:momentum_ls:momentum-rebalance-entry", botmod.load_state()["recovery_required"])

    def test_basket_left_in_recovery_clears_itself_once_flat(self):
        class Flaky(MomentumFakeBinance):
            n = 0
            def cancel_order(self, oid, sym, *a):
                Flaky.n += 1
                if Flaky.n == 1: raise Exception("timeout")              # one cancel fails while the basket is unwound
                return super().cancel_order(oid, sym, *a)
        ex = Flaky(fail_symbol=SYMS[-1])
        self.run_momentum(ex)
        self.assertTrue(botmod.load_state()["recovery_required"])
        self.run_momentum(ex)                                                # next cycle: settled before any early return
        st = botmod.load_state()
        self.assertFalse([k for k in st.get("recovery_required", {}) if not k.startswith("basket:")])
        self.assertEqual(rm.load_risk_state(botmod.RISK_PATH)["open_risk"], {})
        self.assertEqual(ex.fetch_open_orders(None), [])

    def test_one_failed_exit_leg_does_not_leave_the_rebalance_half_closed(self):
        class Flaky(MomentumFakeBinance):
            arm = False; n = 0
            def fetch_positions(self, syms=None):
                if self.arm and syms and syms[0].startswith("S16/"):
                    Flaky.n += 1
                    if Flaky.n == 1: raise Exception("timeout")
                return super().fetch_positions(syms)
        ex = Flaky(); self.run_momentum(ex)
        st = botmod.load_state(); st["mom_last"] = "2020-01-01T00:00:00+00:00"; botmod.save_state(st)
        ex.arm = True
        self.run_momentum(ex, [(sym, (i - 10) / 100.0) for i, sym in enumerate(reversed(SYMS))])
        open_now = sorted(k for k, v in ex.positions.items() if v)
        self.assertEqual(open_now, ["S16/USDT"])                            # every other leg was still closed
        self.assertFalse(botmod.load_state().get("recovery_required"))     # S16 changed nothing: retried, not locked
        self.assertTrue(self.notified)


if __name__ == "__main__":
    unittest.main()
