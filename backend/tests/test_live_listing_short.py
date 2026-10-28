"""listing_short (short-only new-listing fade, max_open cap) real order-execution path.
run_once_listing already routes every live leg through the durable multi-leg basket engine
(_phase2_live_basket) — same atomic entry/exit machinery proven for momentum_ls/ratio_trend.
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


class ListingFakeBinance(FakeBinance):
    def __init__(self, prices=None, **kw):
        super().__init__(**kw)
        self.prices = prices or {}

    def fetch_ticker(self, sym):
        return {"last": self.prices.get(sym, 100.0)}


class ListingShortLiveTests(unittest.TestCase):
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
                              "enabled_strategies": ["listing_short"], "max_open_positions": 10, "public_dir": None})
        botmod._ENTRY_BLOCK["reason"] = ""
        self.state = botmod.load_state()

    def tearDown(self):
        botmod.CONFIG.clear(); botmod.CONFIG.update(self._cfg)
        if self._env is None: os.environ.pop("BINANCE_ENV", None)
        else: os.environ["BINANCE_ENV"] = self._env
        botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH = self._paths
        self.td.cleanup()

    def due_listing(self, sym="NEW/USDT:USDT", age=31.0):
        return [(sym, 1_700_000_000_000, age)]

    def test_entry_shorts_and_registers_risk(self):
        ex = ListingFakeBinance(prices={"NEW/USDT:USDT": 10.0})
        with mock.patch.object(botmod, "listing_markets", return_value=self.due_listing()):
            botmod.run_once_listing(ex)
        pos = self.state["positions"].get("NEW/USDT:USDT") or botmod.load_state()["positions"].get("NEW/USDT:USDT")
        self.assertIsNotNone(pos)
        self.assertEqual(pos["side"], "short")
        ledger = riskmgr_mod.load_risk_state(botmod.RISK_PATH)
        self.assertIn("listing_short:NEW/USDT:USDT", ledger["open_risk"])

    def test_max_open_cap_skips_new_entries_once_full(self):
        ex = ListingFakeBinance(prices={"NEW/USDT:USDT": 10.0})
        botmod.CONFIG["enabled_strategies"] = ["listing_short"]
        for i in range(10):
            self.state["positions"][f"FILL{i}/USDT:USDT"] = {"side": "short", "entry": 1, "qty": 1, "sl": 2,
                "exit_at": "2099-01-01T00:00:00+00:00", "time": "2020-01-01T00:00:00+00:00", "leverage": 2}
        botmod.save_state(self.state)
        with mock.patch.object(botmod, "listing_markets", return_value=self.due_listing()):
            botmod.run_once_listing(ex)
        self.assertNotIn("NEW/USDT:USDT", botmod.load_state()["positions"])

    def test_sl_hit_exit_closes_and_releases_risk(self):
        ex = ListingFakeBinance(prices={"NEW/USDT:USDT": 10.0})
        with mock.patch.object(botmod, "listing_markets", return_value=self.due_listing()):
            botmod.run_once_listing(ex)
        ex.prices["NEW/USDT:USDT"] = 20.0                 # above the 40% stop -> must close
        with mock.patch.object(botmod, "listing_markets", return_value=[]):
            botmod.run_once_listing(ex)
        self.assertNotIn("NEW/USDT:USDT", botmod.load_state()["positions"])
        ledger = riskmgr_mod.load_risk_state(botmod.RISK_PATH)
        self.assertNotIn("listing_short:NEW/USDT:USDT", ledger["open_risk"])


if __name__ == "__main__":
    unittest.main()
