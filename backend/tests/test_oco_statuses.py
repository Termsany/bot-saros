import unittest

from backend.app.oco import _leg_on_exchange, _owned_orders


class Exchange:
    def __init__(self, status):
        self.status = status

    def fetch_order(self, oid, symbol):
        result = {"id": oid, "clientOrderId": "cid"}
        if self.status is not None:
            result["status"] = self.status
        return result

    def fetch_open_orders(self, *args):
        return []


class ProtectiveOrderStatusTests(unittest.TestCase):
    def test_active_statuses_are_accepted_case_insensitively(self):
        for status in ("open", "new", "active", "pending", "OPEN", "New"):
            self.assertTrue(_leg_on_exchange(Exchange(status), "BTC/USDT", {"id": "oid"}, "cid"), status)

    def test_inactive_unknown_and_missing_statuses_are_rejected(self):
        for status in ("closed", "canceled", "expired", "rejected", "unknown", None):
            self.assertFalse(_leg_on_exchange(Exchange(status), "BTC/USDT", {"id": "oid"}, "cid"), status)


class OpenView:
    """An exchange whose open-orders views list one of our stops with the given status."""
    def __init__(self, status):
        self.order = {"id": "oid", "clientOrderId": "cid"}
        if status is not None:
            self.order["status"] = status

    def fetch_open_orders(self, *args):
        return [self.order]


class OwnedOrdersStatusTests(unittest.TestCase):
    def test_listed_with_a_missing_or_unknown_status_counts_as_on_the_exchange(self):
        # cleanup must cancel it and _protect_pending must not send a second stop next to it
        for status in ("open", "NEW", "untriggered", "unknown", "", None):
            found, complete = _owned_orders(OpenView(status), "BTC/USDT", {"cid"})
            self.assertTrue(complete, status)
            self.assertIn("oid", found, status)

    def test_listed_with_a_finished_status_is_not_counted(self):
        for status in ("closed", "filled", "canceled", "Cancelled", "expired", "rejected"):
            found, complete = _owned_orders(OpenView(status), "BTC/USDT", {"cid"})
            self.assertTrue(complete, status)
            self.assertEqual(found, {}, status)