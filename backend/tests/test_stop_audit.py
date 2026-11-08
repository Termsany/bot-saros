"""Hourly stop check (owner, 2026-11-08): a recorded stop that is gone from the exchange (cancelled by hand, dropped)
is caught on two readings in a row, blocks new entries and alerts; the bot places and cancels nothing for it."""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bot as botmod
from backend.app import risk_manager as riskmgr_mod
from test_trend_live import FakeBinance

SYM = "SOL/USDT:USDT"


class StopAuditTests(unittest.TestCase):
    def setUp(self):
        self._cfg = dict(botmod.CONFIG)
        self._env = os.environ.get("BINANCE_ENV")
        os.environ["BINANCE_ENV"] = "demo"
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._paths = (botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH)
        botmod.STATE_PATH = Path(self.td.name) / "state.json"; botmod.LOG_PATH = Path(self.td.name) / "t.log"
        botmod.RISK_PATH = Path(self.td.name) / "risk_state.json"
        riskmgr_mod.save_risk_state(botmod.RISK_PATH, riskmgr_mod._default_state({
            "risk_per_trade_pct": 100.0, "max_aggregate_risk_pct": 100.0,
            "max_correlated_risk_pct": 100.0, "max_daily_loss_pct": 100.0, "max_drawdown_pct": 100.0,
        }))
        botmod.CONFIG.update({"paper_trading": False, "market": "future", "leverage": 2, "trade_amount_usdt": 100,
                              "enabled_strategies": ["rsi2_pullback"], "max_open_positions": 10})
        botmod._ENTRY_BLOCK["reason"] = ""
        self.state = botmod.load_state()
        self.sent = []
        self._notify = mock.patch.object(botmod, "notify", side_effect=self.sent.append); self._notify.start()
        self.ex = FakeBinance()
        margin = botmod.position_size(100.0, self.ex) * 2
        self.assertIsNotNone(botmod._single_leg_live_entry(self.ex, self.state, SYM, "long", margin, 100.0, 60.0, None,
                                                           "rsi2_pullback", {"exit_at": "2099-01-01T00:00:00+00:00"}))
        self.sent.clear()
        self.t0 = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)

    def tearDown(self):
        self._notify.stop()
        botmod.CONFIG.clear(); botmod.CONFIG.update(self._cfg)
        if self._env is None: os.environ.pop("BINANCE_ENV", None)
        else: os.environ["BINANCE_ENV"] = self._env
        botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH = self._paths
        self.td.cleanup()

    def audit(self, minutes=0):
        live = {SYM.split(":")[0]: self.state["positions"][SYM]["qty"]}
        botmod._audit_stops(self.ex, self.state, live, now=self.t0 + timedelta(minutes=minutes))

    def cancel_stop_by_hand(self):
        sl = self.state["positions"][SYM]["oco_ids"]["sl"]
        self.ex.cancelled.append(sl if str(sl).startswith("stop-") else "stop-" + sl)

    def test_a_stop_in_place_changes_nothing_and_waits_an_hour(self):
        self.audit()
        pos = self.state["positions"][SYM]
        self.assertFalse(pos.get("sl_unverified")); self.assertEqual(self.sent, [])
        with mock.patch("backend.app.oco._owned_orders") as owned:
            self.audit(minutes=30)
            owned.assert_not_called()                      # checked at most once an hour
            owned.return_value = ({"x": {}}, True)
            self.audit(minutes=61)
            owned.assert_called_once()

    def test_a_stop_cancelled_by_hand_is_caught_on_the_second_reading(self):
        orders_before = len(self.ex.orders)
        self.audit()
        self.cancel_stop_by_hand()
        self.audit(minutes=60)                             # first miss: not believed yet
        self.assertFalse(self.state["positions"][SYM].get("sl_unverified")); self.assertEqual(self.sent, [])
        self.audit(minutes=61)                             # the next cycle reads again
        pos = self.state["positions"][SYM]
        self.assertTrue(pos["sl_unverified"]); self.assertTrue(pos["stop_audit_missing"])
        self.assertEqual(self.state["recovery_required"][SYM]["reason"], botmod.AUDIT_REASON)
        self.assertEqual(len(self.sent), 1); self.assertIn("وقف الخسارة مش موجود", self.sent[0])
        self.assertEqual(len(self.ex.orders), orders_before)   # nothing placed
        self.audit(minutes=62); self.audit(minutes=130)
        self.assertEqual(len(self.sent), 1)                # said once
        self.assertTrue(botmod.load_state()["positions"][SYM]["sl_unverified"])   # saved

    def test_an_inconclusive_read_is_not_a_miss(self):
        self.audit()
        with mock.patch("backend.app.oco._owned_orders", return_value=({}, False)):
            self.audit(minutes=60); self.audit(minutes=61); self.audit(minutes=62)
        self.assertFalse(self.state["positions"][SYM].get("sl_unverified")); self.assertEqual(self.sent, [])

    def test_the_stop_seen_again_clears_only_its_own_mark(self):
        self.audit(); self.cancel_stop_by_hand(); self.audit(minutes=60); self.audit(minutes=61)
        self.ex.cancelled.clear()                          # the owner put it back
        self.audit(minutes=125)
        pos = self.state["positions"][SYM]
        self.assertFalse(pos.get("sl_unverified")); self.assertNotIn("stop_audit_missing", pos)
        self.assertNotIn(SYM, self.state.get("recovery_required") or {})
        self.assertIn("رجع ظاهر", self.sent[-1])

    def test_a_position_the_stop_machinery_already_flagged_is_left_to_it(self):
        self.state["positions"][SYM]["sl_unverified"] = True
        with mock.patch("backend.app.oco._owned_orders") as owned:
            self.audit()
            owned.assert_not_called()
        self.assertNotIn("stop_audit_missing", self.state["positions"][SYM])

    def test_reconcile_live_runs_it_and_blocks_entries(self):
        botmod.reconcile_live(self.state, self.ex)
        self.cancel_stop_by_hand()
        self.state["_stop_audit"]["at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        botmod.reconcile_live(self.state, self.ex); botmod.reconcile_live(self.state, self.ex)
        self.assertTrue(self.state["positions"][SYM].get("stop_audit_missing"))
        pos2 = botmod._single_leg_live_entry(self.ex, self.state, "ETH/USDT:USDT", "long", 100.0, 50.0, 30.0, None, "rsi2_pullback")
        self.assertIsNone(pos2)


if __name__ == "__main__":
    unittest.main()
