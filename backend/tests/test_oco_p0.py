"""
Run from repo root:  python -m pytest backend/tests/test_oco_p0.py -v
Regression for P0-01, P0-04, P0-05, P0-02.
No network, no real keys, mocked exchanges.
"""
import unittest
from unittest import mock

# P0-02: ensure_futures_setup must raise on failure (never silently pass)
class FuturesSetupTests(unittest.TestCase):
    def test_ensure_futures_setup_raises_on_leverage_failure(self):
        import bot
        ex = mock.Mock()
        ex.set_leverage.side_effect = Exception("not supported")
        bot.CONFIG["market"] = "future"
        with self.assertRaises(RuntimeError):
            bot.ensure_futures_setup(ex, "BTC/USDT")

# P0-01: place_oco_orders must not leave partial protection
class OcoTests(unittest.TestCase):
    def test_partial_oco_keeps_the_stop(self):
        from backend.app.oco import place_oco_orders
        ex = mock.Mock()
        ex.price_to_precision.side_effect = lambda s, p: str(p)
        # SL succeeds, TP fails
        def create_order(sym, typ, side, qty, price, params):
            if "stopLossPrice" in params:
                return {"id": "sl-1", "clientOrderId": params.get("clientOrderId"), "status": "open"}
            raise Exception("tp rejected")
        ex.create_order.side_effect = create_order
        ex.cancel_order = mock.Mock()
        ex.fetch_open_orders.return_value = []
        res = place_oco_orders(ex, "BTC/USDT", "long", 0.01, 90000, 110000, paper=False, pos_id="abcd1234")
        self.assertTrue(res.get("tp_missing"))
        self.assertNotIn("protection_missing", res)
        ex.cancel_order.assert_not_called()      # a position with its stop beats one without

    def test_paper_path_no_exchange_call(self):
        from backend.app.oco import place_oco_orders
        ex = mock.Mock()
        res = place_oco_orders(ex, "BTC/USDT", "long", 0.01, 90000, 110000, paper=True)
        self.assertEqual(res["paper"], True)
        ex.create_order.assert_not_called()

# P0-04: cancel only owned orders
class CancelOwnershipTests(unittest.TestCase):
    def test_cancel_only_owned_ids(self):
        from backend.app.oco import cancel_oco_orders, OCO_PREFIX
        ex = mock.Mock()
        # two open orders: one owned, one manual
        owned = f"{OCO_PREFIX}-abcd1234-sl"
        ex.fetch_open_orders.return_value = [
            {"id": "1", "clientOrderId": owned, "type": "STOP_MARKET", "status": "open"},
            {"id": "2", "clientOrderId": "manual-xyz", "type": "STOP_MARKET", "status": "open"},
        ]
        ex.cancel_order = mock.Mock()
        cancel_oco_orders(ex, "BTC/USDT", pos_id="abcd1234")
        self.assertEqual(ex.cancel_order.call_count, 1)
        self.assertEqual(ex.cancel_order.call_args[0][0], "1")

# P0-05: place_order idempotency via clientOrderId
class IdempotencyTests(unittest.TestCase):
    def test_place_order_uses_client_order_id(self):
        import bot
        bot.CONFIG["paper_trading"] = True  # paper still returns clientOrderId
        ex = mock.Mock()
        ex.amount_to_precision.return_value = "0.01"
        res = bot.place_order(ex, "BTC/USDT", "long", 20, 50000, client_order_id="raqm-abc123")
        self.assertEqual(res["clientOrderId"], "raqm-abc123")

    def test_pending_blocks_double_enter(self):
        import bot
        bot.CONFIG["paper_trading"] = True
        ex = mock.Mock()
        ex.amount_to_precision.return_value = "0.01"
        # state with pending for BTC/USDT
        state = {"positions": {}, "pending_orders": {"BTC/USDT": "raqm-pending"}, "last_trade": {}, "stats": {"trades":0,"wins":0,"losses":0,"pnl":0}, "history": []}
        analysis = {"total": 0.5, "price": 50000, "decision": "شراء", "amount_mult": 1.0}
        # should return early without placing order
        bot.try_enter("BTC/USDT", analysis, state, ex)
        ex.create_order = mock.Mock()
        # ensure no order was placed (paper path not even reached for live check)
        self.assertNotIn("BTC/USDT", state["positions"])
