"""momentum_ls (concurrent long+short weekly rotation) real order-execution path. run_once_momentum
routes its weekly rebalance through the durable multi-leg basket engine (_phase2_live_basket):
every exit then every entry is one atomic basket, so a half-filled rebalance can never strand risk.
Deterministic FakeBinance only — no network."""
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

SYMS = [f"S{i}/USDT:USDT" for i in range(20)]


class MomentumFakeBinance(FakeBinance):
    def __init__(self, fail_symbol=None, **kw):
        super().__init__(**kw)
        self.fail_symbol = fail_symbol

    def fetch_ticker(self, sym):
        return {"last": 10.0}

    def create_order(self, sym, typ, side, qty, price, params):
        if self.fail_symbol and sym == self.fail_symbol and "stopLossPrice" not in (params or {}):
            raise Exception("rejected")
        return super().create_order(sym, typ, side, qty, price, params)


def ranked():
    # weakest first (as momentum_rank returns): picks = ranked[:5] shorts, ranked[-5:] longs.
    return [(sym, (i - 10) / 100.0) for i, sym in enumerate(SYMS)]


class MomentumLsLiveTests(unittest.TestCase):
    def setUp(self):
        self._cfg = dict(botmod.CONFIG)
        self._env = os.environ.get("BINANCE_ENV")
        os.environ["BINANCE_ENV"] = "demo"
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._paths = (botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH)
        botmod.STATE_PATH = Path(self.td.name) / "state.json"; botmod.LOG_PATH = Path(self.td.name) / "t.log"
        botmod.RISK_PATH = Path(self.td.name) / "risk_state.json"
        riskmgr_mod.save_risk_state(botmod.RISK_PATH, riskmgr_mod._default_state({
            "risk_per_trade_pct": 100.0, "max_aggregate_risk_pct": 100.0,
            "max_correlated_risk_pct": 100.0, "max_daily_loss_pct": 100.0, "max_drawdown_pct": 100.0,
        }))
        botmod.CONFIG.update({"paper_trading": False, "market": "future", "leverage": 2, "trade_amount_usdt": 100,
                              "enabled_strategies": ["momentum_ls"], "max_open_positions": 50, "public_dir": None})
        botmod._ENTRY_BLOCK["reason"] = ""
        self.state = botmod.load_state()

    def tearDown(self):
        botmod.CONFIG.clear(); botmod.CONFIG.update(self._cfg)
        if self._env is None: os.environ.pop("BINANCE_ENV", None)
        else: os.environ["BINANCE_ENV"] = self._env
        botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH = self._paths
        self.td.cleanup()

    def test_weekly_rebalance_opens_5_longs_and_5_shorts_atomically(self):
        ex = MomentumFakeBinance()
        with mock.patch.object(botmod, "momentum_rank", return_value=ranked()):
            botmod.run_once_momentum(ex)
        state = botmod.load_state()
        longs = [p for p in state["positions"].values() if p["side"] == "long"]
        shorts = [p for p in state["positions"].values() if p["side"] == "short"]
        self.assertEqual(len(longs), 5); self.assertEqual(len(shorts), 5)
        ledger = riskmgr_mod.load_risk_state(botmod.RISK_PATH)
        self.assertEqual(sum(1 for k in ledger["open_risk"] if k.startswith("momentum_ls:")), 10)

    def test_failed_leg_rolls_back_the_whole_basket_no_stuck_risk(self):
        ex = MomentumFakeBinance(fail_symbol=SYMS[-1])        # one of the picked longs fails to fill
        with mock.patch.object(botmod, "momentum_rank", return_value=ranked()):
            botmod.run_once_momentum(ex)
        state = botmod.load_state()
        self.assertEqual(state["positions"], {})
        ledger = riskmgr_mod.load_risk_state(botmod.RISK_PATH)
        self.assertEqual([k for k in ledger["open_risk"] if k.startswith("momentum_ls:")], [])

    def test_next_rebalance_exits_old_basket_and_opens_new_one(self):
        ex = MomentumFakeBinance()
        with mock.patch.object(botmod, "momentum_rank", return_value=ranked()):
            botmod.run_once_momentum(ex)
        state = botmod.load_state()
        state["mom_last"] = "2020-01-01T00:00:00+00:00"       # force the rebalance clock to fire again
        state["recovery_required"] = {}
        botmod.save_state(state)
        new_ranked = [(sym, (i - 10) / 100.0) for i, sym in enumerate(reversed(SYMS))]
        with mock.patch.object(botmod, "momentum_rank", return_value=new_ranked):
            botmod.run_once_momentum(ex)
        final = botmod.load_state()
        self.assertEqual(len(final["positions"]), 10)
        ledger = riskmgr_mod.load_risk_state(botmod.RISK_PATH)
        self.assertEqual(sum(1 for k in ledger["open_risk"] if k.startswith("momentum_ls:")), 10)


if __name__ == "__main__":
    unittest.main()
