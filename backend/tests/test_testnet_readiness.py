import os
import tempfile
import unittest
from unittest import mock

from backend.app.testnet_readiness import check_testnet_readiness


class FakeExchange:
    def load_markets(self):
        return {"BTC/USDT:USDT": {"contract": True, "linear": True, "inverse": False, "contractSize": 1.0}}
    def fetch_balance(self): pass
    def fetch_positions(self): pass
    def fetch_order(self, *a): pass
    def fetch_open_orders(self, *a): pass
    def create_order(self, *a): raise AssertionError("readiness must not submit orders")
    def cancel_order(self, *a): raise AssertionError("readiness must not cancel orders")


class TestnetReadinessTests(unittest.TestCase):
    def test_readiness_is_read_only_and_requires_testnet(self):
        with mock.patch.dict(os.environ, {"BINANCE_ENV": "testnet", "ALLOW_LIVE_TRADING": "false"}):
            result = check_testnet_readiness(FakeExchange(), strategies=["trend_daily", "ratio_trend"],
                risk_state_loader=lambda: {"kill_switch": {"tripped": False}})
        self.assertTrue(result["ready"])
        self.assertEqual(result["orders_submitted"], 0)

    def test_live_environment_or_bad_metadata_blocks(self):
        class Bad(FakeExchange):
            def load_markets(self): return {"X": {"contract": True, "linear": False, "inverse": True, "contractSize": 1}}
        with mock.patch.dict(os.environ, {"BINANCE_ENV": "live", "ALLOW_LIVE_TRADING": "true"}):
            result = check_testnet_readiness(Bad(), strategies=["trend_daily"], risk_state_loader=lambda: {})
        self.assertFalse(result["ready"])
        self.assertFalse(result["checks"]["testnet_environment"])
        self.assertFalse(result["checks"]["live_locked"])
        self.assertFalse(result["checks"]["linear_contract_metadata"])


if __name__ == "__main__":
    unittest.main()
