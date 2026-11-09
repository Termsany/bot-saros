"""Money moved into or out of the account is not a gain or a loss (owner, 2026-11-07). On 2026-11-05 a $200 withdrawal
from the real sub-account read as a 51% drawdown and tripped the kill switch; a deposit raised the high-water mark so
that taking it back out would trip it again. The bot now reads the account's transfers (Binance income TRANSFER)
before its balance, and the risk ledger applies each one once to the high-water mark and the day's start."""
import os, sys, tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "backend"))
from backend.app import risk_manager as rm
import bot as botmod

LIMITS = {"risk_per_trade_pct": 4.5, "max_aggregate_risk_pct": 45, "max_correlated_risk_pct": 25,
          "max_daily_loss_pct": 20, "max_drawdown_pct": 45, "capital_usdt": 500, "capital_margin_override_usdt": 26}
T0 = 1_762_182_600_000           # 2026-11-03 15:10 UTC, the first deposit (in ms)
MIN = 60_000


def now():
    return datetime.now(timezone.utc).isoformat()


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.p = Path(self.td.name) / "risk_state.json"
        rm.save_risk_state(self.p, rm._default_state(LIMITS))
        self.saved = {k: os.environ.pop(k, None) for k in rm.HARD_CAP_ENV.values()}
    def tearDown(self):
        for k, v in self.saved.items():
            if v is not None: os.environ[k] = v
        self.td.cleanup()

    def eq(self, equity, transfers):
        return rm.update_equity_and_check_kill_switch(self.p, equity, equity_observed_at=now(), transfers=transfers)

    def test_the_nov_5_withdrawal_no_longer_trips_the_kill_switch(self):
        rows = [(T0, 500.0)]
        self.assertEqual(self.eq(581.86, rows), (False, None))                       # high-water mark 581.86
        rows.append((T0 + 2 * 24 * 60 * MIN, -200.0))                                # 2026-11-05 15:09: −$200
        # the real figures: $324.77 after it, i.e. a $57.09 trading drawdown from the high: 15% of $381.86, not 51%
        self.assertEqual(self.eq(324.77, rows), (False, None))
        st = rm.load_risk_state(self.p)
        self.assertAlmostEqual(st["equity_high_water_mark"], 381.86, places=2)
        self.assertFalse(st["kill_switch"]["tripped"])
        self.assertEqual(st["transfers_applied"][-1]["usdt"], -200.0)

    def test_without_the_transfers_the_old_behaviour_stays(self):
        self.eq(581.86, None)
        tripped, why = self.eq(324.77, None)
        self.assertTrue(tripped); self.assertIn("drawdown", why)

    def test_a_deposit_is_no_new_high_so_taking_it_out_trips_nothing(self):
        rows = [(T0, 500.0)]
        self.eq(489.0, rows)
        rows.append((T0 + 4 * 24 * 60 * MIN, 343.29))                                # 2026-11-07 07:46: +$343.29
        self.eq(832.29, rows)
        self.assertAlmostEqual(rm.load_risk_state(self.p)["equity_high_water_mark"], 832.29, places=2)
        rows.append((T0 + 4 * 24 * 60 * MIN + 30 * MIN, -343.29))                    # and back out
        self.assertEqual(self.eq(489.0, rows), (False, None))
        self.assertAlmostEqual(rm.load_risk_state(self.p)["equity_high_water_mark"], 489.0, places=2)

    def test_each_transfer_counts_once(self):
        rows = [(T0, 500.0)]
        self.eq(500.0, rows)
        rows.append((T0 + MIN, -100.0))
        for _ in range(3):
            self.eq(400.0, rows)
        st = rm.load_risk_state(self.p)
        self.assertAlmostEqual(st["equity_high_water_mark"], 400.0)
        self.assertEqual(len(st["transfers_applied"]), 1)

    def test_a_withdrawal_is_no_daily_loss(self):
        rows = [(T0, 500.0)]
        self.eq(500.0, rows)
        today = int(datetime.now(timezone.utc).timestamp() * 1000)
        rows.append((today, -150.0))                                                  # 30%: past the 20% daily limit
        self.assertEqual(self.eq(350.0, rows), (False, None))
        self.assertAlmostEqual(rm.load_risk_state(self.p)["daily"]["start_equity"], 350.0)

    def test_a_real_loss_still_trips(self):
        rows = [(T0, 500.0)]
        self.eq(500.0, rows)
        rows.append((T0 + MIN, 50.0))                                                 # a deposit hides no loss
        tripped, why = self.eq(550.0 - 240.0, rows)
        self.assertTrue(tripped); self.assertIn("drawdown", why)

    def test_odd_rows_are_dropped_and_nothing_is_applied_while_tripped(self):
        self.eq(500.0, [(T0, 500.0), ("x", 1), (T0 + 1, float("nan")), ()])
        self.assertEqual(rm.load_risk_state(self.p)["transfers_through"], T0)
        rm.trip_kill_switch(self.p, "manual")
        self.eq(300.0, [(T0, 500.0), (T0 + MIN, -200.0)])
        self.assertEqual(rm.load_risk_state(self.p)["transfers_through"], T0)          # untouched while tripped
        rm.reset_kill_switch(self.p, operator="test")
        self.assertEqual(self.eq(300.0, [(T0, 500.0), (T0 + MIN, -200.0)]), (False, None))


class BotReadsTransfersFirst(unittest.TestCase):
    def setUp(self):
        self._cfg = dict(botmod.CONFIG); botmod.CONFIG["paper_trading"] = False
    def tearDown(self):
        botmod.CONFIG.clear(); botmod.CONFIG.update(self._cfg); botmod._TRANSFERS["rows"] = None

    def test_the_transfers_are_read_before_the_balance(self):
        calls = []
        ex = mock.Mock()
        ex.fapiPrivateGetIncome.side_effect = lambda p: calls.append(("income", p["incomeType"])) or [
            {"time": str(T0), "income": "500.0", "asset": "USDT"}, {"time": str(T0 + 1), "income": "1", "asset": "BNB"}]
        ex.fetch_balance.side_effect = lambda: calls.append(("balance",)) or {"USDT": {"total": 500.0}}
        equity, at = botmod._equity_now(ex)
        self.assertEqual(calls, [("income", "TRANSFER"), ("balance",)])
        self.assertEqual((equity, botmod._TRANSFERS["rows"]), (500.0, [(T0, 500.0)]))

    def test_unreadable_or_paper_is_none(self):
        ex = mock.Mock(); ex.fapiPrivateGetIncome.side_effect = Exception("418")
        ex.fetch_balance.return_value = {"USDT": {"total": 500.0}}
        botmod._equity_now(ex); self.assertIsNone(botmod._TRANSFERS["rows"])
        botmod.CONFIG["paper_trading"] = True
        self.assertIsNone(botmod._transfers_recent(mock.Mock()))
        botmod.CONFIG["paper_trading"] = False
        self.assertIsNone(botmod._transfers_recent(object()))                         # an exchange with no income endpoint


if __name__ == "__main__":
    unittest.main()
