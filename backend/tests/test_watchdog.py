"""Problem alerts (scripts/watchdog.py, owner 2026-10-30): one message when a problem starts, one when it clears."""
import json, sys, tempfile, unittest
from unittest import mock
from datetime import datetime, timedelta, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
import watchdog as wd
from backend.app import risk_manager as rm

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); d = Path(self.td.name)
        self.ipc, self.ledgers = d / "ipc", {"demo": d / "risk-demo", "live": d / "risk"}
        rm.save_risk_state(self.ledgers["demo"] / "risk_state.json", rm._default_state())
        self.units = {("demo", s): (True, True) for s in wd.STRATEGIES}
        for s in wd.STRATEGIES: self.status(s)
    def tearDown(self): self.td.cleanup()

    def status(self, s, **kw):
        (self.ipc / s).mkdir(parents=True, exist_ok=True)
        st = {"updated": NOW.isoformat(), "env": "demo", "positions": [], "review": {}, "entry_block": "", **kw}
        (self.ipc / s / "live_status.json").write_text(json.dumps(st), encoding="utf-8")

    def seen(self):
        return wd.problems(NOW, unit=lambda env, s: self.units.get((env, s), (False, False)), ipc=self.ipc, ledgers=self.ledgers)

    def test_healthy_bots_send_nothing(self):
        self.assertEqual(self.seen(), {})

    def test_each_problem_is_found(self):
        self.units[("demo", "ratio_trend")] = (True, False)
        self.status("trend_daily", updated=(NOW - timedelta(minutes=12)).isoformat())
        self.status("rsi2_pullback", positions=[{"symbol": "SOL/USDT", "unprotected": True}])
        self.status("momentum_ls", review={"BTC/USDT:USDT": {"reason": "entry outcome unknown"}})
        self.status("vol_breakout", entry_block="unknown position on the account: XRP/USDT")
        rm.update_limits(self.ledgers["demo"] / "risk_state.json", {})
        st = rm.load_risk_state(self.ledgers["demo"] / "risk_state.json"); st["kill_switch"] = {"tripped": True, "reason": "drawdown 31%"}
        rm.save_risk_state(self.ledgers["demo"] / "risk_state.json", st)
        self.assertEqual(set(self.seen()), {"down:demo:ratio_trend", "stale:demo:trend_daily", "stop:demo:rsi2_pullback:SOL/USDT",
                                            "review:demo:momentum_ls", "block:demo:vol_breakout", "kill:demo"})

    def test_a_kill_switch_block_is_one_account_alert_not_seven(self):
        for s in wd.STRATEGIES: self.status(s, entry_block="Central Risk Manager kill switch is tripped — x")
        self.assertEqual(self.seen(), {})

    def test_alert_once_after_the_confirmations_then_once_when_cleared(self):
        down = {"down:demo:x": ("البوت x واقف", 2)}
        st, msgs = wd.step({}, down); self.assertEqual(msgs, [])                      # a restart: not yet
        st, msgs = wd.step(st, down); self.assertEqual(msgs, ["🚨 البوت x واقف"])
        st, msgs = wd.step(st, down); self.assertEqual(msgs, [])                      # not repeated
        st, msgs = wd.step(st, {}); self.assertEqual(msgs, ["✅ اتحلت: البوت x واقف"])
        self.assertEqual(st, {})
        self.assertEqual(wd.step({}, {"kill:demo": ("قفل", 1)})[1], ["🚨 قفل"])       # urgent ones at once
        self.assertEqual(wd.step({"down:demo:x": {"count": 1, "text": "t"}}, {})[1], [])  # cleared before alerting

    # review 2026-10-31: the watchdog could go silent exactly when it mattered most
    def test_a_status_left_by_the_other_environment_is_a_problem_not_skipped(self):
        self.status("trend_daily", env="live")                                        # Demo bot switched on, live's file left
        self.assertEqual(set(self.seen()), {"stale:demo:trend_daily"})

    def test_a_crash_while_checking_is_itself_an_alert(self):
        orig = wd.problems
        try:
            wd.problems = lambda now: (_ for _ in ()).throw(OSError("systemctl missing"))
            seen = wd.checks(NOW)
        finally:
            wd.problems = orig
        self.assertEqual(set(seen), {"watchdog"}); self.assertIn("systemctl missing", seen["watchdog"][0])

    def test_long_alerts_go_in_parts_telegram_accepts(self):
        lines = ["🐶 مراقب رقم"] + [f"🚨 COIN{i}/USDT في trend_breakout (Demo) مش متأكدين إن وقف الخسارة على Binance" for i in range(66)]
        parts = wd.chunks(lines)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(p) <= wd.LIMIT for p in parts))
        self.assertEqual("\n".join(parts).split("\n"), lines)                          # nothing lost or reordered
        self.assertEqual(wd.chunks(["x" * 5000]), ["x" * wd.LIMIT])
        self.assertEqual(wd.chunks([]), [])


class WatchdogUnitTests(unittest.TestCase):
    def test_the_unit_lets_it_open_the_risk_ledgers(self):
        # ProtectSystem=strict made /opt read-only: SQLite couldn't open the ledger, a false "ledger unreadable" alert
        unit = (ROOT / "deploy" / "vps" / "raqm-watchdog.service").read_text(encoding="utf-8")
        paths = " ".join(l.split("=", 1)[1] for l in unit.splitlines() if l.startswith("ReadWritePaths="))
        for d in wd.LEDGERS.values(): self.assertIn(f"-{d.as_posix()}", paths.split())


class HeartbeatTests(unittest.TestCase):
    """An uptime check outside the server (owner, 2026-11-01): the watchdog can't report the VPS or itself being down."""
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.d = Path(self.td.name)
    def tearDown(self): self.td.cleanup()

    def test_the_heartbeat_has_the_time_and_only_a_count(self):
        wd.heartbeat(NOW, {"down:demo:x": {"count": 2, "text": "t", "sent": True}, "stale:demo:y": {"count": 1, "text": "t"}},
                     path=self.d / "hb.json")
        self.assertEqual(json.loads((self.d / "hb.json").read_text(encoding="utf-8")), {"at": NOW.isoformat(), "problems": 1})

    def test_a_heartbeat_failure_does_not_stop_the_watchdog(self):
        wd.heartbeat(NOW, {}, path=self.d / "missing" / "hb.json")   # folder absent: prints, no exception

    def api(self, hb=None):
        sys.path.insert(0, str(ROOT / "backend"))
        import app.main as m
        from fastapi.testclient import TestClient
        if hb is not None:
            (self.d / "watchdog_heartbeat.json").write_text(json.dumps(hb), encoding="utf-8")
        with mock.patch.object(m, "IPC_DIR", self.d):
            return TestClient(m.app).get("/api/health/bots")

    def test_the_api_says_ok_while_the_heartbeat_is_fresh(self):
        r = self.api({"at": datetime.now(timezone.utc).isoformat(), "problems": 2})
        self.assertEqual(r.status_code, 200); self.assertEqual((r.json()["ok"], r.json()["problems"]), (True, 2))

    def test_an_uptime_monitor_checking_with_head_gets_the_same_status(self):
        sys.path.insert(0, str(ROOT / "backend"))
        import app.main as m
        from fastapi.testclient import TestClient
        (self.d / "watchdog_heartbeat.json").write_text(json.dumps({"at": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
        with mock.patch.object(m, "IPC_DIR", self.d):
            self.assertEqual(TestClient(m.app).head("/api/health/bots").status_code, 200)
            (self.d / "watchdog_heartbeat.json").unlink()
            self.assertEqual(TestClient(m.app).head("/api/health/bots").status_code, 503)

    def test_a_stale_or_missing_heartbeat_is_503(self):
        self.assertEqual(self.api().status_code, 503)
        self.assertEqual(self.api({"at": (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat()}).status_code, 503)
        self.assertEqual(self.api({"at": "garbage"}).status_code, 503)

    def test_the_unit_lets_it_write_the_heartbeat(self):
        unit = (ROOT / "deploy" / "vps" / "raqm-watchdog.service").read_text(encoding="utf-8")
        self.assertIn(f"-{wd.IPC.as_posix()}", " ".join(l.split("=", 1)[1] for l in unit.splitlines() if l.startswith("ReadWritePaths=")).split())


if __name__ == "__main__":
    unittest.main()
