"""Binance keeps stop / take-profit orders apart from plain orders (seen on Binance Demo, 2026-10-29): they show only
in the trigger/stop views, and a plain cancel_order answers -2011 "Unknown order sent". cancel_oco_orders must cancel
them through the view it found them in, or every live exit ends in "protective cleanup is unconfirmed" recovery."""
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
import ccxt
from backend.app import oco


class BinanceLike:
    """Conditional orders as Binance USDT-M serves them through ccxt."""
    def __init__(self, cid, *, status="open"):
        # Binance's conditional-order view must expose a documented active status.
        self.stops = {"1000000263046590": {"id": "1000000263046590", "clientOrderId": cid, "type": "STOP_MARKET", "status": status}}
        self.calls = []

    def fetch_open_orders(self, symbol, since=None, limit=None, params=None):
        params = params or {}
        return list(self.stops.values()) if (params.get("trigger") or params.get("stop")) else []

    def cancel_order(self, oid, symbol, params=None):
        self.calls.append(dict(params or {}))
        if not (params or {}).get("trigger") and not (params or {}).get("stop"):
            raise ccxt.OrderNotFound('binanceusdm {"code":-2011,"msg":"Unknown order sent."}')
        self.stops.pop(oid, None)
        return {"id": oid, "status": "canceled"}


class ConditionalCancelTests(unittest.TestCase):
    def test_stop_found_in_the_trigger_view_is_cancelled_through_it(self):
        pos_id = "raqm-diag12345678"
        ex = BinanceLike(oco._oco_id(pos_id, "sl"))
        self.assertTrue(oco.cancel_oco_orders(ex, "DOGE/USDT:USDT", pos_id=pos_id))
        self.assertEqual(ex.stops, {})
        self.assertTrue(ex.calls and (ex.calls[0].get("trigger") or ex.calls[0].get("stop")))

    def test_nothing_of_ours_left_is_success_and_other_orders_untouched(self):
        ex = BinanceLike("manual-order-from-the-app")
        self.assertTrue(oco.cancel_oco_orders(ex, "DOGE/USDT:USDT", pos_id="raqm-other0000000"))
        self.assertEqual(len(ex.stops), 1)                     # a manual stop is never ours to cancel
        self.assertEqual(ex.calls, [])

    def test_missing_status_in_the_open_view_is_still_cancelled(self):
        # an open-orders view listed it, so it is live: skipping it reported "cancelled" with the stop left on the
        # exchange, where it could later close a new position on the coin
        ex = BinanceLike(oco._oco_id("raqm-diag12345678", "sl"), status="")
        ex.stops["1000000263046590"].pop("status")
        self.assertFalse(oco._is_active_protection_order(ex.stops["1000000263046590"]))   # still not proof it protects
        self.assertTrue(oco.cancel_oco_orders(ex, "DOGE/USDT:USDT", pos_id="raqm-diag12345678"))
        self.assertEqual(ex.stops, {})
        self.assertTrue(ex.calls and (ex.calls[0].get("trigger") or ex.calls[0].get("stop")))

    def test_unknown_status_that_survives_the_cancel_is_not_success(self):
        ex = BinanceLike(oco._oco_id("raqm-diag12345678", "sl"), status="untriggered")
        ex.cancel_order = lambda oid, symbol, params=None: {"id": oid}      # accepted, but the stop stays listed
        self.assertFalse(oco.cancel_oco_orders(ex, "DOGE/USDT:USDT", pos_id="raqm-diag12345678"))
        self.assertEqual(len(ex.stops), 1)


if __name__ == "__main__":
    unittest.main()
