"""scripts/realbot_export.py: realbot.da3m.io is public, so only the real-money bots and only what the page shows —
a Demo bot's status (same folder) never leaks, nor who closed a trade, review notes or block reasons; a link planted
for a status file isn't followed, a huge one isn't read, and live.json is replaced whole."""
import json, os, sys, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import realbot_export as rx

NOW = datetime(2026, 11, 3, 15, 30, tzinfo=timezone.utc)
POS = {"symbol": "AGT/USDT", "side": "short", "entry": 0.05207, "price": 0.05269, "qty": 998.0, "contract_size": 1.0,
       "sl": 0.072912, "pnl": -0.671, "pnl_estimated": True, "loss_at_sl": -20.86, "opened": "2026-11-03T15:24:53+00:00",
       "unprotected": False, "sl_unverified": False, "exit_below": None}
TRADE = {"symbol": "BNB/USDT:USDT", "side": "long", "entry": 714.05, "exit": 717.25, "qty": 0.14, "pnl": 0.37, "pnl_pct": 0.74,
         "reason": "قفل يدوي من الموقع", "time": "2026-10-30T04:26:29+00:00", "by": "owner@example.com", "rank": 9}


def status(env="live", updated=NOW - timedelta(seconds=60), **kw):
    return {"env": env, "strategy": "momentum_ls", "updated": updated.isoformat(), "leverage": 2, "margin": 50.0,
            "positions": [POS], "history": [TRADE], "review": {"X/USDT": "check"}, "entry_block": "kill switch",
            "last_block": "secret reason", "manual_hold": ["Y/USDT"], **kw}


class RealbotExportTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.ipc = Path(self.td.name) / "ipc"
        for s in rx.STRATEGIES: (self.ipc / s).mkdir(parents=True)

    def tearDown(self):
        self.td.cleanup()

    def put(self, strategy, doc):
        (self.ipc / strategy / "live_status.json").write_text(json.dumps(doc), encoding="utf-8")

    def test_only_real_money_bots_are_published(self):
        self.put("momentum_ls", status("live")); self.put("trend_daily", status("demo")); self.put("ratio_trend", status("paper"))
        doc = rx.build(self.ipc, NOW)
        self.assertEqual([b["strategy"] for b in doc["bots"]], ["momentum_ls"])

    def test_only_the_pages_fields_leave_the_server(self):
        self.put("momentum_ls", status())
        bot = rx.build(self.ipc, NOW)["bots"][0]
        self.assertEqual(set(bot), {"strategy", "updated", "running", "leverage", "positions", "history"})
        self.assertEqual(set(bot["positions"][0]), set(rx.POSITION_FIELDS))
        self.assertNotIn("by", bot["history"][0]); self.assertNotIn("rank", bot["history"][0])
        text = json.dumps(bot)
        for secret in ("owner@example.com", "secret reason", "kill switch", "Y/USDT", "X/USDT"):
            self.assertNotIn(secret, text)

    def test_a_stale_status_is_not_running(self):
        self.put("momentum_ls", status(updated=NOW - timedelta(minutes=10)))
        self.assertFalse(rx.build(self.ipc, NOW)["bots"][0]["running"])
        self.put("momentum_ls", status(updated=NOW - timedelta(seconds=30)))
        self.assertTrue(rx.build(self.ipc, NOW)["bots"][0]["running"])

    def test_a_link_is_not_followed(self):
        secret = Path(self.td.name) / "secret.json"; secret.write_text(json.dumps(status()), encoding="utf-8")
        try:
            os.symlink(secret, self.ipc / "momentum_ls" / "live_status.json")
        except (OSError, NotImplementedError):
            self.skipTest("no symlinks here")
        self.assertEqual(rx.build(self.ipc, NOW)["bots"], [])

    def test_a_huge_or_broken_file_is_skipped(self):
        (self.ipc / "momentum_ls" / "live_status.json").write_bytes(b"{" + b" " * (rx.MAX_BYTES + 10) + b"}")
        (self.ipc / "trend_daily" / "live_status.json").write_text("not json", encoding="utf-8")
        self.assertEqual(rx.build(self.ipc, NOW)["bots"], [])

    def test_live_json_is_replaced_whole_and_readable(self):
        out = Path(self.td.name) / "web" / "live.json"; out.parent.mkdir()
        self.put("momentum_ls", status())
        rx.write(rx.build(self.ipc, NOW), out)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["bots"][0]["positions"][0]["symbol"], "AGT/USDT")
        self.assertEqual([p.name for p in out.parent.iterdir()], ["live.json"])   # no temp file left
        if os.name != "nt":
            self.assertEqual(oct(out.stat().st_mode & 0o777), "0o644")

    def test_setup_installs_the_page_and_the_exporter(self):
        s = (ROOT / "deploy" / "vps" / "setup-live.sh").read_text(encoding="utf-8")
        for needle in ("scripts/realbot_export.py", "realbot/index.html", "raqm-realbot-export.timer"):
            self.assertIn(needle, s)
        unit = (ROOT / "deploy" / "vps" / "raqm-realbot-export.service").read_text(encoding="utf-8")
        self.assertIn("User=raqmlive", unit); self.assertIn("ReadOnlyPaths=/opt/raqm-ipc", unit); self.assertIn("PrivateNetwork=true", unit)


if __name__ == "__main__":
    unittest.main()
