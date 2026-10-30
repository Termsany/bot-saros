"""Problem alerts (scripts/watchdog.py, owner 2026-10-30): one message when a problem starts, one when it clears."""
import json, sys, tempfile, unittest
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


if __name__ == "__main__":
    unittest.main()


class WatchdogUnitTests(unittest.TestCase):
    def test_the_unit_lets_it_open_the_risk_ledgers(self):
        # ProtectSystem=strict made /opt read-only: SQLite couldn't open the ledger, a false "ledger unreadable" alert
        unit = (ROOT / "deploy" / "vps" / "raqm-watchdog.service").read_text(encoding="utf-8")
        paths = " ".join(l.split("=", 1)[1] for l in unit.splitlines() if l.startswith("ReadWritePaths="))
        for d in wd.LEDGERS.values(): self.assertIn(f"-{d.as_posix()}", paths.split())
