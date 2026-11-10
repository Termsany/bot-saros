"""The bot keeps to the dashboard's capital even when the account holds more (owner, 2026-11-03): with a capital plan
set, every risk percentage — per trade, aggregate, correlated, daily loss, drawdown — is of the capital (at most the
equity), not of the account's balance. $500 of capital on a $3,813 account: one $20.8 stop is 4.16%, not 0.55%; a
$113 loss in a day is 22.6%, not 3%. Without a plan nothing changes, and the basis is never above the equity."""
import tempfile, unittest
from pathlib import Path

from backend.app import risk_manager as rm

EQUITY, CAPITAL, LEG = 3813.0, 500.0, 20.8          # $26 margin × 2 × 40% stop


class RiskOnCapitalTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.path = Path(self.td.name) / "risk_state.json"

    def tearDown(self):
        self.td.cleanup()

    def limits(self, **kw):
        rm.update_limits(self.path, {"capital_usdt": CAPITAL, "capital_margin_override_usdt": 26, "capital_reserve_pct": 40,
                                     "risk_per_trade_pct": 4.5, "max_aggregate_risk_pct": 45, "max_correlated_risk_pct": 25,
                                     "max_daily_loss_pct": 20, "max_drawdown_pct": 45, **kw})

    def gate(self, symbol="AAA/USDT:USDT", equity=EQUITY):
        return rm.pre_trade_gate(self.path, strategy="momentum_ls", symbol=symbol, side="long", risk_usdt=LEG,
                                 notional_usdt=52, equity_usdt=equity, equity_observed_at=rm._now(), correlation_group="alts")

    def basket(self, n=10, equity=EQUITY):
        legs = [{"symbol": f"C{i}/USDT:USDT", "side": "long" if i < n // 2 else "short", "risk_usdt": LEG,
                 "notional_usdt": 52, "correlation_group": "alts"} for i in range(n)]
        return rm.pre_trade_gate_basket(self.path, strategy="momentum_ls", legs=legs, equity_usdt=equity, equity_observed_at=rm._now())

    def test_basis_is_the_capital_at_most_the_equity(self):
        self.assertEqual(rm.risk_basis({"capital_usdt": 500}, 3813), 500)
        self.assertEqual(rm.risk_basis({"capital_usdt": 500}, 400), 400)         # never above what the account holds
        self.assertEqual(rm.risk_basis({"capital_usdt": None}, 3813), 3813)      # no plan: the equity, as before
        self.assertEqual(rm.risk_basis({}, 3813), 3813)

    def test_per_trade_is_a_share_of_the_capital(self):
        self.limits(risk_per_trade_pct=4.0)                 # 4.16% of $500 > 4%, though only 0.55% of the balance
        ok, reason = self.gate()
        self.assertFalse(ok); self.assertIn("per-trade risk 4.160%", reason)
        self.limits(risk_per_trade_pct=4.5)
        self.assertTrue(self.gate()[0])

    def test_without_a_plan_the_equity_still_counts(self):
        rm.update_limits(self.path, {"risk_per_trade_pct": 1.0, "max_aggregate_risk_pct": 5, "max_correlated_risk_pct": 5})
        self.assertTrue(self.gate()[0])                      # 0.55% of $3,813

    def test_basket_aggregate_and_one_side_are_shares_of_the_capital(self):
        self.limits(max_aggregate_risk_pct=40)               # 10 × 4.16% = 41.6% of $500
        ok, reason = self.basket()
        self.assertFalse(ok); self.assertIn("aggregate", reason)
        self.limits(max_aggregate_risk_pct=45, max_correlated_risk_pct=20)    # 5 longs × 4.16% = 20.8% > 20%
        ok, reason = self.basket()
        self.assertFalse(ok); self.assertIn("correlated", reason)
        self.limits()
        self.assertTrue(self.basket()[0])

    def test_daily_loss_is_a_share_of_the_capital(self):
        self.limits()
        self.assertFalse(rm.update_equity_and_check_kill_switch(self.path, EQUITY, equity_observed_at=rm._now())[0])
        tripped, reason = rm.update_equity_and_check_kill_switch(self.path, EQUITY - 113, equity_observed_at=rm._now())
        self.assertTrue(tripped); self.assertIn("daily loss 22.60%", reason)      # $113 of $500, not 3% of $3,813

    def test_drawdown_is_a_share_of_the_capital(self):
        self.limits(max_daily_loss_pct=100)
        rm.update_equity_and_check_kill_switch(self.path, EQUITY, equity_observed_at=rm._now())
        self.assertFalse(rm.update_equity_and_check_kill_switch(self.path, EQUITY - 200, equity_observed_at=rm._now())[0])   # 40%
        tripped, reason = rm.update_equity_and_check_kill_switch(self.path, EQUITY - 230, equity_observed_at=rm._now())
        self.assertTrue(tripped); self.assertIn("drawdown 46.00%", reason)

    def test_same_loss_without_a_plan_does_not_trip(self):
        rm.update_limits(self.path, {"max_daily_loss_pct": 20, "max_drawdown_pct": 45})
        rm.update_equity_and_check_kill_switch(self.path, EQUITY, equity_observed_at=rm._now())
        self.assertFalse(rm.update_equity_and_check_kill_switch(self.path, EQUITY - 113, equity_observed_at=rm._now())[0])


if __name__ == "__main__":
    unittest.main()
