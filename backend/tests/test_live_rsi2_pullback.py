"""Larry Connors RSI-2 pullback (long-only) real order-execution path. run_once_rsi2 calls
_single_leg_live_entry / _single_leg_live_exit with strategy="rsi2_pullback" exactly like this
test does directly, without mocking the 200-day trend-MA universe scan. Deterministic FakeBinance
only — no network."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bot as botmod
from backend.app import risk_manager as riskmgr_mod
from test_trend_live import FakeBinance


class Rsi2PullbackLiveTests(unittest.TestCase):
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
                              "enabled_strategies": ["rsi2_pullback"], "max_open_positions": 10})
        botmod._ENTRY_BLOCK["reason"] = ""
        self.state = botmod.load_state()

    def tearDown(self):
        botmod.CONFIG.clear(); botmod.CONFIG.update(self._cfg)
        if self._env is None: os.environ.pop("BINANCE_ENV", None)
        else: os.environ["BINANCE_ENV"] = self._env
        botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH = self._paths
        self.td.cleanup()

    def enter(self, ex, symbol="SOL/USDT:USDT", price=100.0, stop=60.0):
        # Exactly what run_once_rsi2 does on an RSI-2 < 5 pullback (bot.py ~line 3052).
        margin = botmod.position_size(price, ex) * int(botmod.CONFIG.get("leverage", 2))
        return botmod._single_leg_live_entry(ex, self.state, symbol, "long", margin, price, stop, None,
                                              "rsi2_pullback", {"rsi2": 3.1, "exit_at": "2099-01-01T00:00:00+00:00"})

    def test_entry_places_order_and_stop_and_registers_risk(self):
        ex = FakeBinance()
        pos = self.enter(ex)
        self.assertIsNotNone(pos)
        self.assertEqual(self.state["positions"]["SOL/USDT:USDT"]["strategy"], "rsi2_pullback")
        ledger = riskmgr_mod.load_risk_state(botmod.RISK_PATH)
        self.assertIn("rsi2_pullback:SOL/USDT:USDT", ledger["open_risk"])

    def test_exit_above_exit_ma_closes_exact_size_and_releases_risk(self):
        ex = FakeBinance()
        self.enter(ex)
        ok = botmod._single_leg_live_exit(ex, self.state, "SOL/USDT:USDT", 110.0, "قفل فوق متوسط 5 يوم")
        self.assertTrue(ok)
        self.assertNotIn("SOL/USDT:USDT", self.state["positions"])
        ledger = riskmgr_mod.load_risk_state(botmod.RISK_PATH)
        self.assertNotIn("rsi2_pullback:SOL/USDT:USDT", ledger["open_risk"])

    def test_kill_switch_blocks_entry_not_exit(self):
        ex = FakeBinance()
        self.enter(ex)
        riskmgr_mod.trip_kill_switch(botmod.RISK_PATH, "test")
        botmod.reconcile_live(self.state, ex)
        pos2 = botmod._single_leg_live_entry(ex, self.state, "ETH/USDT:USDT", "long", 100.0, 50.0, 30.0, None, "rsi2_pullback")
        self.assertIsNone(pos2)
        self.assertTrue(botmod._single_leg_live_exit(ex, self.state, "SOL/USDT:USDT", 110.0, "test exit"))

    def test_flat_exchange_does_not_block_first_entry(self):
        ex = FakeBinance()
        botmod.reconcile_live(self.state, ex)
        self.assertEqual(botmod._ENTRY_BLOCK["reason"], "")
        self.assertIsNotNone(self.enter(ex))


if __name__ == "__main__":
    unittest.main()
