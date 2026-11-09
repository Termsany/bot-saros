"""--ratio-net (owner, 2026-11-09; docs/ratio-trend-live-plan.md §1): the ratio trend as one position per coin, the sum
of its pairs, so a one-way account trades every pair instead of whichever coin-disjoint pairs came first. Live through
the basket engine (FakeBinance, no network) and on paper."""
import os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "backend")); sys.path.insert(0, str(Path(__file__).resolve().parent))

import bot as botmod
from backend.app import risk_manager as riskmgr_mod
from test_live_ratio_trend import RatioFakeBinance

A, B, C = "AAA/USDT:USDT", "BBB/USDT:USDT", "CCC/USDT:USDT"
PX = {A: 100.0, B: 50.0, C: 10.0}


def signals(table):
    """ratio_signal from {(a, b): sign}."""
    return lambda ex, a, b, cache: table.get((a, b), 0)


class NetTargetsTests(unittest.TestCase):
    def test_the_net_units_are_the_sum_of_each_coins_pairs(self):
        # A beats B and C, B beats C: A +2, B 0, C -2 — B drops out (no position)
        with mock.patch.object(botmod, "ratio_signal", signals({(A, B): 1, (A, C): 1, (B, C): 1})):
            self.assertEqual(botmod.ratio_targets(None, [A, B, C], {}), {A: 2, C: -2})
        with mock.patch.object(botmod, "ratio_signal", signals({(A, B): -1, (A, C): 1})):      # (B, C) no history: adds nothing
            self.assertEqual(botmod.ratio_targets(None, [A, B, C], {}), {B: 1, C: -1})

    def test_seven_ordered_coins_give_plus_six_to_minus_six(self):
        coins = [f"C{i}/USDT:USDT" for i in range(7)]
        with mock.patch.object(botmod, "ratio_signal", lambda ex, a, b, cache: 1 if coins.index(a) < coins.index(b) else -1):
            t = botmod.ratio_targets(None, coins, {})
        self.assertEqual([t.get(c, 0) for c in coins], [6, 4, 2, 0, -2, -4, -6])

    def test_the_plan_closes_and_reopens_a_change_leaves_a_stopped_coin_flat_and_retries_a_failed_open(self):
        prev = {A: {"units": 2, "opened": True}, B: {"units": -1, "opened": True}, C: {"units": 1, "opened": False}}
        held = {A: {}}                                   # B was stopped out, C never opened
        close, open_ = botmod.ratio_net_plan({A: 1, B: -1, C: 1}, prev, held)
        self.assertEqual((close, open_), ([A], [A, C]))  # A 2 -> 1; B unchanged and stopped: flat; C retried
        close, open_ = botmod.ratio_net_plan({B: -1, C: 1}, prev, held)
        self.assertEqual((close, open_), ([A], [C]))     # A's units go to 0: closed, not reopened
        close, open_ = botmod.ratio_net_plan({A: 2, B: 1, C: 1}, prev, held)
        self.assertEqual((close, open_), ([], [B, C]))   # B flips: opened again although it was flat


class NetLiveTests(unittest.TestCase):
    def setUp(self):
        self._cfg, self._ratio = dict(botmod.CONFIG), dict(botmod.RATIO)
        self._env = os.environ.get("BINANCE_ENV"); os.environ["BINANCE_ENV"] = "demo"
        botmod.RATIO.update({"top": 3, "net": True})
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._paths = (botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH)
        botmod.STATE_PATH = Path(self.td.name) / "state.json"; botmod.LOG_PATH = Path(self.td.name) / "t.log"
        botmod.RISK_PATH = Path(self.td.name) / "risk_state.json"
        riskmgr_mod.save_risk_state(botmod.RISK_PATH, riskmgr_mod._default_state({
            "risk_per_trade_pct": 100.0, "max_aggregate_risk_pct": 100.0, "max_correlated_risk_pct": 100.0,
            "max_daily_loss_pct": 100.0, "max_drawdown_pct": 100.0}))
        botmod.CONFIG.update({"paper_trading": False, "market": "future", "leverage": 2, "trade_amount_usdt": 10,
                              "enabled_strategies": ["ratio_trend"], "max_open_positions": 50, "public_dir": None})
        botmod._ENTRY_BLOCK["reason"] = ""

    def tearDown(self):
        botmod.CONFIG.clear(); botmod.CONFIG.update(self._cfg)
        botmod.RATIO.clear(); botmod.RATIO.update(self._ratio)
        if self._env is None: os.environ.pop("BINANCE_ENV", None)
        else: os.environ["BINANCE_ENV"] = self._env
        botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH = self._paths
        self.td.cleanup()

    def day(self, ex, table, new_day=True):
        if new_day:
            st = botmod.load_state(); st["ratio_day"] = None; st["recovery_required"] = {}; botmod.save_state(st)
        with mock.patch.object(botmod, "ratio_members", return_value=[A, B, C]), mock.patch.object(botmod, "ratio_signal", signals(table)):
            botmod.run_once_ratio(ex)
        return botmod.load_state()

    def test_one_position_per_coin_sized_by_its_units_with_its_stop_on_the_exchange(self):
        ex = RatioFakeBinance(prices=dict(PX))
        st = self.day(ex, {(A, B): 1, (A, C): 1, (B, C): 1})          # A +2, B 0, C -2
        self.assertEqual(set(st["positions"]), {A, C})
        self.assertEqual((st["positions"][A]["side"], st["positions"][C]["side"]), ("long", "short"))
        self.assertAlmostEqual(st["positions"][A]["qty"], 10 * 2 * 2 / 100)   # 2 units x $10 margin x2 at 100
        self.assertAlmostEqual(st["positions"][C]["qty"], 10 * 2 * 2 / 10)
        self.assertEqual(st["positions"][A]["units"], 2)
        self.assertTrue(ex.fetch_open_orders(A) and ex.fetch_open_orders(C))  # each coin's stop is on the exchange
        self.assertEqual(st["ratio_net"][A], {"units": 2, "opened": True})
        ledger = riskmgr_mod.load_risk_state(botmod.RISK_PATH)
        self.assertEqual(sorted(k for k in ledger["open_risk"] if k.startswith("ratio_trend:")), ["ratio_trend:" + A, "ratio_trend:" + C])

    def test_a_change_closes_and_reopens_only_the_coins_whose_units_moved(self):
        ex = RatioFakeBinance(prices=dict(PX))
        self.day(ex, {(A, B): 1, (A, C): 1, (B, C): 1})               # A +2, C -2
        held = botmod.load_state()["positions"]
        first, a_stop = held[C]["time"], held[A]["oco_ids"]["sl"]
        st = self.day(ex, {(A, B): -1, (A, C): 1, (B, C): 1})         # A 0, B +2, C -2
        self.assertEqual(set(st["positions"]), {B, C})
        self.assertEqual(st["positions"][B]["units"], 2)
        self.assertEqual(st["positions"][C]["time"], first)          # C unchanged: not touched
        self.assertIn("stop-" + a_stop, ex.cancelled)                 # A's stop went with it (the fake lists every coin's)

    def test_a_coin_stopped_out_stays_flat_until_its_units_change(self):
        ex = RatioFakeBinance(prices=dict(PX))
        table = {(A, B): 1, (A, C): 1, (B, C): 1}
        self.day(ex, table)
        # as if its stop fired and reconcile_live booked it: off the books, its risk released, the exchange flat
        st = botmod.load_state(); pos = st["positions"].pop(C); botmod.save_state(st)
        botmod._release_position_risk(C, pos); ex.positions[C.split(":")[0]] = 0.0
        with mock.patch.object(botmod, "reconcile_live", lambda state, ex: None):
            st = self.day(ex, table)
        self.assertNotIn(C, st["positions"])
        with mock.patch.object(botmod, "reconcile_live", lambda state, ex: None):
            st = self.day(ex, {(A, B): 1, (A, C): 1, (B, C): -1})     # B: -1 -1 = -2 (opens short), C: -1 +1 = 0
        self.assertNotIn(C, st["positions"]); self.assertEqual(st["positions"][B]["side"], "short")
        with mock.patch.object(botmod, "reconcile_live", lambda state, ex: None):
            st = self.day(ex, {(A, B): 1, (A, C): 1, (B, C): 1})      # C back to -2: its units changed, so it opens again
        self.assertEqual(st["positions"][C]["side"], "short")

    def test_a_refused_entry_opens_nothing_and_is_tried_again(self):
        ex = RatioFakeBinance(prices=dict(PX), fail_symbol=C)
        st = self.day(ex, {(A, B): 1, (A, C): 1, (B, C): 1})
        self.assertEqual(st["positions"], {})                         # the basket is all or nothing
        self.assertIsNone(st.get("ratio_day"))                        # the day isn't marked done
        self.assertEqual(st["ratio_net"], {})                         # nor the target taken
        self.assertIn("ratio_trend:ratio-net-entry", st.get("basket_backoff") or {})   # the engine waits before trying again
        ex.fail_symbol = None
        st["basket_backoff"] = {}; botmod.save_state(st)               # ... the wait over
        st = self.day(ex, {(A, B): 1, (A, C): 1, (B, C): 1}, new_day=False)
        self.assertEqual(set(st["positions"]), {A, C})

    def test_a_paired_book_is_never_mixed_with_the_netted_one(self):
        st = botmod.load_state(); st["pairs"] = {f"{A}|{B}": {"sign": 1, "legs": []}}; botmod.save_state(st)
        ex = RatioFakeBinance(prices=dict(PX))
        st = self.day(ex, {(A, B): 1, (A, C): 1, (B, C): 1}, new_day=False)
        self.assertEqual(st["positions"], {})


class NetPaperTests(NetLiveTests):
    def setUp(self):
        super().setUp(); botmod.CONFIG["paper_trading"] = True

    test_one_position_per_coin_sized_by_its_units_with_its_stop_on_the_exchange = None
    test_a_refused_entry_opens_nothing_and_is_tried_again = None
    test_a_change_closes_and_reopens_only_the_coins_whose_units_moved = None
    test_a_coin_stopped_out_stays_flat_until_its_units_change = None

    def test_paper_opens_the_same_book_and_books_a_change(self):
        ex = RatioFakeBinance(prices=dict(PX))
        st = self.day(ex, {(A, B): 1, (A, C): 1, (B, C): 1})
        self.assertEqual({c: p["units"] for c, p in st["positions"].items()}, {A: 2, C: -2})
        with mock.patch.object(ex, "fetch_funding_rate_history", return_value=[], create=True):
            st = self.day(ex, {(A, B): -1, (A, C): 1, (B, C): 1})
        self.assertEqual(set(st["positions"]), {B, C})
        self.assertEqual(st["stats"]["trades"], 1)                    # A closed and booked
        self.assertEqual(st["history"][-1]["reason"], "الوزن اتغير")

    def test_a_paper_stop_closes_the_coin(self):
        ex = RatioFakeBinance(prices=dict(PX))
        self.day(ex, {(A, B): 1, (A, C): 1, (B, C): 1})
        ex.prices[C] = 14.5                                           # the short's 40% stop at 14
        with mock.patch.object(ex, "fetch_funding_rate_history", return_value=[], create=True):
            st = self.day(ex, {(A, B): 1, (A, C): 1, (B, C): 1}, new_day=False)
        self.assertNotIn(C, st["positions"])


class NetFlagTests(unittest.TestCase):
    def test_the_flag_is_for_the_ratio_trend_only_and_off_by_default(self):
        src = (ROOT / "bot.py").read_text(encoding="utf-8")
        self.assertIn('p.add_argument("--ratio-net"', src)
        self.assertIn('if args.strategy != "ratio_trend": p.error("--ratio-net: ratio_trend only")', src)
        import bots.ratio_trend as rt
        self.assertFalse(rt.RATIO["net"])


if __name__ == "__main__":
    unittest.main()
