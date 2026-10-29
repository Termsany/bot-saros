"""scripts/demo_e2e.py (Phase 1 harness) against a simulated exchange: every scenario passes, nothing is left
open, and it refuses to run anywhere but Binance Demo. The real run is on Binance Demo with Demo keys."""
import os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(ROOT / "scripts"))
import bot as botmod
import demo_e2e as h
from test_trend_live import FakeBinance


class Sim(FakeBinance):
    urls = {"api": {"fapiPrivate": "https://demo-fapi.binance.com/fapi/v1"}}
    def __init__(self): super().__init__(); self.fills = []; self.markets = {}
    def load_markets(self): return {}
    def fetch_ticker(self, s): return {"last": 100.0}
    def create_order(self, sym, typ, side, qty, price, params):
        p = dict(params or {}); base = sym.split(":")[0]
        if "stopLossPrice" in p or "takeProfitPrice" in p:
            self.orders.append({"symbol": sym, "side": side, "qty": float(qty), "params": p})
            return {"id": "stop-" + p["clientOrderId"], "clientOrderId": p["clientOrderId"], "status": "open"}
        if float(qty) * 100.0 < 5: raise Exception('binanceusdm {"code":-4164,"msg":"Order\'s notional must be no smaller than 5"}')
        signed = float(qty) if side == "buy" else -float(qty)
        self.positions[base] = self.positions.get(base, 0.0) + signed
        if abs(self.positions[base]) < 1e-12: self.positions[base] = 0.0
        self.orders.append({"symbol": sym, "side": side, "qty": float(qty), "params": p})
        oid = f"o{len(self.orders)}"
        # like Binance (seen on Demo): the fill is split, and only the fills carry the price and the fee
        for part in (float(qty) * 0.4, float(qty) * 0.6):
            self.fills.append({"symbol": sym, "side": side, "order": oid, "amount": part, "filled": part, "price": 100.0,
                               "fee": {"cost": part * 100 * 0.0004, "currency": "USDT"}, "timestamp": 2e12})
        return {"id": oid, "clientOrderId": p.get("clientOrderId"), "filled": float(qty), "average": None, "fee": None, "status": "closed"}
    def fetch_positions(self, syms=None):
        out = []
        for b, q in self.positions.items():
            if q and (not syms or b in [x.split(":")[0] for x in syms]):
                out.append({"symbol": b + ":USDT", "contracts": abs(q), "side": "long" if q > 0 else "short"})
        return out
    # like Binance USDT-M (seen on Demo): stop/take-profit orders only show in the trigger/stop views, and a plain
    # cancel of one answers -2011 "Unknown order sent"
    def _stops(self, sym):
        return [{"id": "stop-" + o["params"]["clientOrderId"], "clientOrderId": o["params"]["clientOrderId"]}
                for o in self.orders if o["symbol"] == sym and ("stopLossPrice" in o["params"] or "takeProfitPrice" in o["params"])
                and "stop-" + o["params"]["clientOrderId"] not in self.cancelled]
    def fetch_open_orders(self, sym, since=None, limit=None, params=None):
        return self._stops(sym) if (params or {}).get("trigger") or (params or {}).get("stop") else []
    def cancel_order(self, oid, sym, params=None):
        if oid.startswith("stop-") and not ((params or {}).get("trigger") or (params or {}).get("stop")):
            import ccxt; raise ccxt.OrderNotFound('binanceusdm {"code":-2011,"msg":"Unknown order sent."}')
        self.cancelled.append(oid)
    def fetch_order(self, oid, sym, params=None):
        for o in self._stops(sym):
            if o["id"] == oid or o["clientOrderId"] == oid: return {**o, "status": "open"}
        raise Exception("not found")
    def fetch_my_trades(self, sym, since=None, limit=100, params=None):
        oid = (params or {}).get("orderId")
        return [f for f in self.fills if f["symbol"] == sym and (oid is None or f["order"] == oid)]
    def fetch_funding_rate_history(self, *a, **k): return []



class HarnessTests(unittest.TestCase):
    def setUp(self):
        self._cfg = dict(botmod.CONFIG); self._env = os.environ.get("BINANCE_ENV")
        self._paths = (botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH, botmod.ENTRY_RECHECK_S)
    def tearDown(self):
        botmod.CONFIG.clear(); botmod.CONFIG.update(self._cfg)
        if self._env is None: os.environ.pop("BINANCE_ENV", None)
        else: os.environ["BINANCE_ENV"] = self._env
        botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH, botmod.ENTRY_RECHECK_S = self._paths

    def run_harness(self, ex, env="demo"):
        os.environ["BINANCE_ENV"] = env
        out = Path(tempfile.mkdtemp()) / "r.json"
        with mock.patch.object(botmod, "get_exchange", lambda auth=False: (ex, None)), mock.patch.object(h.time, "sleep", lambda s: None),              mock.patch.object(sys, "argv", ["demo_e2e.py", "--out", str(out)]):
            with self.assertRaises(SystemExit) as e: h.main()
        return e.exception.code, out

    def test_every_scenario_passes_and_nothing_is_left_open(self):
        import json
        ex = Sim(); code, out = self.run_harness(ex)
        report = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(code, 0, [s for s in report["scenarios"] if not s["ok"]])
        self.assertEqual(len(report["scenarios"]), len(h.SCENARIOS))
        self.assertEqual(report["cleanup"], [])
        self.assertTrue(all(abs(q) < 1e-12 for q in ex.positions.values()))

    def test_refuses_anything_but_demo(self):
        code, _ = self.run_harness(Sim(), env="live")
        self.assertIn("refusing", str(code))
        ex = Sim(); ex.urls = {"api": {"fapiPrivate": "https://fapi.binance.com/fapi/v1"}}
        code, _ = self.run_harness(ex)
        self.assertIn("refusing", str(code))
        self.assertEqual(ex.orders, [])                                    # not a single order sent


if __name__ == "__main__":
    unittest.main()
