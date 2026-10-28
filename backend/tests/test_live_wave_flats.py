"""Wave Flats real order-execution path (bot.py try_enter_wave), mirroring test_trend_live.py's
coverage but for the wave-pattern SL/TP1/TP2 structure. Deterministic FakeBinance only — no network."""
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


def wave_signal(ts=1, dir=1, stop=90.0, tgt1=110.0, tgt2=120.0, two=True, be=100.0, kind="Flat"):
    return {"ts": ts, "dir": dir, "stop": stop, "tgt1": tgt1, "tgt2": tgt2, "two": two, "be": be, "kind": kind}


class WaveFlatsLiveTests(unittest.TestCase):
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
        botmod.CONFIG.update({"paper_trading": False, "market": "future", "leverage": 5, "trade_amount_usdt": 100,
                              "enabled_strategies": ["wave_flats"], "max_open_positions": 10, "use_percent_risk": False})
        botmod._ENTRY_BLOCK["reason"] = ""
        self.state = botmod.load_state()

    def tearDown(self):
        botmod.CONFIG.clear(); botmod.CONFIG.update(self._cfg)
        if self._env is None: os.environ.pop("BINANCE_ENV", None)
        else: os.environ["BINANCE_ENV"] = self._env
        botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH = self._paths
        self.td.cleanup()

    def test_entry_places_order_and_stop_and_registers_risk(self):
        ex = FakeBinance()
        analysis = {"price": 100.0, "wave": wave_signal()}
        botmod.try_enter_wave("SOL/USDT:USDT", analysis, self.state, ex)
        buy = ex.orders[0]
        self.assertEqual(buy["side"], "buy")
        self.assertTrue(all(o["params"].get("reduceOnly") for o in ex.orders[1:]))
        pos = self.state["positions"]["SOL/USDT:USDT"]
        self.assertEqual(pos["strategy"], "wave_flats")
        self.assertEqual(pos["wave"]["kind"], "Flat")
        ledger = riskmgr_mod.load_risk_state(botmod.RISK_PATH)
        self.assertIn("wave_flats:SOL/USDT:USDT", ledger["open_risk"])

    def test_sl_hit_closes_exact_size_and_releases_risk(self):
        ex = FakeBinance()
        analysis = {"price": 100.0, "wave": wave_signal()}
        botmod.try_enter_wave("SOL/USDT:USDT", analysis, self.state, ex)
        botmod.check_sl_tp(self.state, {"SOL/USDT:USDT": 85.0}, ex)
        self.assertNotIn("SOL/USDT:USDT", self.state["positions"])
        ledger = riskmgr_mod.load_risk_state(botmod.RISK_PATH)
        self.assertNotIn("wave_flats:SOL/USDT:USDT", ledger["open_risk"])
        self.assertEqual(self.state["history"][-1]["type"], "live")

    def test_kill_switch_blocks_new_entry_but_not_an_existing_exit(self):
        ex = FakeBinance()
        analysis = {"price": 100.0, "wave": wave_signal()}
        botmod.try_enter_wave("SOL/USDT:USDT", analysis, self.state, ex)
        riskmgr_mod.trip_kill_switch(botmod.RISK_PATH, "pre-tripped for this test")
        botmod.reconcile_live(self.state, ex)
        self.assertIn("kill switch", botmod._ENTRY_BLOCK["reason"])
        n = len(ex.orders)
        botmod.try_enter_wave("ETH/USDT:USDT", {"price": 50.0, "wave": wave_signal(ts=2)}, self.state, ex)
        self.assertEqual(len(ex.orders), n)                                    # no new entry
        botmod.check_sl_tp(self.state, {"SOL/USDT:USDT": 85.0}, ex)            # exit still runs
        self.assertNotIn("SOL/USDT:USDT", self.state["positions"])

    def test_clean_flat_account_does_not_block_the_first_entry(self):
        ex = FakeBinance()
        botmod.reconcile_live(self.state, ex)
        self.assertEqual(botmod._ENTRY_BLOCK["reason"], "")
        analysis = {"price": 100.0, "wave": wave_signal()}
        botmod.try_enter_wave("SOL/USDT:USDT", analysis, self.state, ex)
        self.assertIn("SOL/USDT:USDT", self.state["positions"])


if __name__ == "__main__":
    unittest.main()
