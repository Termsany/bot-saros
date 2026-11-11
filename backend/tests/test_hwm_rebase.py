"""The owner's high-water-mark rebase (2026-11-11; risk_manager.rebase_high_water_mark, deploy/vps/tools/rebase_hwm.py).
Money withdrawn before the transfer watermark existed read as an 81% drawdown on the main account; the kill switch
tripped and resetting it alone would trip it again at the next cycle. The rebase moves the high-water mark to the
equity the bot last read — only that figure, only a fresh one — and leaves the kill switch to its own step."""
import os, subprocess, sys, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from backend.app import risk_manager as rm


class RebaseTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(); self.dir = Path(self.td.name); self.p = self.dir / "risk_state.json"
        rm.save_risk_state(self.p, rm._default_state({"max_drawdown_pct": 45.0, "max_daily_loss_pct": 20.0}))
        # the main account on 2026-11-09: a high of $1,925, then $358 after the owner's withdrawals -> 81% "drawdown"
        now = datetime.now(timezone.utc).isoformat()
        rm.update_equity_and_check_kill_switch(self.p, 1925.0, equity_observed_at=now)
        self.tripped, self.reason = rm.update_equity_and_check_kill_switch(self.p, 358.0, equity_observed_at=now)

    def tearDown(self):
        self.td.cleanup()

    def test_the_withdrawal_trips_and_a_reset_alone_trips_again(self):
        self.assertTrue(self.tripped); self.assertIn("drawdown 81.4", self.reason)
        rm.reset_kill_switch(self.p, operator="owner")
        tripped, _ = rm.update_equity_and_check_kill_switch(self.p, 358.0, equity_observed_at=datetime.now(timezone.utc).isoformat())
        self.assertTrue(tripped)                                     # why the rebase is needed

    def test_a_rebase_then_a_reset_keeps_the_switch_clear_and_records_who(self):
        old, new = rm.rebase_high_water_mark(self.p, equity_usdt=358.5, operator="Owner")   # what the dashboard showed
        self.assertEqual((old, new), (1925.0, 358.5))
        s = rm.load_risk_state(self.p)
        self.assertTrue(s["kill_switch"]["tripped"])                  # untouched: its own step
        self.assertEqual((s["equity_high_water_mark"], s["daily"]["start_equity"]), (358.5, 358.5))
        self.assertEqual((s["hwm_rebases"][-1]["by"], s["hwm_rebases"][-1]["from"], s["hwm_rebases"][-1]["to"]), ("Owner", 1925.0, 358.5))
        rm.reset_kill_switch(self.p, operator="owner")
        tripped, reason = rm.update_equity_and_check_kill_switch(self.p, 355.0, equity_observed_at=datetime.now(timezone.utc).isoformat())
        self.assertFalse(tripped, reason)                            # a $3 move is no longer an 81% drawdown

    def test_a_figure_the_bot_did_not_read_is_refused(self):
        with self.assertRaisesRegex(ValueError, "not the equity the bot last read"):
            rm.rebase_high_water_mark(self.p, equity_usdt=1900, operator="Owner")    # the old high, typed by mistake
        self.assertEqual(rm.load_risk_state(self.p)["equity_high_water_mark"], 1925.0)   # nothing written

    def test_a_stale_reading_is_refused(self):
        later = datetime.now(timezone.utc) + timedelta(seconds=rm.REBASE_MAX_AGE_S + 60)
        with self.assertRaisesRegex(ValueError, "s old"):
            rm.rebase_high_water_mark(self.p, equity_usdt=358, operator="Owner", now=later)

    def test_no_reading_no_operator_or_a_bad_number_is_refused(self):
        empty = self.dir / "empty"; empty.mkdir(); rm.save_risk_state(empty / "risk_state.json", rm._default_state())
        with self.assertRaisesRegex(ValueError, "no equity reading"):
            rm.rebase_high_water_mark(empty / "risk_state.json", equity_usdt=358, operator="Owner")
        for eq, op in ((358, " "), (0, "Owner"), (float("nan"), "Owner"), ("x", "Owner")):
            with self.assertRaises(ValueError): rm.rebase_high_water_mark(self.p, equity_usdt=eq, operator=op)

    def test_the_audit_keeps_the_last_ones(self):
        for _ in range(rm.HWM_REBASES_KEPT + 3):
            rm.rebase_high_water_mark(self.p, equity_usdt=358, operator="Owner")
        self.assertEqual(len(rm.load_risk_state(self.p)["hwm_rebases"]), rm.HWM_REBASES_KEPT)

    def test_the_tool_shows_then_writes_and_never_resets_the_switch(self):
        tool = ROOT / "deploy" / "vps" / "tools" / "rebase_hwm.py"
        run = lambda *a: subprocess.run([sys.executable, str(tool), str(self.dir), *a], capture_output=True, text=True,
                                        encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        r = run("358", "Owner", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr); self.assertIn("drawdown now:      81.40%", r.stdout); self.assertIn("nothing written", r.stdout)
        self.assertEqual(rm.load_risk_state(self.p)["equity_high_water_mark"], 1925.0)
        r = run("1900", "Owner")
        self.assertNotEqual(r.returncode, 0); self.assertIn("refused, nothing written", r.stderr)
        r = run("358", "Owner")
        self.assertEqual(r.returncode, 0, r.stderr); self.assertIn("1925.0 -> 358.0", r.stdout)
        self.assertTrue(rm.load_risk_state(self.p)["kill_switch"]["tripped"])

    def test_setup_live_installs_it_and_deploy_checks_it(self):
        self.assertIn('"$T/deploy/vps/tools/rebase_hwm.py" /usr/local/lib/raqm/rebase_hwm.py', (ROOT / "deploy" / "vps" / "setup-live.sh").read_text(encoding="utf-8"))
        self.assertIn("rebase_hwm.py", (ROOT / "deploy" / "vps" / "deploy.sh").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
