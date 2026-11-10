"""Root's ceilings over the dashboard's risk limits (RAQM_CAP_*_PCT, from the root-owned allow-live.env).

The limits live in the ledger the API writes: a stolen admin session or the API itself could set 100% risk per trade.
These tests set exactly that in the ledger and check the ceilings still bind — in the single-trade gate, the basket
gate, the capital plan's sizing and the daily-loss / drawdown kill switch — that a bad ceiling refuses, and that the
ledger keeps the dashboard's own values."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend.app import risk_manager as rm

CAPS = {"RAQM_CAP_RISK_PER_TRADE_PCT": "2", "RAQM_CAP_AGGREGATE_RISK_PCT": "10",
        "RAQM_CAP_CORRELATED_RISK_PCT": "10", "RAQM_CAP_DAILY_LOSS_PCT": "5", "RAQM_CAP_DRAWDOWN_PCT": "15"}
WIDE_OPEN = {"risk_per_trade_pct": 100, "max_aggregate_risk_pct": 100, "max_correlated_risk_pct": 100,
             "max_daily_loss_pct": 100, "max_drawdown_pct": 100}


def _no_caps():
    return {k: v for k, v in os.environ.items() if not k.startswith("RAQM_CAP_")}


class HardCapsTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.path = Path(self.td.name) / "risk_state.json"
        rm.update_limits(self.path, dict(WIDE_OPEN))            # what a hostile dashboard request would set

    def tearDown(self):
        self.td.cleanup()

    def gate(self, risk, symbol="BTC/USDT:USDT"):
        return rm.pre_trade_gate(self.path, strategy="momentum_ls", symbol=symbol, side="long", risk_usdt=risk,
                                 notional_usdt=risk * 3, equity_usdt=1000, equity_observed_at=rm._now())

    def basket(self, risks):
        legs = [{"symbol": f"C{i}/USDT:USDT", "side": "long", "risk_usdt": r, "notional_usdt": r * 3}
                for i, r in enumerate(risks)]
        return rm.pre_trade_gate_basket(self.path, strategy="momentum_ls", legs=legs, equity_usdt=1000,
                                        equity_observed_at=rm._now())

    def test_without_ceilings_the_dashboard_limits_apply_as_before(self):
        with mock.patch.dict(os.environ, _no_caps(), clear=True):
            self.assertTrue(self.gate(500)[0])                  # 50%: allowed by the ledger alone

    def test_per_trade_ceiling_binds_over_the_ledger(self):
        with mock.patch.dict(os.environ, {**_no_caps(), **CAPS}, clear=True):
            ok, reason = self.gate(50)                          # 5% > ceiling 2%
            self.assertFalse(ok); self.assertIn("per-trade risk", reason)
            self.assertTrue(self.gate(15)[0])                   # 1.5% fits

    def test_aggregate_ceiling_binds_across_trades(self):
        with mock.patch.dict(os.environ, {**_no_caps(), **CAPS}, clear=True):
            for i in range(5):
                self.assertTrue(self.gate(19, symbol=f"C{i}/USDT:USDT")[0])   # 5 × 1.9% = 9.5%
            ok, reason = self.gate(19, symbol="C9/USDT:USDT")                 # 11.4% > ceiling 10%
            self.assertFalse(ok); self.assertIn("aggregate", reason)

    def test_basket_ceilings_bind_per_leg_and_in_total(self):
        with mock.patch.dict(os.environ, {**_no_caps(), **CAPS}, clear=True):
            self.assertFalse(self.basket([50])[0])              # one leg 5% > 2%
            ok, reason = self.basket([15] * 10)                 # 10 × 1.5% = 15% > 10%
            self.assertFalse(ok); self.assertIn("aggregate", reason)
            self.assertTrue(self.basket([9] * 10)[0])           # 9% fits

    def test_ledger_keeps_the_dashboard_values(self):
        with mock.patch.dict(os.environ, {**_no_caps(), **CAPS}, clear=True):
            self.gate(15)
            rm.update_equity_and_check_kill_switch(self.path, 1000, equity_observed_at=rm._now())
        self.assertEqual(rm.load_risk_state(self.path)["limits"]["risk_per_trade_pct"], 100)

    def test_daily_loss_ceiling_trips_the_kill_switch(self):
        with mock.patch.dict(os.environ, {**_no_caps(), **CAPS}, clear=True):
            self.assertFalse(rm.update_equity_and_check_kill_switch(self.path, 1000, equity_observed_at=rm._now())[0])
            tripped, reason = rm.update_equity_and_check_kill_switch(self.path, 940, equity_observed_at=rm._now())
        self.assertTrue(tripped); self.assertIn("daily loss", reason)   # 6% >= ceiling 5%, ledger said 100%

    def test_invalid_ceiling_refuses_entries_and_trips_the_kill_switch(self):
        for bad in ("abc", "0", "-1", "nan", "150"):
            with self.subTest(bad=bad), mock.patch.dict(os.environ, {**_no_caps(), **CAPS, "RAQM_CAP_RISK_PER_TRADE_PCT": bad}, clear=True):
                ok, reason = self.gate(1)
                self.assertFalse(ok); self.assertIn("RAQM_CAP_RISK_PER_TRADE_PCT", reason)
        with mock.patch.dict(os.environ, {**_no_caps(), **CAPS, "RAQM_CAP_DRAWDOWN_PCT": "abc"}, clear=True):
            tripped, reason = rm.update_equity_and_check_kill_switch(self.path, 1000, equity_observed_at=rm._now())
        self.assertTrue(tripped); self.assertIn("ceiling invalid", reason)

    def test_capital_plan_is_sized_under_the_ceiling(self):
        # margin 50% of capital by the rule: only the risk per trade can bring it down
        limits = {**rm.DEFAULT_LIMITS, **WIDE_OPEN, "capital_usdt": 1500, "capital_margin_pct": 50}
        with mock.patch.dict(os.environ, {**_no_caps(), **CAPS}, clear=True):
            capped = rm.capital_plan(rm.capped_limits(limits), 1500)
        loose = rm.capital_plan(limits, 1500)
        self.assertLessEqual(capped["loss_per_trade_pct"], 2.0 + 1e-9)
        self.assertGreater(loose["margin"], capped["margin"])

    def test_required_ceilings_must_all_be_set(self):
        with mock.patch.dict(os.environ, _no_caps(), clear=True):
            with self.assertRaises(ValueError):
                rm.hard_caps(required=True)
        partial = {k: v for k, v in CAPS.items() if k != "RAQM_CAP_DRAWDOWN_PCT"}
        with mock.patch.dict(os.environ, {**_no_caps(), **partial}, clear=True):
            with self.assertRaises(ValueError):
                rm.hard_caps(required=True)
        with mock.patch.dict(os.environ, {**_no_caps(), **CAPS}, clear=True):
            self.assertEqual(rm.hard_caps(required=True)["risk_per_trade_pct"], 2.0)


class LiveStartupRequiresCeilingsTests(unittest.TestCase):
    """The real-money unit refuses to start without root's ceilings; it is set up in deploy/vps/README.md."""
    def test_setup_files_name_every_ceiling(self):
        root = Path(__file__).resolve().parent.parent.parent
        readme = (root / "deploy" / "vps" / "README.md").read_text(encoding="utf-8")
        bot = (root / "bot.py").read_text(encoding="utf-8")
        for var in rm.HARD_CAP_ENV.values():
            self.assertIn(var, readme)
        self.assertIn("hard_caps(required=True)", bot)


if __name__ == "__main__":
    unittest.main()
