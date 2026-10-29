"""Per-user LIVE trend_daily execution — Phase B regression tests (TDD).

Proves the per-user live order path end to end with a deterministic fake
exchange (no real or testnet orders): entry -> protective stop on the
exchange -> per-user risk ledger reservation -> per-user state file, and
exit -> close -> risk release. Also proves the path only fires for a user
who is actually live-enabled with their own keys, and that one user's
cycle never touches another user's state/risk ledger files.
"""
import sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app import user_live_trading as ult
from app import user_live_activation as ula
from app import user_keys_vault as ukv
from app import risk_manager as riskmgr


class FakeBinance:
    """Minimal deterministic fake — enough of ccxt.binanceusdm for the trend's live path."""
    id = "binance"

    def __init__(self, fail_stop=False, balance=1000.0, min_cost=5.0):
        self.options = {}
        self.orders, self.cancelled, self.positions = [], [], {}
        self.fail_stop, self.balance, self.min_cost = fail_stop, balance, min_cost
        self.set_leverage = mock.Mock(); self.set_margin_mode = mock.Mock(); self.set_position_mode = mock.Mock()

    def market(self, sym):
        return {"contract": True, "linear": True, "inverse": False, "contractSize": 1.0, "limits": {"cost": {"min": self.min_cost}}}

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
            self.positions[base] = max(0.0, self.positions.get(base, 0.0) - float(qty))
            return {"id": "c", "filled": float(qty), "average": 110.0, "fee": {"cost": abs(float(qty)) * 110.0 * 0.0004}}
        self.positions[base] = self.positions.get(base, 0.0) + float(qty)
        return {"id": "e", "clientOrderId": params.get("clientOrderId"), "filled": float(qty), "average": 100.0,
                "fee": {"cost": abs(float(qty)) * 100.0 * 0.0004}}

    def fetch_order(self, oid, sym):
        o = next((o for o in self.orders if "stopLossPrice" in o["params"] and "stop-" + o["params"]["clientOrderId"] == oid), None)
        if o and oid not in self.cancelled: return {"id": oid, "status": "open"}
        raise Exception("not found")

    def fetch_open_orders(self, sym, *a):
        return [{"id": "stop-" + o["params"]["clientOrderId"], "clientOrderId": o["params"]["clientOrderId"]}
                for o in self.orders if "stopLossPrice" in o["params"] and "stop-" + o["params"]["clientOrderId"] not in self.cancelled]

    def cancel_order(self, oid, sym, *a): self.cancelled.append(oid)
    def fetch_positions(self, syms=None):
        return [{"symbol": f"{b}:USDT", "contracts": q} for b, q in self.positions.items() if not syms or b in [s.split(":")[0] for s in syms]]
    def fetch_my_trades(self, sym, since=None, limit=20, params=None): return [{"side": "sell", "price": 82.0, "amount": 5.0, "fee": {"cost": 5.0 * 82.0 * 0.0004}}]


SIG_ON = {"price": 100.0, "trend": {"on": True, "ts": 1, "size": 1.0}, "in_universe": True, "rank": 1, "total": 0}
SIG_OFF = {"price": 110.0, "trend": {"on": False, "ts": 2, "size": 1.0}, "in_universe": True, "rank": 1, "total": 0}


class UserLiveTrendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.bot_dir = Path(self.tmp.name)
        self.activation_path = self.bot_dir / "user_live_activation.sqlite3"
        self.vault_patch = mock.patch.object(ukv, "VAULT_PATH", self.bot_dir / "user_vault.json")
        self.vault_patch.start()
        import os
        self._old_master = os.environ.get("VAULT_MASTER_KEY")
        from cryptography.fernet import Fernet
        os.environ["VAULT_MASTER_KEY"] = Fernet.generate_key().decode()

    def tearDown(self):
        self.vault_patch.stop()
        import os
        if self._old_master is None: os.environ.pop("VAULT_MASTER_KEY", None)
        else: os.environ["VAULT_MASTER_KEY"] = self._old_master
        self.tmp.cleanup()

    def _enable(self, user_id, exchange="binance", **kw):
        ukv.save_user_keys(user_id, exchange, "AKEY", "ASECRET", "")
        ula.enable_user_live(self.activation_path, user_id=user_id, exchange=exchange,
                              confirm=ula.CONSENT_TEXT, actor=user_id, **kw)

    def test_cycle_does_nothing_for_a_user_who_never_enabled_live(self):
        ex = FakeBinance()
        result = ult.run_trend_daily_live_cycle(user_id="nobody", symbol="SOL/USDT:USDT", ex=ex,
                                                  bot_dir=self.bot_dir, analysis=SIG_ON,
                                                  activation_path=self.activation_path)
        self.assertFalse(result["fired"])
        self.assertEqual(result["reason"], "not enabled")
        self.assertEqual(ex.orders, [])  # no order path fires for a disabled/unknown user

    def test_cycle_does_nothing_if_enabled_but_keys_were_deleted_since(self):
        self._enable("u1")
        ukv.delete_user_keys("u1", "binance")  # keys removed after enabling
        ex = FakeBinance()
        result = ult.run_trend_daily_live_cycle(user_id="u1", symbol="SOL/USDT:USDT", ex=ex,
                                                  bot_dir=self.bot_dir, analysis=SIG_ON,
                                                  activation_path=self.activation_path)
        self.assertFalse(result["fired"])
        self.assertIn("keys", result["reason"])
        self.assertEqual(ex.orders, [])

    def test_entry_buys_then_puts_the_stop_on_the_exchange_for_enabled_user(self):
        self._enable("u1")
        ex = FakeBinance(balance=50000.0)
        result = ult.run_trend_daily_live_cycle(user_id="u1", symbol="SOL/USDT:USDT", ex=ex,
                                                  bot_dir=self.bot_dir, analysis=SIG_ON,
                                                  activation_path=self.activation_path, margin_usdt=100.0)
        self.assertTrue(result["fired"])
        self.assertEqual(result["action"], "enter")
        buys = [o for o in ex.orders if o["side"] == "buy"]
        stops = [o for o in ex.orders if "stopLossPrice" in o["params"]]
        self.assertEqual(len(buys), 1)
        self.assertEqual(len(stops), 1)   # protective stop verification path fired for this user
        state = ult.load_user_state(ult.user_state_path(self.bot_dir, "u1"))
        self.assertIn("SOL/USDT:USDT", state["positions"])
        self.assertTrue(state["positions"]["SOL/USDT:USDT"]["contract_size_verified"])

    def test_risk_ledger_reservation_is_registered_per_user(self):
        self._enable("u1")
        ex = FakeBinance(balance=50000.0)
        ult.run_trend_daily_live_cycle(user_id="u1", symbol="SOL/USDT:USDT", ex=ex, bot_dir=self.bot_dir,
                                        analysis=SIG_ON, activation_path=self.activation_path, margin_usdt=100.0)
        risk_state = riskmgr.load_risk_state(ult.user_risk_path(self.bot_dir, "u1"))
        self.assertIn("trend_daily:SOL/USDT:USDT", risk_state["open_risk"])

    def test_second_user_never_enabled_has_no_order_and_no_state_file(self):
        self._enable("u1")
        ex1, ex2 = FakeBinance(balance=50000.0), FakeBinance(balance=50000.0)
        ult.run_trend_daily_live_cycle(user_id="u1", symbol="SOL/USDT:USDT", ex=ex1, bot_dir=self.bot_dir,
                                        analysis=SIG_ON, activation_path=self.activation_path, margin_usdt=100.0)
        result2 = ult.run_trend_daily_live_cycle(user_id="u2", symbol="SOL/USDT:USDT", ex=ex2, bot_dir=self.bot_dir,
                                                   analysis=SIG_ON, activation_path=self.activation_path, margin_usdt=100.0)
        self.assertFalse(result2["fired"])
        self.assertEqual(ex2.orders, [])
        self.assertFalse(ult.user_state_path(self.bot_dir, "u2").exists())
        # u1's own state/risk ledger is untouched by u2's (no-op) cycle
        state1 = ult.load_user_state(ult.user_state_path(self.bot_dir, "u1"))
        self.assertIn("SOL/USDT:USDT", state1["positions"])

    def test_two_enabled_users_get_independent_state_and_risk_ledgers(self):
        self._enable("u1"); self._enable("u2")
        ex1, ex2 = FakeBinance(balance=50000.0), FakeBinance(balance=50000.0)
        ult.run_trend_daily_live_cycle(user_id="u1", symbol="SOL/USDT:USDT", ex=ex1, bot_dir=self.bot_dir,
                                        analysis=SIG_ON, activation_path=self.activation_path, margin_usdt=100.0)
        ult.run_trend_daily_live_cycle(user_id="u2", symbol="SOL/USDT:USDT", ex=ex2, bot_dir=self.bot_dir,
                                        analysis=SIG_ON, activation_path=self.activation_path, margin_usdt=100.0)
        self.assertNotEqual(ult.user_state_path(self.bot_dir, "u1"), ult.user_state_path(self.bot_dir, "u2"))
        s1 = ult.load_user_state(ult.user_state_path(self.bot_dir, "u1"))
        s2 = ult.load_user_state(ult.user_state_path(self.bot_dir, "u2"))
        self.assertIn("SOL/USDT:USDT", s1["positions"]); self.assertIn("SOL/USDT:USDT", s2["positions"])
        r1 = riskmgr.load_risk_state(ult.user_risk_path(self.bot_dir, "u1"))
        r2 = riskmgr.load_risk_state(ult.user_risk_path(self.bot_dir, "u2"))
        self.assertEqual(r1["limits"]["leverage"], 2); self.assertEqual(r2["limits"]["leverage"], 2)
        # u1 closing their position never touches u2's ledger/state
        ult.run_trend_daily_live_cycle(user_id="u1", symbol="SOL/USDT:USDT", ex=ex1, bot_dir=self.bot_dir,
                                        analysis=SIG_OFF, activation_path=self.activation_path, margin_usdt=100.0)
        s1b = ult.load_user_state(ult.user_state_path(self.bot_dir, "u1"))
        s2b = ult.load_user_state(ult.user_state_path(self.bot_dir, "u2"))
        self.assertNotIn("SOL/USDT:USDT", s1b["positions"])   # u1 closed
        self.assertIn("SOL/USDT:USDT", s2b["positions"])       # u2 unaffected

    def test_exit_closes_position_and_releases_risk(self):
        self._enable("u1")
        ex = FakeBinance(balance=50000.0)
        ult.run_trend_daily_live_cycle(user_id="u1", symbol="SOL/USDT:USDT", ex=ex, bot_dir=self.bot_dir,
                                        analysis=SIG_ON, activation_path=self.activation_path, margin_usdt=100.0)
        result = ult.run_trend_daily_live_cycle(user_id="u1", symbol="SOL/USDT:USDT", ex=ex, bot_dir=self.bot_dir,
                                                  analysis=SIG_OFF, activation_path=self.activation_path, margin_usdt=100.0)
        self.assertTrue(result["fired"])
        self.assertEqual(result["action"], "exit")
        state = ult.load_user_state(ult.user_state_path(self.bot_dir, "u1"))
        self.assertNotIn("SOL/USDT:USDT", state["positions"])
        risk_state = riskmgr.load_risk_state(ult.user_risk_path(self.bot_dir, "u1"))
        self.assertNotIn("trend_daily:SOL/USDT:USDT", risk_state["open_risk"])

    def test_rejected_protective_stop_closes_the_position_immediately(self):
        self._enable("u1")
        ex = FakeBinance(fail_stop=True, balance=50000.0)
        result = ult.run_trend_daily_live_cycle(user_id="u1", symbol="SOL/USDT:USDT", ex=ex, bot_dir=self.bot_dir,
                                                  analysis=SIG_ON, activation_path=self.activation_path, margin_usdt=100.0)
        self.assertTrue(result["fired"])
        self.assertTrue(result.get("protection_missing"))
        state = ult.load_user_state(ult.user_state_path(self.bot_dir, "u1"))
        self.assertNotIn("SOL/USDT:USDT", state["positions"])  # fail-closed: no stop -> closed at once

    def test_oversized_entry_is_blocked_by_the_users_own_risk_gate(self):
        self._enable("u1", risk_per_trade_pct=0.01, max_aggregate_risk_pct=0.01)
        ex = FakeBinance()
        result = ult.run_trend_daily_live_cycle(user_id="u1", symbol="SOL/USDT:USDT", ex=ex, bot_dir=self.bot_dir,
                                                  analysis=SIG_ON, activation_path=self.activation_path, margin_usdt=100.0)
        self.assertFalse(result["fired"])
        self.assertIn("risk", result["reason"])
        self.assertEqual(ex.orders, [])


if __name__ == "__main__":
    unittest.main()
