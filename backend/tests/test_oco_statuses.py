import unittest

from backend.app.oco import _leg_on_exchange


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