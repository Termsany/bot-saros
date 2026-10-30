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
