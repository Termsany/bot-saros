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
    ex.price_to_precision.side_effect = lambda s, p: str(float(p))
    ex.create_order.side_effect = lambda sym, typ, side, qty, price, params: {"id": "x-" + params["clientOrderId"], "clientOrderId": params["clientOrderId"]}
    ex.fetch_order.side_effect = Exception("not found")
    ex.fetch_open_orders.side_effect = lambda sym, *a: list(open_trigger if (len(a) == 3 and a[2]) else open_plain)
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
