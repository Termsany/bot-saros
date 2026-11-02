"""The activation preflight must refuse a plan whose own arithmetic makes every entry fail the risk gate.

The old activation accepted anything: a record saying "live" could be paired with limits that refuse every trade, so
the account looked active and never opened one. These tests pin the arithmetic, not the exchange.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "backend"))

from backend.app.activation_preflight import evaluate
from backend.app import risk_manager as rm


def limits(**overrides):
    base = {**rm.DEFAULT_LIMITS, "capital_usdt": 100_000, "capital_margin_override_usdt": 30.0}
    base.update(overrides)
    return base


class ActivationPreflightTests(unittest.TestCase):
    def test_no_capital_plan_is_refused(self):
        result = evaluate(strategies=["trend_daily"], allocation={"trend_daily": 1.0},
                          limits=limits(capital_usdt=None, capital_margin_override_usdt=None))
        self.assertFalse(result["ok"])
        self.assertIn("no capital plan", " ".join(result["reasons"]).lower())

    def test_default_plan_cannot_fund_one_trade(self):
        # $1,000 capital at the built-in 1 % rule = $30 margin, x2, 40 % stop = $24 = 2.4 % of equity, while the
        # default per-trade limit is 0.25 %. Activation must show this instead of creating a dead record.
        result = evaluate(strategies=["trend_daily"], allocation={"trend_daily": 1.0},
                          limits=limits(capital_usdt=1_000, capital_margin_override_usdt=None),
                          equity_usdt=1_000)
        self.assertFalse(result["ok"])
        self.assertAlmostEqual(result["per_trade_risk_pct"], 2.4)
        self.assertIn("risk_per_trade_pct", " ".join(result["reasons"]))

    def test_equal_seven_way_split_is_too_small_for_one_trade(self):
        strategies = ["trend_daily", "listing_short", "momentum_ls", "ratio_trend",
                      "vol_breakout", "rsi2_pullback", "trend_breakout"]
        allocation = {s: 1 / 7 for s in strategies}
        # No manual margin override: the built-in rule puts 1 % of $100k into a trade, and x2 with the 40 % stop risks
        # 0.8 % of equity - far more than a 1/7 share (0.143 %) of the aggregate budget.
        result = evaluate(strategies=strategies, allocation=allocation,
                          limits=limits(risk_per_trade_pct=1.0, capital_margin_override_usdt=None),
                          equity_usdt=100_000)
        self.assertFalse(result["ok"])
        self.assertIn("allocation", " ".join(result["reasons"]))

    def test_a_funded_plan_passes(self):
        result = evaluate(strategies=["trend_daily"], allocation={"trend_daily": 0.25},
                          limits=limits(), equity_usdt=100_000)
        self.assertTrue(result["ok"], result["reasons"])
        self.assertAlmostEqual(result["per_trade_risk_pct"], 0.02)   # $24 of $100k, rounded by capital_plan
        self.assertEqual(result["plan"]["max_open"], 2000)

    def test_a_share_below_one_trade_is_refused(self):
        result = evaluate(strategies=["trend_daily"], allocation={"trend_daily": 0.001},
                          limits=limits(), equity_usdt=100_000)
        self.assertFalse(result["ok"])
        self.assertIn("trend_daily", " ".join(result["reasons"]))

    def test_missing_allocation_is_refused(self):
        result = evaluate(strategies=["trend_daily"], allocation={}, limits=limits(), equity_usdt=100_000)
        self.assertFalse(result["ok"])
        self.assertIn("allocation", " ".join(result["reasons"]))

    def test_no_open_slot_is_refused(self):
        result = evaluate(strategies=["trend_daily"], allocation={"trend_daily": 1.0},
                          limits=limits(capital_usdt=30), equity_usdt=30)
        self.assertFalse(result["ok"])
        self.assertIn("max_open", " ".join(result["reasons"]))

    def test_strategies_taking_turns_is_a_warning_not_a_refusal(self):
        result = evaluate(strategies=["trend_daily", "ratio_trend", "momentum_ls"],
                          allocation={s: 1 / 3 for s in ("trend_daily", "ratio_trend", "momentum_ls")},
                          limits=limits(capital_usdt=100, risk_per_trade_pct=100, max_aggregate_risk_pct=100,
                                        max_correlated_risk_pct=100), equity_usdt=100)
        self.assertTrue(result["ok"], result["reasons"])
        self.assertTrue(any("take turns" in w for w in result["warnings"]))

    def test_non_positive_limits_are_refused(self):
        result = evaluate(strategies=["trend_daily"], allocation={"trend_daily": 1.0},
                          limits=limits(risk_per_trade_pct=0), equity_usdt=100_000)
        self.assertFalse(result["ok"])
        self.assertIn("risk_per_trade_pct", " ".join(result["reasons"]))


if __name__ == "__main__":
    unittest.main()
