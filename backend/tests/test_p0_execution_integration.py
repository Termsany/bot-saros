import unittest
from unittest.mock import Mock

import bot


class FakeFutureExchange:
    id = "binance"
    options = {}

    def __init__(self, positions):
        self.positions = positions
        self.created = []
        self.set_leverage = lambda *args, **kwargs: None
        self.set_margin_mode = lambda *args, **kwargs: None
        self.set_position_mode = lambda *args, **kwargs: None

    def market(self, symbol):
        return {"contract": True, "linear": True, "inverse": False, "contractSize": 0.001}

    def amount_to_precision(self, symbol, qty):
        return str(qty)

    def create_order(self, symbol, kind, side, qty, price, params):
        self.created.append((symbol, side, qty, params))
        return {"id": "exchange-1", "filled": qty, "average": 50000, "status": "closed", "fee": {"cost": abs(float(qty)) * 50000 * 0.0004}}

    def fetch_positions(self, symbols=None):
        return self.positions

    def fetch_funding_history(self, symbol, since=None):
        return []


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
        result = bot.place_order(ex, "BTC/USDT", "long", 20, 50000)
        self.assertEqual(len(ex.created), 1)
        self.assertEqual(ex.created[0][2], 2.0)
        self.assertEqual(result["qty"], 2.0)
        self.assertEqual(result["contract_size"], 0.001)

    def test_entry_contract_quantity_changes_with_leverage_and_contract_size(self):
        ex = FakeFutureExchange([])
        ex.market = lambda symbol: {"contract": True, "linear": True, "inverse": False, "contractSize": 0.01}
        bot.CONFIG["leverage"] = 3
        bot.place_order(ex, "BTC/USDT", "long", 20, 50000)
        self.assertAlmostEqual(ex.created[0][2], 0.12)

    def test_partial_close_fill_is_not_verified(self):
        ex = FakeFutureExchange([{"symbol": "BTC/USDT", "contracts": 2}])
        ex.create_order = lambda *args: {"id": "partial", "filled": 1.0, "average": 50000, "fee": {"cost": 0.02}}
        reads = iter([[{"symbol": "BTC/USDT", "contracts": 2}], [{"symbol": "BTC/USDT", "contracts": 0}]])
        ex.fetch_positions = lambda symbols=None: next(reads)
        pos = {"side": "long", "qty": 2, "entry": 50000, "contract_size": 0.001, "contract_size_verified": True, "entry_fee_rate": 0.0004}
        res = bot.close_live_position(ex, "BTC/USDT", pos, 50000)
        self.assertFalse(res["accounting_verified"])
        self.assertTrue(res["recovery_required"])
        with self.assertRaises(RuntimeError):
            bot._require_verified_close(res)

    def test_close_does_not_claim_flat_from_empty_snapshot(self):
        ex = FakeFutureExchange([])
        pos = {"side": "long", "qty": 2, "entry": 50000}
        res = bot.close_live_position(ex, "BTC/USDT", pos, 50000)
        self.assertFalse(res["accounting_verified"])
        self.assertTrue(res["recovery_required"])
        with self.assertRaises(Exception):
            bot._require_verified_close(res)

    def test_explicit_zero_matching_position_proves_flat(self):
        ex = FakeFutureExchange([{"symbol": "BTC/USDT", "contracts": 0}])
        pos = {"side": "long", "qty": 2, "entry": 50000}
        result = bot.close_live_position(ex, "BTC/USDT", pos, 50000)
        self.assertTrue(result["by_exchange"])
        self.assertFalse(result["accounting_verified"])
        self.assertEqual(result["price"], None)

    def test_verified_close_returns_explicit_accounting_flag(self):
        ex = FakeFutureExchange([{"symbol": "BTC/USDT", "contracts": 2}])
        reads = iter([[{"symbol": "BTC/USDT", "contracts": 2}], [{"symbol": "BTC/USDT", "contracts": 0}]])
        ex.fetch_positions = lambda symbols=None: next(reads)
        pos = {"side": "long", "qty": 2, "entry": 50000, "contract_size": 0.001, "contract_size_verified": True, "entry_fee_rate": 0.0004}
        result = bot.close_live_position(ex, "BTC/USDT", pos, 50000)
        self.assertTrue(result["accounting_verified"])
        self.assertTrue(result["by_exchange"] is False)

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
