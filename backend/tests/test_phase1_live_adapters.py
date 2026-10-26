import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import bot
from backend.app import risk_manager as riskmgr


class Phase1LiveAdapterTests(unittest.TestCase):
    def setUp(self):
        self.old_cfg = dict(bot.CONFIG)
        self.old_risk = bot.RISK_PATH
        self.old_state = bot.STATE_PATH
        self.old_block = dict(bot._ENTRY_BLOCK)
        self.td = tempfile.TemporaryDirectory()
        bot.RISK_PATH = Path(self.td.name) / "risk.json"
        bot.STATE_PATH = Path(self.td.name) / "state.json"
        bot.CONFIG.update({"paper_trading": False, "market": "future", "leverage": 2})
        bot._ENTRY_BLOCK["reason"] = ""
        self.env = {k: os.environ.get(k) for k in ("ALLOW_LIVE_TRADING", "BINANCE_ENV")}
        os.environ["ALLOW_LIVE_TRADING"] = "true"
        os.environ["BINANCE_ENV"] = "demo"

    def tearDown(self):
        bot.CONFIG.clear(); bot.CONFIG.update(self.old_cfg)
        bot.RISK_PATH = self.old_risk
        bot.STATE_PATH = self.old_state
        bot._ENTRY_BLOCK.clear(); bot._ENTRY_BLOCK.update(self.old_block)
        for key, value in self.env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.td.cleanup()

    def state(self):
        return {"positions": {}, "last_trade": {}, "stats": {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0},
                "history": [], "recovery_required": {}, "pending_orders": {}}

    def test_shared_entry_routes_risk_order_and_verified_protection(self):
        state = self.state()
        with mock.patch.object(bot, "_fetch_equity_usdt", return_value=1000.0), \
             mock.patch.object(bot.riskmgr, "update_equity_and_check_kill_switch", return_value=(False, None)), \
             mock.patch.object(bot.riskmgr, "pre_trade_gate", return_value=(True, None)), \
             mock.patch.object(bot, "place_order", return_value={"id": "e1", "qty": 1.0, "price": 100.0, "cost": 100.0,
                 "contract_size": 1.0, "contract_size_verified": True, "entry_fee_rate": 0.0004, "entry_fee_cost": 0.04}), \
             mock.patch("backend.app.oco.place_oco_orders", return_value={"sl_id": "sl1", "tp_id": "tp1"}) as oco, \
             mock.patch.object(bot.riskmgr, "register_open_risk"):
            pos = bot._single_leg_live_entry(mock.Mock(), state, "BTC/USDT", "long", 100.0, 100.0, 90.0, 110.0, "vol_breakout")
        self.assertIsNotNone(pos)
        self.assertIn("BTC/USDT", state["positions"])
        self.assertEqual(state["positions"]["BTC/USDT"]["oco_ids"]["sl"], "sl1")
        oco.assert_called_once()

    def test_protection_failure_persists_recovery_and_blocks(self):
        state = self.state()
        with mock.patch.object(bot, "_fetch_equity_usdt", return_value=1000.0), \
             mock.patch.object(bot.riskmgr, "update_equity_and_check_kill_switch", return_value=(False, None)), \
             mock.patch.object(bot.riskmgr, "pre_trade_gate", return_value=(True, None)), \
             mock.patch.object(bot, "place_order", return_value={"id": "e1", "qty": 1.0, "price": 100.0, "cost": 100.0,
                 "contract_size": 1.0, "contract_size_verified": True}), \
             mock.patch("backend.app.oco.place_oco_orders", return_value={"protection_missing": True}), \
             mock.patch.object(bot, "close_live_position", return_value={"accounting_verified": False}), \
             mock.patch.object(bot.riskmgr, "register_open_risk"):
            self.assertIsNone(bot._single_leg_live_entry(mock.Mock(), state, "BTC/USDT", "long", 100.0, 100.0, 90.0, 110.0, "vol_breakout"))
        self.assertIn("BTC/USDT", state["recovery_required"])
        self.assertTrue(bot._ENTRY_BLOCK["reason"])

    def test_ambiguous_entry_persists_recovery_and_risk_status(self):
        state = self.state()
        with mock.patch.object(bot, "_fetch_equity_usdt", return_value=1000.0), \
             mock.patch.object(bot.riskmgr, "update_equity_and_check_kill_switch", return_value=(False, None)), \
             mock.patch.object(bot.riskmgr, "pre_trade_gate", return_value=(True, None)), \
             mock.patch.object(bot, "place_order", side_effect=TimeoutError("network timeout")), \
             mock.patch.object(bot, "_exchange_position_qty", return_value=None), \
             mock.patch.object(bot.riskmgr, "mark_reservation_recovery") as recover:
            self.assertIsNone(bot._single_leg_live_entry(mock.Mock(), state, "BTC/USDT", "long", 100.0, 100.0, 90.0, 110.0, "vol_breakout"))
        recover.assert_called_once()
        self.assertIn("BTC/USDT", state["recovery_required"])
        self.assertNotIn("BTC/USDT", state["pending_orders"])

    def test_verified_exit_records_history_and_removes_position(self):
        state = self.state()
        state["positions"]["BTC/USDT"] = {"side": "long", "entry": 100.0, "qty": 1.0, "contract_size": 1.0,
            "contract_size_verified": True, "entry_fee_rate": 0.0004, "entry_fee_cost": 0.04, "strategy": "vol_breakout"}
        result = {"accounting_verified": True, "price": 110.0, "qty": 1.0}
        with mock.patch.object(bot, "close_live_position", return_value=result), \
             mock.patch.object(bot, "_position_contract_size", return_value=1.0), \
             mock.patch.object(bot, "_fee_rate", return_value=0.0004), \
             mock.patch.object(bot, "_funding_pnl", return_value=0.0), \
             mock.patch.object(bot.riskmgr, "release_open_risk"):
            self.assertTrue(bot._single_leg_live_exit(mock.Mock(), state, "BTC/USDT", 110.0, "target"))
        self.assertNotIn("BTC/USDT", state["positions"])
        self.assertEqual(state["history"][-1]["type"], "live")

    def test_ambiguous_exit_keeps_position_and_requires_recovery(self):
        state = self.state()
        state["positions"]["BTC/USDT"] = {"side": "long", "entry": 100.0, "qty": 1.0}
        with mock.patch.object(bot, "close_live_position", return_value={"accounting_verified": False, "error": "unknown"}):
            self.assertFalse(bot._single_leg_live_exit(mock.Mock(), state, "BTC/USDT", 90.0, "stop"))
        self.assertIn("BTC/USDT", state["positions"])
        self.assertIn("BTC/USDT", state["recovery_required"])

    def test_kill_switch_blocks_entry_before_order(self):
        state = self.state()
        with mock.patch.object(bot, "_fetch_equity_usdt", return_value=1000.0), \
             mock.patch.object(bot.riskmgr, "update_equity_and_check_kill_switch", return_value=(True, "manual")), \
             mock.patch.object(bot, "place_order") as order:
            self.assertIsNone(bot._single_leg_live_entry(mock.Mock(), state, "BTC/USDT", "long", 100.0, 100.0, 90.0, 110.0, "vol_breakout"))
        order.assert_not_called()
        self.assertIn("kill switch", bot._ENTRY_BLOCK["reason"])

    def test_restart_state_keeps_recovery_and_blocks_new_entry(self):
        state = self.state()
        state["recovery_required"]["BTC/USDT"] = {"reason": "ambiguous", "at": "now"}
        with mock.patch.object(bot, "_fetch_equity_usdt") as equity, mock.patch.object(bot, "place_order") as order:
            self.assertIsNone(bot._single_leg_live_entry(mock.Mock(), state, "ETH/USDT", "long", 100.0, 100.0, 90.0, 110.0, "rsi2_pullback"))
        equity.assert_not_called(); order.assert_not_called()

    def test_live_adapter_is_disabled_without_explicit_gate(self):
        os.environ["ALLOW_LIVE_TRADING"] = "false"
        with mock.patch.object(bot, "place_order") as order:
            self.assertIsNone(bot._single_leg_live_entry(mock.Mock(), self.state(), "BTC/USDT", "long", 100.0, 100.0, 90.0, 110.0, "vol_breakout"))
        order.assert_not_called()


if __name__ == "__main__":
    unittest.main()
