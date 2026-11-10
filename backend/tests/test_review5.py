"""Short review of #31/#32 (2026-10-30): a retried basket exit kept an execution mark that blocked entries for good;
a held leg's ratio pair was dropped; leg-form history broke the ratio status; post-fill recovery alerted wrongly;
two live bots on one IPC folder; group changes without restarts."""
import json, os, sys, tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_full_review_code as base
from test_live_momentum_ls import MomentumFakeBinance
botmod = base.botmod
VPS = Path(__file__).resolve().parent.parent.parent / "deploy" / "vps"


class Flaky(MomentumFakeBinance):
    fail = 0
    def fetch_positions(self, syms=None):
        if self.fail and syms and syms[0].startswith("S16/"):
            self.fail -= 1; raise Exception("timeout")
        return super().fetch_positions(syms)


class BasketExitTests(base.BasketTests):
    def exit_leg(self, st, sym):
        pos = st["positions"][sym]
        return [{"symbol": sym, "side": "close_" + pos["side"], "action": "exit", "position": pos, "price": 1.0, "order": 0,
                 "risk_usdt": 0, "notional_usdt": 0, "correlation_group": None}]

    def test_retried_exit_leaves_no_mark_behind(self):
        ex = Flaky(); self.run_momentum(ex)
        st = botmod.load_state(); sym = next(k for k in st["positions"] if k.startswith("S16"))
        ex.fail = 1
        self.assertEqual(botmod._phase2_live_basket(ex, st, "momentum_ls", "single-exit", self.exit_leg(st, sym), reserve=False)["status"], "exit_retry")
        botmod._ENTRY_BLOCK["reason"] = ""
        self.assertEqual(botmod._phase2_live_basket(ex, st, "momentum_ls", "single-exit", self.exit_leg(st, sym), reserve=False)["status"], "filled")
        botmod._phase2_live_basket(ex, st, "momentum_ls", "another-exit", self.exit_leg(st, next(iter(st["positions"]))), reserve=False)
        self.assertFalse(st.get("recovery_required"))

    def test_basket_with_a_held_leg_is_not_reported_filled(self):
        ex = MomentumFakeBinance(); self.run_momentum(ex)
        st = botmod.load_state(); a, b = sorted(st["positions"])[:2]
        st.setdefault("recovery_required", {})[a] = {"reason": "size mismatch"}
        legs = self.exit_leg(st, a) + self.exit_leg(st, b)
        res = botmod._phase2_live_basket(ex, st, "momentum_ls", "pair-exit", legs, reserve=False)
        self.assertEqual(res["status"], "held"); self.assertEqual(res["held"], [a])
        self.assertIn(a, st["positions"]); self.assertNotIn(b, st["positions"])


class StatusWriterTests(unittest.TestCase):
    def test_ratio_and_listing_status_take_leg_rows_and_unknown_pnl(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d, mock.patch.dict(botmod.CONFIG, {"public_dir": d}):
            leg = {"symbol": "AAA/USDT:USDT", "side": "long", "entry": 1, "exit": 2, "qty": 1, "pnl": None, "reason": "x", "type": "live"}
            botmod.write_ratio_status({"pairs": {}, "history": [leg], "stats": {}}, {})
            self.assertEqual(json.loads((Path(d) / "ratio.json").read_text(encoding="utf-8"))["history"][0]["pair"], "AAA/USDT")
            botmod.write_listing_status({"positions": {}, "history": [leg], "stats": {}}, {}, [])
            self.assertIsNone(json.loads((Path(d) / "listing.json").read_text(encoding="utf-8"))["history"][0]["pnl"])


class SharedIpcTests(unittest.TestCase):
    def test_a_bot_leaves_another_live_bots_status_and_requests_alone(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d, mock.patch.dict(os.environ, {"RAQM_IPC_DIR": d}), \
             mock.patch.dict(botmod.CONFIG, {"enabled_strategies": ["vol_breakout"]}):
            (Path(d) / "commands").mkdir(); (Path(d) / "results").mkdir()
            (Path(d) / "live_status.json").write_text(json.dumps({"updated": datetime.now(timezone.utc).isoformat(), "strategy": "trend_daily"}))
            req = Path(d) / "commands" / ("close-" + "a" * 32 + ".json")
            req.write_text(json.dumps({"id": "a" * 32, "symbol": "BTC/USDT", "at_epoch": __import__("time").time()}))
            botmod.process_manual_closes({"positions": {}}, None, {})
            self.assertTrue(req.exists())                                   # the trend bot's request, not ours
            botmod.write_live_status({"positions": {}, "history": []}, {})
            self.assertEqual(json.loads((Path(d) / "live_status.json").read_text())["strategy"], "trend_daily")


class RestartTests(unittest.TestCase):
    def test_group_changes_restart_the_services(self):
        live = (VPS / "setup-live.sh").read_text(encoding="utf-8")
        self.assertIn("systemctl try-restart raqm-api ", live); self.assertNotIn("try-restart raqm-api raqm-", live)   # live bots: by hand
        self.assertIn("systemctl try-restart raqm-api raqm-bot", (VPS / "setup-paper-ipc.sh").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()


class WhyNoTradeTests(unittest.TestCase):
    """Owner (2026-10-30): the admin page says why a strategy isn't trading — its last refusal, or nothing blocking."""
    def test_the_last_refusal_reaches_the_admin_page(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d, mock.patch.dict(os.environ, {"RAQM_IPC_DIR": d}), \
             mock.patch.dict(botmod.CONFIG, {"enabled_strategies": ["vol_breakout"]}), mock.patch.object(botmod, "LOG_PATH", Path(d) / "l.log"):
            botmod._LAST_BLOCK.clear()
            botmod.log("📊 بريك أوت: 0 مفتوحة")                                    # not a refusal
            botmod.write_live_status({"positions": {}, "history": []}, {})
            self.assertIsNone(json.loads((Path(d) / "live_status.json").read_text(encoding="utf-8"))["last_block"])
            botmod.log("⛔ SOL/USDT:USDT رفض بوابة المخاطر المركزية — per-trade risk 1.6% exceeds limit 1%")
            botmod.write_live_status({"positions": {}, "history": []}, {})
            last = json.loads((Path(d) / "live_status.json").read_text(encoding="utf-8"))["last_block"]
            self.assertTrue(last["reason"].startswith("SOL/USDT:USDT رفض")); self.assertTrue(last["at"])


class EquityRetryTests(unittest.TestCase):
    """One dropped balance request no longer blocks a bot's entries for the whole cycle (22 times in a day on Demo)."""
    def test_a_dropped_request_is_tried_once_more(self):
        ex = mock.Mock(); ex.fetch_balance.side_effect = [OSError("Connection reset"), {"USDT": {"total": 5000.0}}]
        with mock.patch.object(botmod.time, "sleep") as sl:
            self.assertEqual(botmod._fetch_equity_usdt(ex), 5000.0)
        sl.assert_called_once_with(2)

    def test_two_failures_still_fail_closed_and_say_why(self):
        ex = mock.Mock(); ex.fetch_balance.side_effect = OSError("Connection reset")
        with mock.patch.object(botmod.time, "sleep"), mock.patch.object(botmod, "log") as lg:
            self.assertIsNone(botmod._fetch_equity_usdt(ex))
        self.assertEqual(ex.fetch_balance.call_count, 2); self.assertIn("Connection reset", lg.call_args[0][0])

    def test_a_zero_balance_is_not_retried(self):
        ex = mock.Mock(); ex.fetch_balance.return_value = {"USDT": {"total": 0}}
        self.assertIsNone(botmod._fetch_equity_usdt(ex)); self.assertEqual(ex.fetch_balance.call_count, 1)


class LiveStatusPositionTests(unittest.TestCase):
    """The admin page showed shorts as LONG (no side in the status) and "—" for every open trade's profit (fee and
    funding not verified while it is open)."""
    def test_side_and_an_estimated_profit_reach_the_page(self):
        state = {"positions": {
            "ETH/USDT:USDT": {"side": "short", "entry": 2000.0, "qty": 0.1, "contract_size": 1.0, "contract_size_verified": True,
                              "entry_fee_rate": 0.0004, "sl": 2800.0, "time": "2026-10-31T00:00:00+00:00"},
            "BTC/USDT:USDT": {"side": "long", "entry": 100.0, "qty": 1.0, "contract_size": 1.0, "contract_size_verified": True,
                              "entry_fee_rate": 0.0004, "fee_verified": True, "fee_rate": 0.0004, "funding_verified": True, "funding_pnl": -1.0,
                              "sl": 60.0, "time": "2026-10-31T00:00:00+00:00"}}, "history": []}
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d, mock.patch.dict(os.environ, {"RAQM_IPC_DIR": d}), \
             mock.patch.dict(botmod.CONFIG, {"enabled_strategies": ["ratio_trend"]}):
            botmod.write_live_status(state, {"ETH/USDT:USDT": 1900.0, "BTC/USDT:USDT": 110.0})
            pos = {p["symbol"]: p for p in json.loads((Path(d) / "live_status.json").read_text(encoding="utf-8"))["positions"]}
        eth, btc = pos["ETH/USDT"], pos["BTC/USDT"]
        self.assertEqual((eth["side"], eth["pnl_estimated"]), ("short", True))
        self.assertAlmostEqual(eth["pnl"], 10.0 - (200.0 + 190.0) * 0.0004, places=4)       # a short gains as price falls
        self.assertAlmostEqual(eth["loss_at_sl"], -80.0 - (200.0 + 280.0) * 0.0004, places=2)
        self.assertEqual((btc["side"], btc["pnl_estimated"]), ("long", False))
        self.assertAlmostEqual(btc["pnl"], 10.0 - 210.0 * 0.0004 - 1.0, places=4)            # verified: funding counted
