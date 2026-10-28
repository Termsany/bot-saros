"""ratio_trend (pairs trading: long one leg / short the other, same signal) real order-execution
path. run_once_ratio routes every pair's entry/exit through the durable multi-leg basket engine
(_phase2_live_basket) as ONE atomic two-leg intent — if either leg's order throws, the whole basket
is compensated so no half-open position or stuck risk-ledger row survives. Deterministic
FakeBinance only — no network."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bot as botmod
from backend.app import risk_manager as riskmgr_mod
from test_trend_live import FakeBinance

A, B = "AAA/USDT:USDT", "BBB/USDT:USDT"


class RatioFakeBinance(FakeBinance):
    def __init__(self, fail_symbol=None, prices=None, **kw):
        super().__init__(**kw)
        self.fail_symbol = fail_symbol
        self.prices = prices or {A: 100.0, B: 50.0}

    def fetch_ticker(self, sym):
        return {"last": self.prices.get(sym, 10.0)}

    def create_order(self, sym, typ, side, qty, price, params):
        if self.fail_symbol and sym == self.fail_symbol and "stopLossPrice" not in (params or {}):
            raise Exception("rejected")
        return super().create_order(sym, typ, side, qty, price, params)


class RatioTrendLiveTests(unittest.TestCase):
    def setUp(self):
        self._cfg = dict(botmod.CONFIG)
        self._ratio_cfg = dict(botmod.RATIO)
        self._env = os.environ.get("BINANCE_ENV")
        os.environ["BINANCE_ENV"] = "demo"
        botmod.RATIO["top"] = 2                           # only one pair (A, B) in this test's universe
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._paths = (botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH)
        botmod.STATE_PATH = Path(self.td.name) / "state.json"; botmod.LOG_PATH = Path(self.td.name) / "t.log"
        botmod.RISK_PATH = Path(self.td.name) / "risk_state.json"
        riskmgr_mod.save_risk_state(botmod.RISK_PATH, riskmgr_mod._default_state({
            "risk_per_trade_pct": 100.0, "max_aggregate_risk_pct": 100.0,
            "max_correlated_risk_pct": 100.0, "max_daily_loss_pct": 100.0, "max_drawdown_pct": 100.0,
        }))
        botmod.CONFIG.update({"paper_trading": False, "market": "future", "leverage": 2, "trade_amount_usdt": 100,
                              "enabled_strategies": ["ratio_trend"], "max_open_positions": 50, "public_dir": None})
        botmod._ENTRY_BLOCK["reason"] = ""
        self.state = botmod.load_state()

    def tearDown(self):
        botmod.CONFIG.clear(); botmod.CONFIG.update(self._cfg)
        botmod.RATIO.clear(); botmod.RATIO.update(self._ratio_cfg)
        if self._env is None: os.environ.pop("BINANCE_ENV", None)
        else: os.environ["BINANCE_ENV"] = self._env
        botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH = self._paths
        self.td.cleanup()

    def run_with(self, ex, sig=1):
        with mock.patch.object(botmod, "ratio_members", return_value=[A, B]), \
             mock.patch.object(botmod, "ratio_signal", return_value=sig):
            botmod.run_once_ratio(ex)

    def test_entry_opens_both_legs_atomically_and_registers_both_risks(self):
        ex = RatioFakeBinance()
        self.run_with(ex, sig=1)                           # long A / short B
        state = botmod.load_state()
        self.assertEqual(state["positions"][A]["side"], "long")
        self.assertEqual(state["positions"][B]["side"], "short")
        ledger = riskmgr_mod.load_risk_state(botmod.RISK_PATH)
        self.assertIn("ratio_trend:" + A, ledger["open_risk"])
        self.assertIn("ratio_trend:" + B, ledger["open_risk"])

    def test_second_leg_failure_unwinds_the_first_leg_no_stuck_risk(self):
        ex = RatioFakeBinance(fail_symbol=B)                # the short leg's order rejects
        self.run_with(ex, sig=1)
        state = botmod.load_state()
        self.assertNotIn(A, state["positions"])
        self.assertNotIn(B, state["positions"])
        self.assertEqual(state.get("pairs", {}), {})
        ledger = riskmgr_mod.load_risk_state(botmod.RISK_PATH)
        self.assertEqual([k for k in ledger["open_risk"] if k.startswith("ratio_trend:")], [])

    def test_signal_flip_closes_old_pair_and_opens_new_one_atomically(self):
        ex = RatioFakeBinance()
        self.run_with(ex, sig=1)                            # long A / short B
        state = botmod.load_state()
        state["recovery_required"] = {}
        state["ratio_day"] = None                           # force the daily check to run again
        botmod.save_state(state)
        self.run_with(ex, sig=-1)                           # flips to long B / short A
        final = botmod.load_state()
        self.assertEqual(final["positions"][A]["side"], "short")
        self.assertEqual(final["positions"][B]["side"], "long")
        ledger = riskmgr_mod.load_risk_state(botmod.RISK_PATH)
        self.assertIn("ratio_trend:" + A, ledger["open_risk"])
        self.assertIn("ratio_trend:" + B, ledger["open_risk"])


if __name__ == "__main__":
    unittest.main()
