"""Daily trend with real orders (Binance USDT-M, one-way): market buy + stop on the exchange, exit on the signal,
reconciliation with the exchange every cycle. Mock exchange — Binance Demo Trading is the next check."""
import os, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
import bot as botmod
from backend.app import oco as oco_mod


class FakeBinance:
    """Enough of ccxt.binanceusdm for the trend's live path."""
    id = "binance"

    def __init__(self, fail_stop=False, fail_close=False, balance=1000.0, min_cost=5.0):
        self.options = {}
        self.orders, self.cancelled, self.positions = [], [], {}
        self.fail_stop, self.fail_close, self.balance, self.min_cost = fail_stop, fail_close, balance, min_cost
        self.set_leverage = mock.Mock(); self.set_margin_mode = mock.Mock(); self.set_position_mode = mock.Mock()

    def market(self, sym): return {"limits": {"cost": {"min": self.min_cost}}}
    def amount_to_precision(self, sym, q): return str(round(float(q), 6))
    def price_to_precision(self, sym, p): return str(round(float(p), 6))
    def fetch_balance(self): return {"USDT": {"free": self.balance}}

    def create_order(self, sym, typ, side, qty, price, params):
        params = dict(params or {}); self.orders.append({"symbol": sym, "side": side, "qty": float(qty), "params": params})
        base = sym.split(":")[0]
        if "stopLossPrice" in params:
            if self.fail_stop: raise Exception("binance stop rejected")
            return {"id": "stop-" + params["clientOrderId"], "clientOrderId": params["clientOrderId"], "status": "open"}
        if params.get("reduceOnly"):
            if self.fail_close: raise Exception("network down")
            self.positions[base] = max(0.0, self.positions.get(base, 0.0) - float(qty))
            return {"id": "c", "filled": float(qty), "average": 110.0}
        self.positions[base] = self.positions.get(base, 0.0) + float(qty)
        return {"id": "e", "clientOrderId": params.get("clientOrderId"), "filled": float(qty), "average": 100.0}

    def fetch_order(self, oid, sym):
        o = next((o for o in self.orders if "stopLossPrice" in o["params"] and "stop-" + o["params"]["clientOrderId"] == oid), None)
        if o and oid not in self.cancelled: return {"id": oid, "status": "open"}
        raise Exception("not found")

    def fetch_open_orders(self, sym, *a):
        return [{"id": "stop-" + o["params"]["clientOrderId"], "clientOrderId": o["params"]["clientOrderId"]}
                for o in self.orders if "stopLossPrice" in o["params"] and "stop-" + o["params"]["clientOrderId"] not in self.cancelled]

    def cancel_order(self, oid, sym, *a): self.cancelled.append(oid)
    def fetch_positions(self, syms=None):
        return [{"symbol": f"{b}:USDT", "contracts": q} for b, q in self.positions.items() if q and (not syms or b in [s.split(":")[0] for s in syms])]
    def fetch_my_trades(self, sym, limit=20): return [{"side": "sell", "price": 82.0}]


SIG_ON = {"price": 100.0, "trend": {"on": True, "ts": 1, "size": 1.0}, "in_universe": True, "rank": 1, "total": 0}
SIG_OFF = {"price": 110.0, "trend": {"on": False, "ts": 2, "size": 1.0}, "in_universe": True, "rank": 1, "total": 0}


class TrendLiveTests(unittest.TestCase):
    def setUp(self):
        self._cfg = dict(botmod.CONFIG)
        self.td = tempfile.TemporaryDirectory()
        self._paths = (botmod.STATE_PATH, botmod.LOG_PATH)
        botmod.STATE_PATH = Path(self.td.name) / "state.json"; botmod.LOG_PATH = Path(self.td.name) / "t.log"
        botmod.CONFIG.update({"paper_trading": False, "market": "future", "leverage": 5, "trade_amount_usdt": 100,
                              "enabled_strategies": ["trend_daily"], "max_open_positions": 10, "use_percent_risk": False})
        botmod._ENTRY_BLOCK["reason"] = ""
        self.state = botmod.load_state()
    def tearDown(self):
        botmod.CONFIG.clear(); botmod.CONFIG.update(self._cfg)
        botmod.STATE_PATH, botmod.LOG_PATH = self._paths
        self.td.cleanup()

    def test_entry_buys_then_puts_the_stop_on_the_exchange(self):
        ex = FakeBinance()
        botmod.try_enter("SOL/USDT:USDT", SIG_ON, self.state, ex)
        buy, stop = ex.orders
        self.assertEqual((buy["side"], buy["qty"]), ("buy", 5.0))                       # $100 x5 / $100
        self.assertNotIn("positionSide", buy["params"]); self.assertNotIn("reduceOnly", buy["params"])
        self.assertEqual(stop["side"], "sell"); self.assertTrue(stop["params"]["reduceOnly"])
        self.assertAlmostEqual(stop["params"]["stopLossPrice"], 100 * (1 - 0.8 / 5))    # 84 — before liquidation
        self.assertEqual(len([o for o in ex.orders if "takeProfitPrice" in o["params"]]), 0)   # no target
        pos = self.state["positions"]["SOL/USDT:USDT"]
        self.assertTrue(pos["oco_ids"]["sl"]); self.assertFalse(self.state.get("recovery_required"))
        ex.set_leverage.assert_called_with(5, "SOL/USDT:USDT")

    def test_rejected_stop_closes_at_once(self):
        ex = FakeBinance(fail_stop=True)
        botmod.try_enter("SOL/USDT:USDT", SIG_ON, self.state, ex)
        self.assertNotIn("SOL/USDT:USDT", self.state["positions"])
        self.assertEqual(ex.positions["SOL/USDT"], 0.0)
        self.assertEqual(self.state["history"][-1]["reason"], "الوقف اترفض — قفل فوري")

    def test_rejected_stop_and_failed_close_is_tracked_and_blocks_entries(self):
        ex = FakeBinance(fail_stop=True, fail_close=True)
        botmod.try_enter("SOL/USDT:USDT", SIG_ON, self.state, ex)
        self.assertTrue(self.state["positions"]["SOL/USDT:USDT"]["unprotected"])
        self.assertIn("SOL/USDT:USDT", self.state["recovery_required"])
        n = len(ex.orders)
        botmod.try_enter("ETH/USDT:USDT", {**SIG_ON, "trend": {"on": True, "ts": 9, "size": 1.0}}, self.state, ex)
        self.assertEqual(len(ex.orders), n)                                              # nothing new anywhere

    def test_too_small_for_the_exchange_minimum_sends_nothing(self):
        ex = FakeBinance(min_cost=1000)
        botmod.try_enter("BTC/USDT:USDT", SIG_ON, self.state, ex)
        self.assertEqual(ex.orders, [])

    def test_not_enough_balance_sends_nothing(self):
        ex = FakeBinance(balance=50)
        botmod.try_enter("SOL/USDT:USDT", SIG_ON, self.state, ex)
        self.assertEqual(ex.orders, [])

    def test_trend_off_closes_exact_size_and_cancels_its_stop(self):
        ex = FakeBinance()
        botmod.try_enter("SOL/USDT:USDT", SIG_ON, self.state, ex)
        stop_id = "stop-" + ex.orders[1]["params"]["clientOrderId"]
        botmod.try_enter("SOL/USDT:USDT", SIG_OFF, self.state, ex)
        close = ex.orders[-1]
        self.assertEqual((close["side"], close["qty"]), ("sell", 5.0)); self.assertTrue(close["params"]["reduceOnly"])
        self.assertIn(stop_id, ex.cancelled)
        self.assertNotIn("SOL/USDT:USDT", self.state["positions"])
        h = self.state["history"][-1]; self.assertEqual(h["type"], "live"); self.assertAlmostEqual(h["pnl"], (110 - 100) * 5)

    def test_exit_still_runs_while_entries_are_blocked(self):
        ex = FakeBinance()
        botmod.try_enter("SOL/USDT:USDT", SIG_ON, self.state, ex)
        self.state["recovery_required"] = {"XRP/USDT:USDT": {"reason": "test"}}
        botmod.try_enter("SOL/USDT:USDT", SIG_OFF, self.state, ex)
        self.assertNotIn("SOL/USDT:USDT", self.state["positions"])

    def test_reconcile_records_a_stop_filled_on_the_exchange(self):
        ex = FakeBinance()
        botmod.try_enter("SOL/USDT:USDT", SIG_ON, self.state, ex)
        ex.positions["SOL/USDT"] = 0.0                                                  # the exchange stop filled
        botmod.reconcile_live(self.state, ex)
        self.assertNotIn("SOL/USDT:USDT", self.state["positions"])
        h = self.state["history"][-1]; self.assertEqual(h["reason"], "وقف المنصة"); self.assertAlmostEqual(h["exit"], 82.0)

    def test_unknown_position_blocks_new_entries(self):
        ex = FakeBinance(); ex.positions["DOGE/USDT"] = 100.0                           # opened by hand on the same account
        botmod.reconcile_live(self.state, ex)
        botmod.try_enter("SOL/USDT:USDT", SIG_ON, self.state, ex)
        self.assertEqual(ex.orders, [])
        self.assertIn("DOGE", botmod._ENTRY_BLOCK["reason"])


class StartupGateTests(unittest.TestCase):
    def _run(self, *args, env=None):
        e = {k: v for k, v in os.environ.items() if k not in ("ALLOW_LIVE_TRADING", "BINANCE_ENV")}
        e.update(env or {}); e["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run([sys.executable, str(ROOT / "bot.py"), *args], capture_output=True, text=True, env=e,
                              cwd=tempfile.gettempdir(), timeout=60, encoding="utf-8")

    def test_live_only_for_the_daily_trend(self):
        r = self._run("--live", "--strategy", "momentum_ls", "--once", env={"BINANCE_ENV": "demo"})
        self.assertNotEqual(r.returncode, 0); self.assertIn("trend_daily", r.stderr)

    def test_real_money_needs_the_server_switch(self):
        r = self._run("--live", "--strategy", "trend_daily", "--once")
        self.assertNotEqual(r.returncode, 0); self.assertIn("ALLOW_LIVE_TRADING", r.stderr)


if __name__ == "__main__":
    unittest.main()


class ManualCloseTests(TrendLiveTests):
    def _request(self, ipc, symbol, age=0):
        import json, time
        (ipc / "commands").mkdir(parents=True, exist_ok=True)
        (ipc / "commands" / "close-abc.json").write_text(json.dumps({"id": "abc", "symbol": symbol, "at_epoch": time.time() - age, "by": "admin"}))

    def test_site_close_closes_records_and_holds_the_coin(self):
        ex = FakeBinance(); ipc = Path(self.td.name) / "ipc"
        botmod.try_enter("SOL/USDT:USDT", SIG_ON, self.state, ex)
        self._request(ipc, "SOL/USDT")
        with mock.patch.dict(os.environ, {"RAQM_IPC_DIR": str(ipc)}):
            botmod.process_manual_closes(self.state, ex, {"SOL/USDT:USDT": 105.0})
        import json
        res = json.loads((ipc / "results" / "abc.json").read_text(encoding="utf-8"))
        self.assertTrue(res["ok"]); self.assertNotIn("SOL/USDT:USDT", self.state["positions"])
        self.assertEqual(self.state["history"][-1]["reason"], "قفل يدوي من الموقع")
        self.assertFalse(list((ipc / "commands").glob("*.json")))
        n = len(ex.orders)                                   # trend still on, next day: no re-buy while held
        botmod.try_enter("SOL/USDT:USDT", {**SIG_ON, "trend": {"on": True, "ts": 5, "size": 1.0}}, self.state, ex)
        self.assertEqual(len(ex.orders), n)
        botmod.try_enter("SOL/USDT:USDT", {**SIG_OFF, "trend": {"on": False, "ts": 6, "size": 1.0}}, self.state, ex)
        botmod.try_enter("SOL/USDT:USDT", {**SIG_ON, "trend": {"on": True, "ts": 7, "size": 1.0}}, self.state, ex)
        self.assertGreater(len(ex.orders), n)                # off then on again: a new signal may buy

    def test_old_request_is_dropped_not_executed(self):
        ex = FakeBinance(); ipc = Path(self.td.name) / "ipc"
        botmod.try_enter("SOL/USDT:USDT", SIG_ON, self.state, ex)
        self._request(ipc, "SOL/USDT", age=3600)
        with mock.patch.dict(os.environ, {"RAQM_IPC_DIR": str(ipc)}):
            botmod.process_manual_closes(self.state, ex, {})
        self.assertIn("SOL/USDT:USDT", self.state["positions"])


class ExitLevelTests(unittest.TestCase):
    def test_exit_level_is_the_trend_boundary(self):
        import random, strategies_trend as st
        random.seed(3); c = [100.0]
        for _ in range(300): c.append(c[-1] * (1 + random.gauss(0.001, 0.03)))
        lvl = st.exit_level(c)
        self.assertTrue(st.trend_on(c + [lvl * 1.001], len(c)))
        self.assertFalse(st.trend_on(c + [lvl * 0.999], len(c)))
