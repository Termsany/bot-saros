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
            p = rm.capital_plan({**rm.DEFAULT_LIMITS, "capital_usdt": capital})
            self.assertEqual((p["margin"], p["max_open"]), (margin, max_open), capital)

    def test_capital_counts_at_most_what_the_account_holds(self):
        self.assertEqual(rm.capital_plan({**rm.DEFAULT_LIMITS, "capital_usdt": 5000}, 2000)["max_open"], 24)

    def test_no_capital_no_plan(self):
        self.assertIsNone(rm.capital_plan(rm.DEFAULT_LIMITS))


class GateTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.path = Path(self.td.name) / "r.json"
        rm.save_risk_state(self.path, rm._default_state({**LOOSE, "capital_usdt": 500}))   # 10 trades of $30
    def tearDown(self): self.td.cleanup()

    def gate(self, sym, strategy="s"):
        return rm.pre_trade_gate(self.path, strategy=strategy, symbol=sym, side="long", risk_usdt=1, notional_usdt=60,
                                 equity_usdt=1000, correlation_group="alts")

    def test_the_eleventh_trade_is_refused_until_the_capital_is_raised(self):
        for i in range(10): self.assertTrue(self.gate(f"C{i}/USDT")[0], i)
        ok, why = self.gate("C10/USDT")
        self.assertFalse(ok); self.assertIn("max open trades", why)
        rm.update_limits(self.path, {"capital_usdt": 1000})
        self.assertTrue(self.gate("C10/USDT")[0])

    def test_a_basket_enters_whole_or_not_at_all(self):
        for i in range(5): self.gate(f"C{i}/USDT")
        legs = [{"symbol": f"B{i}/USDT", "side": "long", "risk_usdt": 1, "notional_usdt": 60, "correlation_group": "alts"} for i in range(6)]
        ok, why = rm.pre_trade_gate_basket(self.path, strategy="momentum_ls", legs=legs, equity_usdt=1000)
        self.assertFalse(ok); self.assertIn("max open trades", why)
        self.assertEqual(len(rm.load_risk_state(self.path)["open_risk"]), 5)             # nothing of it reserved
        self.assertTrue(rm.pre_trade_gate_basket(self.path, strategy="momentum_ls", legs=legs[:5], equity_usdt=1000)[0])


class BotSizingTests(unittest.TestCase):
    def test_live_bots_size_with_the_plans_margin(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d, mock.patch.object(botmod, "RISK_PATH", Path(d) / "r.json"), \
             mock.patch.dict(botmod.CONFIG, {"paper_trading": False, "trade_amount_usdt": 100, "use_percent_risk": False}):
            rm.save_risk_state(botmod.RISK_PATH, rm._default_state({"capital_usdt": 5000}))
            self.assertEqual(botmod.position_size(100.0), 50.0)
            rm.update_limits(botmod.RISK_PATH, {"capital_usdt": None})
            self.assertEqual(botmod.position_size(100.0), 100.0)                          # no plan: the service's size
            with mock.patch.dict(botmod.CONFIG, {"paper_trading": True}):
                rm.update_limits(botmod.RISK_PATH, {"capital_usdt": 5000})
                self.assertEqual(botmod.position_size(100.0), 100.0)                      # paper never reads it


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
        self.assertEqual(r.json()["plan"]["max_open"], 20)
        demo = rm.load_risk_state(Path(self.tmp.name) / "demo" / "risk_state.json")["limits"]["capital_usdt"]
        live = rm.load_risk_state(Path(self.tmp.name) / "live" / "risk_state.json")["limits"]["capital_usdt"]
        self.assertEqual((demo, live), (1000, None))                                       # the demo plan never reaches real money
        self.assertEqual(self.c.post("/api/live/capital", headers=self.h("admin-token"), json={"env": "demo", "capital_usdt": 0}).json()["plan"], None)


if __name__ == "__main__":
    unittest.main()
