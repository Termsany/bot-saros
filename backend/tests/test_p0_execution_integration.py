import unittest
from unittest.mock import Mock

import bot


class FakeFutureExchange:
    id = "binance"
    options = {}

    def __init__(self, positions):
        self.positions = positions
        self.created = []

    def market(self, symbol):
        return {"contract": True, "linear": True, "inverse": False, "contractSize": 0.001}

    def amount_to_precision(self, symbol, qty):
        return str(qty)

    def create_order(self, symbol, kind, side, qty, price, params):
        self.created.append((symbol, side, qty, params))
        return {"id": "exchange-1", "filled": qty, "average": 50000, "status": "closed"}

    def fetch_positions(self, symbols=None):
        return self.positions


class P0IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.old = dict(bot.CONFIG)
        bot.CONFIG["paper_trading"] = False
        bot.CONFIG["market"] = "future"
        bot.CONFIG["leverage"] = 5

    def tearDown(self):
        bot.CONFIG.clear()
        bot.CONFIG.update(self.old)

    def test_entry_uses_contracts_not_base_quantity(self):
        ex = FakeFutureExchange([])
        with self.assertRaises(Exception):
            # setup calls are intentionally absent: this proves the quantity conversion
            bot.place_order(ex, "BTC/USDT", "long", 20, 50000)
        self.assertEqual(ex.created, [])

    def test_close_does_not_claim_flat_from_empty_snapshot(self):
        ex = FakeFutureExchange([])
        pos = {"side": "long", "qty": 2, "entry": 50000}
        with self.assertRaises(Exception):
            bot.close_live_position(ex, "BTC/USDT", pos, 50000)

    def test_explicit_zero_matching_position_proves_flat(self):
        ex = FakeFutureExchange([{"symbol": "BTC/USDT", "contracts": 0}])
        pos = {"side": "long", "qty": 2, "entry": 50000}
        result = bot.close_live_position(ex, "BTC/USDT", pos, 50000)
        self.assertTrue(result["by_exchange"])

    def test_hedge_mode_selects_exact_position_leg(self):
        ex = FakeFutureExchange([
            {"symbol": "BTC/USDT", "contracts": 2, "positionIdx": 1, "side": "long"},
            {"symbol": "BTC/USDT", "contracts": 3, "positionIdx": 2, "side": "short"},
        ])
        ex.options = {"hedgeMode": True}
        self.assertEqual(bot._exchange_position_qty(ex, "BTC/USDT", side="long"), 2.0)
        self.assertEqual(bot._exchange_position_qty(ex, "BTC/USDT", side="short"), 3.0)

    def test_futures_missing_contract_metadata_fails_closed(self):
        ex = FakeFutureExchange([])
        ex.market = lambda symbol: {"symbol": symbol, "contract": True, "linear": False, "inverse": False, "contractSize": 1.0}
        with self.assertRaises(RuntimeError):
            bot.place_order(ex, "BTC/USDT", "long", 20, 50000)

    def test_empty_snapshot_blocks_nontrend_entry(self):
        bot._ENTRY_BLOCK["reason"] = "exchange position snapshot is empty or incomplete"
        state = {"positions": {}, "last_trade": {}, "stats": {"trades": 0, "wins": 0, "losses": 0, "pnl": 0}, "history": [], "recovery_required": {}}
        ex = Mock()
        bot.CONFIG["paper_trading"] = False
        bot.try_enter("BTC/USDT", {"total": 0.9, "price": 50000, "amount_mult": 1}, state, ex)
        ex.create_order.assert_not_called()
        bot._ENTRY_BLOCK["reason"] = ""

    def test_reconcile_empty_snapshot_blocks_entries(self):
        ex = FakeFutureExchange([])
        state = {"positions": {}, "last_trade": {}, "stats": {"trades": 0, "wins": 0, "losses": 0, "pnl": 0}, "history": [], "recovery_required": {}}
        bot.reconcile_live(state, ex)
        self.assertTrue(bot._ENTRY_BLOCK["reason"])
        bot._ENTRY_BLOCK["reason"] = ""

    def test_edit_order_without_readback_verification_is_not_success(self):
        ex = Mock()
        ex.id = "binance"
        ex.edit_order.return_value = {"id": "old-sl", "status": "open"}
        ex.fetch_order.return_value = {"id": "old-sl", "status": "open", "stopLossPrice": 49000}
        bot.CONFIG["paper_trading"] = False
        pos = {"side": "long", "qty": 1, "sl": 49000, "oco_ids": {"sl": "old-sl"}}
        self.assertFalse(bot._amend_exchange_sl("BTC/USDT", pos, 50000, 49000, ex))



if __name__ == "__main__":
    unittest.main()
