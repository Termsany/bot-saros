"""The owner's capital plan (2026-10-30): the capital decides the margin per trade and the most trades open at once,
every strategy together; entries beyond that count are refused until the capital is raised."""
import os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "backend")); sys.path.insert(0, str(Path(__file__).resolve().parent))
import bot as botmod
from backend.app import risk_manager as rm
from test_security import ApiAuthTests

LOOSE = {"risk_per_trade_pct": 100.0, "max_aggregate_risk_pct": 100.0, "max_correlated_risk_pct": 100.0,
         "max_daily_loss_pct": 100.0, "max_drawdown_pct": 100.0}


class PlanTests(unittest.TestCase):
    def test_the_agreed_examples(self):
        for capital, margin, max_open in ((500, 30, 10), (1000, 30, 20), (3000, 30, 60), (5000, 50, 60)):
            p = rm.capital_plan({**rm.DEFAULT_LIMITS, "capital_usdt": capital, "risk_per_trade_pct": 5.0})
            self.assertEqual((p["margin"], p["max_open"]), (margin, max_open), capital)

    def test_capital_counts_at_most_what_the_account_holds(self):
        # size and count both: 5,000 typed on a 2,000 account trades like 2,000 ($30 x 40), never $50 a trade
        p = rm.capital_plan({**rm.DEFAULT_LIMITS, "capital_usdt": 5000, "risk_per_trade_pct": 5.0}, 2000)
        self.assertEqual((p["margin"], p["max_open"]), (30, 40))
        typo = rm.capital_plan({**rm.DEFAULT_LIMITS, "capital_usdt": 50000, "risk_per_trade_pct": 5.0}, 5000)        # a zero too many
        self.assertEqual((typo["margin"], typo["max_open"]), (50, 60))

    def test_manual_margin_and_its_risk(self):
        p = rm.capital_plan({**rm.DEFAULT_LIMITS, "capital_usdt": 5000, "capital_margin_override_usdt": 300}, 5000)
        self.assertTrue(p["manual"]); self.assertEqual((p["margin"], p["max_open"]), (300, 10))
        self.assertEqual((p["loss_per_trade"], p["loss_per_trade_pct"], p["level"]), (240, 4.8, "high"))   # 40% stop at x2
        self.assertEqual(rm.capital_plan({**rm.DEFAULT_LIMITS, "capital_usdt": 5000, "capital_margin_override_usdt": 30}, 5000)["level"], "low")

    def test_which_limit_binds_first(self):
        lim = {**rm.DEFAULT_LIMITS, "capital_usdt": 5000, "risk_per_trade_pct": 1.0, "max_aggregate_risk_pct": 40.0}
        self.assertEqual(rm.plan_vs_limits(lim, rm.capital_plan(lim, 5000))["binding"], "aggregate_risk")       # 49 < 60
        big = {**lim, "capital_margin_override_usdt": 100}
        self.assertEqual(rm.plan_vs_limits(big, rm.capital_plan(big, 5000))["binding"], "risk_per_trade")       # 1.6% > 1%

    def test_a_setting_that_is_not_a_number_refuses(self):
        with self.assertRaises(ValueError): rm.capital_plan({**rm.DEFAULT_LIMITS, "capital_usdt": float("nan")})

    def test_small_capital_still_trades_within_the_per_trade_limit(self):
        # $400 with a 1% limit: $30 a trade would lose 6% at the stop and every entry was refused
        lim = {**rm.DEFAULT_LIMITS, "capital_usdt": 400, "risk_per_trade_pct": 1.0}
        p = rm.capital_plan(lim, 5000)
        self.assertEqual((p["margin"], p["max_open"]), (4.95, 48))
        self.assertLessEqual(p["loss_per_trade_pct"], 1.0)
        self.assertEqual(rm.plan_vs_limits(lim, p)["binding"], "aggregate_risk")      # 40 trades by the 40% limit
        big = rm.capital_plan({**lim, "capital_usdt": 5000}, 5000)
        self.assertEqual(big["margin"], 50)                                              # the 1% rule where it fits
        self.assertEqual(rm.capital_plan({**lim, "capital_usdt": 100}, 5000)["margin"], 3.0)   # never below Binance's minimum

    def test_no_capital_no_plan(self):
        self.assertIsNone(rm.capital_plan(rm.DEFAULT_LIMITS))


class GateTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.path = Path(self.td.name) / "r.json"
        rm.save_risk_state(self.path, rm._default_state({**LOOSE, "capital_usdt": 500}))   # 10 trades of $30
    def tearDown(self): self.td.cleanup()

    def gate(self, sym, strategy="s"):
        return rm.pre_trade_gate(self.path, strategy=strategy, symbol=sym, side="long", risk_usdt=1, notional_usdt=60,
                                 equity_usdt=1000, correlation_group="alts", equity_observed_at=rm._now())

    def test_the_eleventh_trade_is_refused_until_the_capital_is_raised(self):
        for i in range(10): self.assertTrue(self.gate(f"C{i}/USDT")[0], i)
        ok, why = self.gate("C10/USDT")
        self.assertFalse(ok); self.assertIn("max open trades", why)
        rm.update_limits(self.path, {"capital_usdt": 1000})
        self.assertTrue(self.gate("C10/USDT")[0])

    def test_a_basket_enters_whole_or_not_at_all(self):
        for i in range(5): self.gate(f"C{i}/USDT")
        legs = [{"symbol": f"B{i}/USDT", "side": "long", "risk_usdt": 1, "notional_usdt": 60, "correlation_group": "alts"} for i in range(6)]
        ok, why = rm.pre_trade_gate_basket(self.path, strategy="momentum_ls", legs=legs, equity_usdt=1000, equity_observed_at=rm._now())
        self.assertFalse(ok); self.assertIn("max open trades", why)
        self.assertEqual(len(rm.load_risk_state(self.path)["open_risk"]), 5)             # nothing of it reserved
        self.assertTrue(rm.pre_trade_gate_basket(self.path, strategy="momentum_ls", legs=legs[:5], equity_usdt=1000, equity_observed_at=rm._now())[0])


class AllocationWithPlanTests(unittest.TestCase):
    """Owner (2026-10-30): with a capital plan, the live allocation does not split the risk budget per strategy."""
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.path = Path(self.td.name) / "r.json"
        rm.save_risk_state(self.path, rm._default_state({**LOOSE, "max_aggregate_risk_pct": 40.0}))
    def tearDown(self): self.td.cleanup()

    def gate(self, sym, share):
        return rm.pre_trade_gate(self.path, strategy="s", symbol=sym, side="long", risk_usdt=20, notional_usdt=60,
                                 equity_usdt=1000, equity_observed_at=rm._now(), strategy_risk_share=share)

    def test_a_seventh_share_binds_without_a_plan_but_not_with_one(self):
        self.assertTrue(self.gate("A/USDT", 1 / 7)[0]); self.assertTrue(self.gate("B/USDT", 1 / 7)[0])
        self.assertIn("allocation", self.gate("C/USDT", 1 / 7)[1])                     # 6% > 40% / 7
        rm.update_limits(self.path, {"capital_usdt": 1000})
        self.assertTrue(self.gate("C/USDT", 1 / 7)[0])
        self.assertTrue(rm.pre_trade_gate_basket(self.path, strategy="s", legs=[{"symbol": "D/USDT", "side": "long", "risk_usdt": 20,
                        "notional_usdt": 60}], equity_usdt=1000, equity_observed_at=rm._now(), strategy_risk_share=1 / 7)[0])

    def test_an_invalid_share_still_refuses_with_a_plan(self):
        rm.update_limits(self.path, {"capital_usdt": 1000})
        self.assertFalse(self.gate("A/USDT", 0.0)[0])


class BotSizingTests(unittest.TestCase):
    def test_live_bots_size_with_the_plans_margin(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d, mock.patch.object(botmod, "RISK_PATH", Path(d) / "r.json"), \
             mock.patch.dict(botmod.CONFIG, {"paper_trading": False, "trade_amount_usdt": 100, "use_percent_risk": False}):
            rm.save_risk_state(botmod.RISK_PATH, rm._default_state({"capital_usdt": 5000, "risk_per_trade_pct": 5.0}))
            self.assertEqual(botmod.position_size(100.0), 50.0)
            rm.update_limits(botmod.RISK_PATH, {"capital_usdt": None})
            self.assertEqual(botmod.position_size(100.0), 100.0)                          # no plan: the service's size
            with mock.patch.dict(botmod.CONFIG, {"paper_trading": True}):
                rm.update_limits(botmod.RISK_PATH, {"capital_usdt": 5000})
                self.assertEqual(botmod.position_size(100.0), 100.0)                      # paper never reads it


class FairShareGateTests(unittest.TestCase):
    """Owner (2026-10-31): with a capital plan, each strategy switched on gets an even share of the account's count."""
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.path = Path(self.td.name) / "r.json"
        rm.save_risk_state(self.path, rm._default_state({**LOOSE, "capital_usdt": 500}))   # 10 trades of $30
    def tearDown(self): self.td.cleanup()

    def gate(self, sym, strategy, sharing):
        return rm.pre_trade_gate(self.path, strategy=strategy, symbol=sym, side="long", risk_usdt=1, notional_usdt=60,
                                 equity_usdt=1000, equity_observed_at=rm._now(), strategies_sharing=sharing)

    def basket(self, n, sharing, prefix="B"):
        legs = [{"symbol": f"{prefix}{i}/USDT", "side": "long", "risk_usdt": 1, "notional_usdt": 60} for i in range(n)]
        return rm.pre_trade_gate_basket(self.path, strategy="momentum_ls", legs=legs, equity_usdt=1000,
                                        equity_observed_at=rm._now(), strategies_sharing=sharing)

    def test_the_slots(self):
        plan = rm.capital_plan({**rm.DEFAULT_LIMITS, "capital_usdt": 500, "risk_per_trade_pct": 5.0})   # 10 trades
        self.assertEqual([rm.strategy_slots(plan, n) for n in (1, 2, 3, 7, 20)], [10, 5, 3, 1, 1])
        self.assertIsNone(rm.strategy_slots(plan, None)); self.assertIsNone(rm.strategy_slots(None, 3))

    def test_one_strategy_on_takes_the_whole_account(self):
        for i in range(10): self.assertTrue(self.gate(f"C{i}/USDT", "a", 1)[0], i)
        self.assertIn("max open trades", self.gate("C10/USDT", "a", 1)[1])

    def test_the_busiest_cant_take_the_others_slots(self):
        for i in range(3): self.assertTrue(self.gate(f"A{i}/USDT", "a", 3)[0], i)
        ok, why = self.gate("A3/USDT", "a", 3)
        self.assertFalse(ok); self.assertIn("share", why)
        for i in range(3): self.assertTrue(self.gate(f"B{i}/USDT", "b", 3)[0], i)       # b still has its 3

    def test_a_basket_counts_every_leg_against_the_share(self):
        ok, why = self.basket(4, 3)                                                       # 4 legs > 10 // 3
        self.assertFalse(ok); self.assertIn("share", why)
        self.assertEqual(rm.load_risk_state(self.path)["open_risk"], {})                 # nothing of it reserved
        self.assertTrue(self.basket(4, 2)[0])                                             # 4 legs <= 10 // 2

    def test_no_plan_no_share(self):
        rm.update_limits(self.path, {"capital_usdt": None})
        for i in range(5): self.assertTrue(self.gate(f"C{i}/USDT", "a", 7)[0], i)


class StrategyCapTests(unittest.TestCase):
    """The strategy's own cap (as tested) always holds; with a plan, so does its even share of the account's count."""
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); d = Path(self.td.name)
        self.patches = [mock.patch.object(botmod, "RISK_PATH", d / "r.json"), mock.patch.object(botmod, "ACTIVATION_PATH", d / "a.sqlite3"),
                        mock.patch.dict(botmod.CONFIG, {"paper_trading": False}), mock.patch.dict(os.environ, {"BINANCE_ENV": "demo"})]
        for p in self.patches: p.start()
        rm.save_risk_state(botmod.RISK_PATH, rm._default_state({"capital_usdt": 500, "risk_per_trade_pct": 5.0}))   # 10 trades
    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        self.td.cleanup()

    def full(self, n, cap=10):
        return botmod._strategy_full({"positions": {f"C{i}/USDT:USDT": {} for i in range(n)}}, cap)

    def test_one_strategy_on_gets_the_account_up_to_its_own_cap(self):
        botmod.live_activation.set_demo_strategies(botmod.ACTIVATION_PATH, strategies=["trend_daily"], set_by="t")
        self.assertFalse(self.full(9)); self.assertTrue(self.full(10)); self.assertTrue(self.full(4, cap=4))

    def test_three_on_share_the_account(self):
        botmod.live_activation.set_demo_strategies(botmod.ACTIVATION_PATH, strategies=["trend_daily", "rsi2_pullback", "momentum_ls"], set_by="t")
        self.assertFalse(self.full(2)); self.assertTrue(self.full(3))                    # 10 // 3

    def test_nothing_chosen_on_demo_is_all_seven(self):
        self.assertEqual(botmod._strategies_sharing(), 7); self.assertTrue(self.full(1))   # 10 // 7

    def test_an_unreadable_choice_is_the_smallest_share(self):
        with mock.patch.object(botmod.live_activation, "demo_strategies", side_effect=OSError("locked")):
            self.assertEqual(botmod._strategies_sharing(), 7)

    def test_no_plan_or_paper_keeps_the_tested_cap(self):
        rm.update_limits(botmod.RISK_PATH, {"capital_usdt": None})
        self.assertFalse(self.full(9)); self.assertTrue(self.full(10))
        rm.update_limits(botmod.RISK_PATH, {"capital_usdt": 500})
        with mock.patch.dict(botmod.CONFIG, {"paper_trading": True}):
            self.assertIsNone(botmod._strategies_sharing()); self.assertFalse(self.full(9))


class SafetyTests(unittest.TestCase):
    def test_unreadable_plan_refuses_instead_of_the_default_size(self):
        with mock.patch.dict(botmod.CONFIG, {"paper_trading": False, "trade_amount_usdt": 100}),              mock.patch.object(botmod.riskmgr, "load_risk_state", side_effect=OSError("database is locked")):
            with self.assertRaises(OSError): botmod.position_size(100.0)

    def test_order_below_the_exchange_minimum_is_not_sent(self):
        ex = mock.Mock(); ex.market.return_value = {"limits": {"cost": {"min": 50.0}}}
        with mock.patch.dict(botmod.CONFIG, {"leverage": 2}):
            self.assertFalse(botmod._meets_min_order(ex, "BTC/USDT:USDT", 20))
            self.assertTrue(botmod._meets_min_order(ex, "BTC/USDT:USDT", 30))


class ApiTests(ApiAuthTests):
    def setUp(self):
        super().setUp()
        import app.main as m; self.m = m
        self.p = [mock.patch.object(m, "BOT_DIR", Path(self.tmp.name)),
                  mock.patch.dict(os.environ, {"RAQM_RISK_DIR": str(Path(self.tmp.name) / "live"), "RAQM_RISK_DIR_DEMO": str(Path(self.tmp.name) / "demo")})]
        for p in self.p: p.start()
    def tearDown(self):
        for p in self.p: p.stop()
        super().tearDown()

    def test_capital_per_account_admin_only(self):
        self.assertEqual(self.c.post("/api/live/capital", headers=self.h("user-token"), json={"env": "demo", "capital_usdt": 1000}).status_code, 403)
        r = self.c.post("/api/live/capital", headers=self.h("admin-token"), json={"env": "demo", "capital_usdt": 1000})
        self.assertEqual(r.json()["plan"]["margin"], 3.09)                                  # 0.25% default limit: one stop costs <= 0.25%
        demo = rm.load_risk_state(Path(self.tmp.name) / "demo" / "risk_state.json")["limits"]["capital_usdt"]
        live = rm.load_risk_state(Path(self.tmp.name) / "live" / "risk_state.json")["limits"]["capital_usdt"]
        self.assertEqual((demo, live), (1000, None))                                       # the demo plan never reaches real money
        self.assertEqual(self.c.post("/api/live/capital", headers=self.h("admin-token"), json={"env": "demo", "capital_usdt": 0}).json()["plan"], None)


if __name__ == "__main__":
    unittest.main()
