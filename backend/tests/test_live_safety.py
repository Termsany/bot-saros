"""Live-trading safety fixes on top of Stage C: keep an accepted stop, find conditional orders, unique protective ids,
"already set" futures settings, vault fail-closed."""
import os, tempfile, unittest
from pathlib import Path
from unittest import mock
import sys
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
import bot as botmod
from backend.app import oco as oco_mod
from backend.app.oco import place_oco_orders, cancel_oco_orders


def _ex(open_plain=(), open_trigger=()):
    ex = mock.Mock()
    ex.id = "binance"; ex.options = {}
    ex.market.return_value = {"contract": True, "linear": True, "inverse": False, "contractSize": 1.0}
    ex.price_to_precision.side_effect = lambda s, p: str(float(p))
    ex.create_order.side_effect = lambda sym, typ, side, qty, price, params: {"id": "x-" + params["clientOrderId"], "clientOrderId": params["clientOrderId"]}
    ex.fetch_order.side_effect = Exception("not found")
    ex.fetch_open_orders.side_effect = lambda sym, *a: list(open_trigger if (len(a) == 3 and a[2]) else open_plain)
    ex.fetch_funding_history = lambda symbol, since=None: []
    ex.cancel_order = mock.Mock()
    return ex


class ConditionalOrdersTests(unittest.TestCase):
    def test_stop_found_among_trigger_orders_is_verified(self):
        sl, tp = oco_mod._oco_id("raqm-aaaabbbbcccc", "sl"), oco_mod._oco_id("raqm-aaaabbbbcccc", "tp")
        # Binance keeps stop / take-profit orders apart from the plain open orders
        ex = _ex(open_plain=[], open_trigger=[{"id": "1", "clientOrderId": sl}, {"id": "2", "clientOrderId": tp}])
        res = place_oco_orders(ex, "BTC/USDT", "long", 0.01, 49000, 51000, paper=False, pos_id="raqm-aaaabbbbcccc")
        self.assertNotIn("verify_failed", res)
        ex.cancel_order.assert_not_called()

    def test_found_by_exchange_id(self):
        ex = _ex()
        ex.fetch_order.side_effect = lambda oid, sym: {"id": oid, "status": "open"}
        res = place_oco_orders(ex, "BTC/USDT", "short", 0.01, 51000, 49000, paper=False, pos_id="raqm-111122223333")
        self.assertNotIn("verify_failed", res)

    def test_stop_rejected_means_protection_missing(self):
        ex = _ex()
        def create(sym, typ, side, qty, price, params):
            if "stopLossPrice" in params: raise Exception("rejected")
            return {"id": "t", "clientOrderId": params["clientOrderId"]}
        ex.create_order.side_effect = create
        res = place_oco_orders(ex, "BTC/USDT", "long", 0.01, 49000, 51000, paper=False, pos_id="raqm-111122223333")
        self.assertTrue(res["protection_missing"])


class ProtectiveIdTests(unittest.TestCase):
    def test_ids_differ_between_entries(self):
        a = oco_mod._oco_id("raqm-0e8b777212da", "sl"); b = oco_mod._oco_id("raqm-0e8f00000000", "sl")
        self.assertNotEqual(a, b)
        self.assertLessEqual(len(a), 36)
        self.assertTrue(a.startswith("raqm-") and a.endswith("-sl"))

    def test_cancel_requires_readback_absence(self):
        ex = mock.Mock()
        owned = [{"id": "sl-1", "clientOrderId": "raqm-pos-sl"}]
        active = list(owned)
        ex.fetch_open_orders.side_effect = lambda sym, *a: list(active)
        ex.cancel_order.side_effect = lambda oid, *a: active.clear()
        self.assertTrue(cancel_oco_orders(ex, "BTC/USDT", sl_id="raqm-pos-sl"))

    def test_cancel_ambiguous_readback_stays_unconfirmed(self):
        ex = mock.Mock()
        ex.fetch_open_orders.return_value = [{"id": "sl-1", "clientOrderId": "raqm-pos-sl"}]
        self.assertFalse(cancel_oco_orders(ex, "BTC/USDT", sl_id="raqm-pos-sl"))

    def test_algo_endpoint_is_read_and_cancelled(self):
        ex = mock.Mock()
        active = [{"id": "algo-1", "clientOrderId": "raqm-pos-sl"}]
        ex.fetch_open_orders.return_value = []
        ex.fetch_open_algo_orders = lambda symbol: list(active)
        ex.cancel_algo_order = lambda oid, symbol: active.clear()
        self.assertTrue(cancel_oco_orders(ex, "BTC/USDT", sl_id="raqm-pos-sl"))

    def test_cancel_leaves_the_other_positions_stop(self):
        mine, other = "raqm-0e8b777212da", "raqm-0e8f00000000"
        ex = mock.Mock()
        ex.fetch_open_orders.return_value = [{"id": "1", "clientOrderId": oco_mod._oco_id(mine, "sl")},
                                             {"id": "2", "clientOrderId": oco_mod._oco_id(other, "sl")}]
        cancel_oco_orders(ex, "BTC/USDT", pos_id=mine)
        self.assertEqual([c[0][0] for c in ex.cancel_order.call_args_list], ["1"])


class FuturesSetupTests(unittest.TestCase):
    def setUp(self):
        self._cfg = dict(botmod.CONFIG); botmod.CONFIG["market"] = "future"
    def tearDown(self):
        botmod.CONFIG.clear(); botmod.CONFIG.update(self._cfg)

    def test_already_set_is_not_an_error(self):
        ex = mock.Mock(spec=["set_leverage", "set_margin_mode", "set_position_mode"])
        ex.set_margin_mode.side_effect = Exception('binance {"code":-4046,"msg":"No need to change margin type."}')
        ex.set_position_mode.side_effect = Exception('binance {"code":-4059,"msg":"No need to change position side."}')
        botmod.ensure_futures_setup(ex, "BTC/USDT")   # no exception

    def test_real_failure_still_stops_the_order(self):
        ex = mock.Mock(spec=["set_leverage", "set_margin_mode", "set_position_mode"])
        ex.set_leverage.side_effect = Exception("Invalid API-key, IP, or permissions for action")
        with self.assertRaises(RuntimeError):
            botmod.ensure_futures_setup(ex, "BTC/USDT")


class VaultTests(unittest.TestCase):
    def setUp(self):
        from backend.app import keys_vault as kv
        self.kv = kv
        self.td = tempfile.TemporaryDirectory()
        self._paths = (kv.VAULT_PATH, kv.MASTER_KEY_PATH)
        kv.VAULT_PATH = Path(self.td.name) / "vault.json"; kv.MASTER_KEY_PATH = Path(self.td.name) / ".master.key"
        self._env = {k: os.environ.get(k) for k in ("VAULT_MASTER_KEY", "ALLOW_LIVE_TRADING", "RENDER", "VERCEL", "RAILWAY_ENVIRONMENT")}
        for k in self._env: os.environ.pop(k, None)
    def tearDown(self):
        self.kv.VAULT_PATH, self.kv.MASTER_KEY_PATH = self._paths
        for k, v in self._env.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
        self.td.cleanup()

    def test_live_needs_a_separate_master_key(self):
        os.environ["ALLOW_LIVE_TRADING"] = "true"
        with self.assertRaises(RuntimeError):
            self.kv.get_fernet()
        self.assertFalse(self.kv.MASTER_KEY_PATH.exists())

    def test_wrong_key_does_not_wipe_saved_keys(self):
        from cryptography.fernet import Fernet
        os.environ["VAULT_MASTER_KEY"] = Fernet.generate_key().decode()
        self.kv.save_keys("binance", "k1", "s1")
        before = self.kv.VAULT_PATH.read_bytes()
        os.environ["VAULT_MASTER_KEY"] = Fernet.generate_key().decode()   # wrong key
        with self.assertRaises(RuntimeError):
            self.kv.save_keys("bybit", "k2", "s2")
        self.assertEqual(self.kv.VAULT_PATH.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()


class CloseLivePositionTests(unittest.TestCase):
    def setUp(self):
        self._cfg = dict(botmod.CONFIG); botmod.CONFIG.update({"paper_trading": False, "market": "future", "leverage": 5})
        self.td = tempfile.TemporaryDirectory(); botmod.LOG_PATH = Path(self.td.name) / "t.log"
    def tearDown(self):
        botmod.CONFIG.clear(); botmod.CONFIG.update(self._cfg); self.td.cleanup()

    def _ex(self):
        ex = mock.Mock(); ex.id = "binance"; ex.options = {}
        ex.market.return_value = {"contract": True, "linear": True, "inverse": False, "contractSize": 1.0}
        ex.amount_to_precision.side_effect = lambda s, q: str(q)
        ex.create_order.side_effect = lambda sym, typ, side, qty, price, params: {"id": "c1", "filled": qty, "average": 100.0, "fee": {"cost": abs(float(qty)) * 100.0 * 0.0004}}
        ex.fetch_open_orders.return_value = []
        ex.fetch_funding_history = lambda symbol, since=None: [{"amount": 0.0, "timestamp": 1}]
        ex.fetch_positions.side_effect = [[{"symbol": "SOL/USDT:USDT", "contracts": 0.37}], [{"symbol": "SOL/USDT:USDT", "contracts": 0}]]
        return ex

    def test_closes_the_exact_size_and_cancels_own_orders(self):
        ex = self._ex()
        pos = {"side": "long", "entry": 100.0, "qty": 0.37, "contract_size": 1.0, "contract_size_verified": True, "oco_ids": {"pos_id": "raqm-aaaabbbbcccc"}, "entry_fee_rate": 0.0004, "entry_fee_cost": 0.37 * 100.0 * 0.0004}
        sl = oco_mod._oco_id("raqm-aaaabbbbcccc", "sl")
        ex.fetch_open_orders.return_value = [{"id": "9", "clientOrderId": sl}, {"id": "8", "clientOrderId": "manual"}]
        orders = list(ex.fetch_open_orders.return_value)
        cancelled = set()
        def active_remove(oid):
            orders[:] = [o for o in orders if o["id"] != oid]
        ex.fetch_open_orders.side_effect = lambda sym, *a: [o for o in orders if o["id"] not in cancelled]
        ex.cancel_order.side_effect = lambda oid, *a: (cancelled.add(oid), active_remove(oid))[1]
        res = botmod.close_live_position(ex, "SOL/USDT", pos, 100.0)
        args = ex.create_order.call_args[0]
        self.assertEqual(args[2], "sell"); self.assertAlmostEqual(float(args[3]), 0.37)   # not 0.37 x leverage
        self.assertTrue(args[5].get("reduceOnly"))
        ex.set_leverage.assert_not_called()
        self.assertEqual([c[0][0] for c in ex.cancel_order.call_args_list], ["9"])        # our stop only, never "manual"
        self.assertFalse(res["by_exchange"])

    def test_already_flat_on_the_exchange_counts_as_closed(self):
        ex = self._ex()
        ex.create_order.side_effect = Exception('binance {"code":-2022,"msg":"ReduceOnly Order is rejected."}')
        ex.fetch_positions.return_value = [{"symbol": "SOL/USDT:USDT", "contracts": 0}]
        res = botmod.close_live_position(ex, "SOL/USDT", {"side": "short", "qty": 1.0}, 90.0)
        self.assertTrue(res["by_exchange"])

    def test_still_open_after_a_failed_close_raises(self):
        ex = self._ex()
        ex.fetch_positions.side_effect = None
        ex.create_order.side_effect = Exception("network down")
        ex.fetch_positions.return_value = [{"symbol": "SOL/USDT:USDT", "contracts": 1.0}]
        res = botmod.close_live_position(ex, "SOL/USDT", {"side": "long", "qty": 1.0}, 90.0)
        self.assertFalse(res["accounting_verified"])
        self.assertTrue(res["recovery_required"])
        with self.assertRaises(Exception):
            botmod._require_verified_close(res)


class LiveExchangeTests(unittest.TestCase):
    def test_binance_keys_go_to_binance(self):
        with mock.patch.dict(os.environ, {"BINANCE_API_KEY": "k", "BINANCE_SECRET": "s"}):
            ex, err = botmod.get_exchange(auth=True)
        self.assertIsNone(err); self.assertTrue(ex.id.startswith("binance"))

    def test_paper_data_needs_no_keys(self):
        ex, err = botmod.get_exchange(auth=False)
        self.assertIsNone(err); self.assertFalse(ex.apiKey)


class LlmLabGateTests(unittest.TestCase):
    def test_off_by_default_and_never_with_live(self):
        from backend.app import main as m
        with mock.patch.dict(os.environ, {"ENABLE_LLM_LAB": "", "ALLOW_LIVE_TRADING": ""}):
            self.assertFalse(m.llm_lab_allowed())
        with mock.patch.dict(os.environ, {"ENABLE_LLM_LAB": "true", "ALLOW_LIVE_TRADING": "true"}):
            self.assertFalse(m.llm_lab_allowed())
        with mock.patch.dict(os.environ, {"ENABLE_LLM_LAB": "true", "ALLOW_LIVE_TRADING": ""}):
            self.assertTrue(m.llm_lab_allowed())

    def test_name_dispatch_is_refused(self):
        from backend.app.llm_sandbox import validate_code, UnsafeCode
        head = "import pandas as pd\ndef llm_signal(df):\n"
        for body in ('    df.agg("to_csv", "/tmp/x")\n    return 0, {}',
                     '    df.agg("_"+"_class_"+"_")\n    return 0, {}',
                     '    m = "to" + "_pickle"\n    df.apply(m)\n    return 0, {}',
                     '    print("__RESULT__{}")\n    return 0, {}'):
            with self.assertRaises(UnsafeCode):
                validate_code(head + body)
        validate_code(head + '    ma = df["close"].rolling(20).mean()\n    return float((df["close"] > ma).iloc[-1]), {}')
