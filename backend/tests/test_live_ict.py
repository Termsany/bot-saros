"""The generic score-based strategy ('ict', the default 20-pair long/short ensemble) real
order-execution path inside try_enter() (bot.py ~line 2379) — the one live path that had no
dedicated coverage: test_trend_live.py only exercises the trend_daily branch of the same
function. Deterministic FakeBinance only — no network."""
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


class IctFakeBinance(FakeBinance):
    """The score-based path places both a stop and a take-profit; the base FakeBinance's
    fetch_open_orders only tracks the stop leg (sufficient for trend_daily, which has no TP)."""

    def create_order(self, sym, typ, side, qty, price, params):
        params = dict(params or {})
        if "takeProfitPrice" in params:
            self.orders.append({"symbol": sym, "side": side, "qty": float(qty), "params": params})
            return {"id": "tp-" + params["clientOrderId"], "clientOrderId": params["clientOrderId"], "status": "open"}
        return super().create_order(sym, typ, side, qty, price, params)

    def fetch_open_orders(self, sym, *a):
        out = super().fetch_open_orders(sym, *a)
        out += [{"id": "tp-" + o["params"]["clientOrderId"], "clientOrderId": o["params"]["clientOrderId"], "status": "open"}
                for o in self.orders if "takeProfitPrice" in o["params"] and "tp-" + o["params"]["clientOrderId"] not in self.cancelled]
        return out

    def fetch_order(self, oid, sym):
        tp = next((o for o in self.orders if "takeProfitPrice" in o["params"] and "tp-" + o["params"]["clientOrderId"] == oid), None)
        if tp and oid not in self.cancelled: return {"id": oid, "status": "open"}
        return super().fetch_order(oid, sym)


LONG_SIG = {"price": 100.0, "total": 0.6, "decision": "شراء", "amount_mult": 1.0}
SHORT_SIG = {"price": 100.0, "total": -0.6, "decision": "بيع", "amount_mult": 1.0}
STRONG_SELL_SIG = {"price": 90.0, "total": -0.6, "decision": "بيع", "amount_mult": 1.0}


class IctLiveTests(unittest.TestCase):
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
                              "enabled_strategies": ["ict"], "max_open_positions": 10, "use_percent_risk": False,
                              "htf_filter": False, "vol_filter": False, "regime_filter": False, "cooldown_bars": 0,
                              "max_daily_loss_pct": 0})
        botmod._ENTRY_BLOCK["reason"] = ""
        self.state = botmod.load_state()

    def tearDown(self):
        botmod.CONFIG.clear(); botmod.CONFIG.update(self._cfg)
        if self._env is None: os.environ.pop("BINANCE_ENV", None)
        else: os.environ["BINANCE_ENV"] = self._env
        botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH = self._paths
        self.td.cleanup()

    def test_long_entry_places_order_stop_tp_and_registers_risk(self):
        ex = IctFakeBinance()
        botmod.try_enter("SOL/USDT:USDT", LONG_SIG, self.state, ex)
        buy = ex.orders[0]
        self.assertEqual(buy["side"], "buy")
        self.assertTrue(any(o["params"].get("stopLossPrice") for o in ex.orders[1:]))
        self.assertTrue(any(o["params"].get("takeProfitPrice") for o in ex.orders[1:]))
        pos = self.state["positions"]["SOL/USDT:USDT"]
        self.assertEqual(pos["side"], "long")
        ledger = riskmgr_mod.load_risk_state(botmod.RISK_PATH)
        self.assertIn("ict:SOL/USDT:USDT", ledger["open_risk"])

    def test_short_entry_places_order_and_registers_risk(self):
        ex = IctFakeBinance()
        botmod.try_enter("SOL/USDT:USDT", SHORT_SIG, self.state, ex)
        self.assertEqual(ex.orders[0]["side"], "sell")
        self.assertEqual(self.state["positions"]["SOL/USDT:USDT"]["side"], "short")

    def test_strong_reversal_closes_the_position_and_releases_risk(self):
        ex = IctFakeBinance()
        botmod.try_enter("SOL/USDT:USDT", LONG_SIG, self.state, ex)
        botmod.try_enter("SOL/USDT:USDT", STRONG_SELL_SIG, self.state, ex)
        self.assertNotIn("SOL/USDT:USDT", self.state["positions"])
        ledger = riskmgr_mod.load_risk_state(botmod.RISK_PATH)
        self.assertNotIn("ict:SOL/USDT:USDT", ledger["open_risk"])
        self.assertEqual(self.state["history"][-1]["type"], "live")

    def test_kill_switch_blocks_new_entry_but_not_an_existing_reversal_close(self):
        ex = IctFakeBinance()
        botmod.try_enter("SOL/USDT:USDT", LONG_SIG, self.state, ex)
        riskmgr_mod.trip_kill_switch(botmod.RISK_PATH, "test")
        botmod.reconcile_live(self.state, ex)
        n = len(ex.orders)
        botmod.try_enter("ETH/USDT:USDT", LONG_SIG, self.state, ex)
        self.assertEqual(len(ex.orders), n)                         # no new entry
        botmod.try_enter("SOL/USDT:USDT", STRONG_SELL_SIG, self.state, ex)
        self.assertNotIn("SOL/USDT:USDT", self.state["positions"])  # the reversal close still runs

    def test_flat_exchange_does_not_block_first_entry(self):
        ex = IctFakeBinance()
        botmod.reconcile_live(self.state, ex)
        self.assertEqual(botmod._ENTRY_BLOCK["reason"], "")
        botmod.try_enter("SOL/USDT:USDT", LONG_SIG, self.state, ex)
        self.assertIn("SOL/USDT:USDT", self.state["positions"])


if __name__ == "__main__":
    unittest.main()
