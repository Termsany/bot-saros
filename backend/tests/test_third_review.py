"""Fixes from the third pre-production review (2026-10-29): reproduces each finding on the pre-fix
code before the matching fix commit.

_protect_pending: a confirmed-placed stop was dropped from the book without ever being cancelled when the
exchange went flat (left live on the exchange forever); it acted on a single flat reading instead of the two
consecutive readings the sibling reconciliation loop requires; an incomplete order-book read was treated the
same as "confirmed absent", risking a duplicate stop. _phase2_live_basket: a retried basket read its cycle
token before engine.reconcile() had a chance to clear a stale one, so a crash-recovered retry reused the
previous attempt's order numbers."""
import os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "backend")); sys.path.insert(0, str(Path(__file__).resolve().parent))
import bot as botmod
from backend.app import risk_manager as rm
from test_trend_live import FakeBinance

S = "SOL/USDT:USDT"
A, B = "A/USDT:USDT", "B/USDT:USDT"
LOOSE = {"risk_per_trade_pct": 100.0, "max_aggregate_risk_pct": 100.0, "max_correlated_risk_pct": 100.0,
         "max_daily_loss_pct": 100.0, "max_drawdown_pct": 100.0}


class Base(unittest.TestCase):
    def setUp(self):
        self._cfg = dict(botmod.CONFIG); self._env = os.environ.get("BINANCE_ENV"); os.environ["BINANCE_ENV"] = "demo"
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._saved = (botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH, botmod.ENTRY_RECHECK_S, botmod.FILL_LOOKUP_WAITS)
        botmod.STATE_PATH = Path(self.td.name) / "s.json"; botmod.LOG_PATH = Path(self.td.name) / "l.log"
        botmod.RISK_PATH = Path(self.td.name) / "r.json"; botmod.ENTRY_RECHECK_S = 0; botmod.FILL_LOOKUP_WAITS = (0.0,)
        rm.save_risk_state(botmod.RISK_PATH, rm._default_state(LOOSE))
        botmod.CONFIG.update({"paper_trading": False, "market": "future", "leverage": 2, "trade_amount_usdt": 100,
                              "enabled_strategies": ["momentum_ls"], "max_open_positions": 50, "use_percent_risk": False, "public_dir": None})
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

    @staticmethod
    def stops(ex, sym=None):
        return [o for o in ex.orders if "stopLossPrice" in o["params"] and (sym is None or o["symbol"] == sym)]

    @staticmethod
    def stop_id(ex, sym):
        stops = [o for o in ex.orders if "stopLossPrice" in o["params"] and o["symbol"] == sym]
        return "stop-" + stops[-1]["params"]["clientOrderId"] if stops else None


class ProtectPendingFlatHandlingTests(Base):
    """Findings 1 (HIGH, stale stop left behind) and 4 (MEDIUM, no two-reading flat requirement)."""

    def seed_protected(self, ex):
        cid = "raqm-" + "p" * 27
        botmod._expect_stop(self.state, S, "long", 60.0, cid)
        ex.positions["SOL"] = 2.0
        botmod._protect_pending(ex, self.state, {"SOL/USDT": 2.0})       # places the real stop, protected=True
        self.assertTrue(self.state["protect"][S]["protected"])
        return cid

    def test_single_flat_reading_does_not_drop_the_book_entry_or_touch_the_stop(self):
        """Finding 4: one flat reading must not be believed (exchange reads can lag)."""
        ex = FakeBinance(); self.seed_protected(ex)
        sid = self.stop_id(ex, S)
        botmod._protect_pending(ex, self.state, {})                      # exchange now reads flat, once
        self.assertIn(S, self.state["protect"])                          # book entry must survive a single flat reading
        self.assertNotIn(sid, ex.cancelled)                              # ...and the stop must not be touched yet

    def test_second_consecutive_flat_reading_cancels_the_stop_before_dropping_the_entry(self):
        """Finding 1: the stop this function placed must be cancelled, not just forgotten about."""
        ex = FakeBinance(); self.seed_protected(ex)
        sid = self.stop_id(ex, S)
        botmod._protect_pending(ex, self.state, {})                      # 1st flat reading
        botmod._protect_pending(ex, self.state, {})                      # 2nd consecutive flat reading
        self.assertIn(sid, ex.cancelled)                                 # the stop is actually gone from the exchange...
        self.assertNotIn(S, self.state["protect"])                       # ...only then is the book entry dropped

    def test_uncancellable_stop_keeps_the_book_entry_for_retry(self):
        """Cancellation failure (unconfirmed) must not be silently treated as success."""
        class StuckStop(FakeBinance):
            stuck = False
            def fetch_open_orders(self, sym, *a):
                if self.stuck and a and isinstance(a[-1], dict): raise Exception("trigger view timeout")  # complete=False
                return super().fetch_open_orders(sym, *a)
        ex = StuckStop(); self.seed_protected(ex)
        ex.stuck = True                                                  # now the trigger/stop views stop answering
        botmod._protect_pending(ex, self.state, {})
        botmod._protect_pending(ex, self.state, {})
        self.assertIn(S, self.state["protect"])                          # cancel unconfirmed: keep retrying, don't drop

    def test_a_truthy_reading_resets_the_flat_streak(self):
        ex = FakeBinance(); self.seed_protected(ex)
        sid = self.stop_id(ex, S)
        botmod._protect_pending(ex, self.state, {})                      # 1 flat reading
        botmod._protect_pending(ex, self.state, {"SOL/USDT": 2.0})       # back to open: resets the streak
        botmod._protect_pending(ex, self.state, {})                      # only 1 consecutive flat reading again
        self.assertIn(S, self.state["protect"]); self.assertNotIn(sid, ex.cancelled)


class ProtectPendingIncompleteReadTests(Base):
    """Small item: an incomplete read of the order book must not be treated as 'confirmed absent'."""

    def test_incomplete_read_skips_placing_a_new_stop_this_cycle(self):
        class AllViewsFail(FakeBinance):
            def fetch_open_orders(self, *a, **kw):
                raise Exception("timeout")                                # every view errors: complete=False
        ex = AllViewsFail(); ex.positions["SOL"] = 2.0
        cid = "raqm-" + "q" * 27
        botmod._expect_stop(self.state, S, "long", 60.0, cid)
        botmod._protect_pending(ex, self.state, {"SOL/USDT": 2.0})
        self.assertEqual(ex.orders, [])                                  # no duplicate-risk order was ever placed
        self.assertFalse(self.state["protect"][S].get("protected"))      # left pending for a retry next cycle


class StaleCycleTokenTests(Base):
    """Finding 5 (MEDIUM): a retried basket must not reuse a stale cycle_token once reconcile() clears it."""

    def legs(self, *syms):
        return [botmod._phase2_leg(s, "long" if i == 0 else "short", 50, 10.0, 6.0 if i == 0 else 14.0, None, "momentum_ls", i)
                for i, s in enumerate(syms)]

    def test_stale_token_cleared_by_reconcile_is_not_reused_for_the_new_attempt(self):
        C, D = "C/USDT:USDT", "D/USDT:USDT"

        class Blind(FakeBinance):
            """Leg B's own position read fails, so THIS attempt ends in recovery_required (not filled/
            compensated) -- isolating the cycle_token bug from the terminal-status cleanup that would
            otherwise pop the book entry regardless of which token was used."""
            def create_order(self, sym, typ, side, qty, price, params):
                r = super().create_order(sym, typ, side, qty, price, params)
                if sym == B and "stopLossPrice" not in params and not params.get("reduceOnly"):
                    return {"id": "e2", "clientOrderId": params.get("clientOrderId"), "filled": None, "status": "NEW"}
                return r
            def fetch_my_trades(self, sym, since=None, limit=20, params=None): raise Exception("timeout")
            def fetch_positions(self, syms=None):
                if syms and B in syms: raise Exception("timeout")
                return super().fetch_positions(syms)

        ex = Blind()
        engine = botmod._phase2_engine(self.state)
        stale_legs = self.legs(C, D)                                     # unrelated symbols: resolves cleanly to flat
        for n, leg in enumerate(stale_legs): leg["client_order_id"] = f"raqm-crash{n:022d}"
        stale_token = "stale-token-aaaaaaaaaaaaaaaaaaaaaaaa"
        engine._write_execution("exec-crash", "momentum_ls", "t-entry", "started", {"legs": stale_legs, "cycle_token": stale_token})
        cycle_key = "momentum_ls:t-entry"
        self.state.setdefault("_execution_cycles", {})[cycle_key] = stale_token
        botmod.save_state(self.state)
        # C/D are flat on the exchange -> reconcile resolves that STALE pending row as "compensated" and
        # clears the stale cycle_token from state["_execution_cycles"] as part of the SAME call below —
        # while THIS call's own A/B attempt (unrelated symbols) ends in recovery_required.
        res = botmod._phase2_live_basket(ex, self.state, "momentum_ls", "t-entry", self.legs(A, B))
        self.assertEqual(res["status"], "recovery_required")
        cycles = self.state.get("_execution_cycles", {})
        self.assertIn(cycle_key, cycles)                                 # a fresh token must be minted for this attempt
        self.assertNotEqual(cycles[cycle_key], stale_token)               # ...never the stale one that was just cleared


class WriteJsonAtomicPermissionsTests(unittest.TestCase):
    """Finding 2(i) HIGH: the API (raqmapi) and the bot (raqm/raqmlive) share these dashboard/status
    JSON files via group membership on a setgid dir — but tempfile.mkstemp() defaults to 0600 (no group
    bits at all), so even with correct group membership the API still couldn't read them."""

    def test_write_json_atomic_chmods_the_file_to_group_read_write(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            path = Path(d) / "status.json"
            with mock.patch("os.chmod") as chmod_mock:
                botmod._write_json_atomic(path, {"a": 1})
            # same convention risk_manager.py / live_activation.py already use for their sqlite files
            self.assertTrue(any(c.args[1] == 0o660 for c in chmod_mock.call_args_list),
                             f"expected a chmod(..., 0o660) call, got {chmod_mock.call_args_list}")
        self.assertTrue(path.exists())   # the mocked chmod must not have broken the normal write/replace


if __name__ == "__main__":
    unittest.main()
