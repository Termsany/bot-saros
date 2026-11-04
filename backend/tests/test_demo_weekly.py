"""The weekly Demo check (scripts/demo_weekly.py, roadmap B5): the admin page's measurement, as a Telegram message."""
import json, sys, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(ROOT / "backend"))
import demo_weekly as dw
from app import demo_measure as dm

NOW = datetime(2026, 11, 8, 18, tzinfo=timezone.utc)
BASE = json.loads((ROOT / "lib" / "demo-baseline.json").read_text(encoding="utf-8"))


def trade(day, pct, **kw):
    t = dm.START + timedelta(days=day)
    return dict({"symbol": "X/USDT:USDT", "opened": (t - timedelta(hours=1)).isoformat(), "time": t.isoformat(),
                 "pnl_pct": pct, "reason": "إشارة", "by": None}, **kw)


class DemoWeeklyTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(); self.ipc = Path(self.td.name)

    def tearDown(self):
        self.td.cleanup()

    def write(self, s, rows, env="demo"):
        (self.ipc / s).mkdir(parents=True, exist_ok=True)
        (self.ipc / s / "closed.json").write_text(json.dumps({"env": env, "closed": rows}), encoding="utf-8")

    def test_reads_only_demo_files(self):
        self.write("trend_daily", [trade(1, 5.0)]); self.write("ratio_trend", [trade(1, 5.0)], env="live")
        (self.ipc / "vol_breakout").mkdir(); (self.ipc / "vol_breakout" / "closed.json").write_text("{bad", encoding="utf-8")
        self.assertEqual(set(dw.load_closed(self.ipc)), {"trend_daily"})

    def test_report_lists_every_strategy_with_its_sample_and_the_baseline(self):
        self.write("trend_daily", [trade(1, 20.0), trade(2, -5.0), trade(3, -5.0, reason="قفل يدوي من Binance")])
        text, far = dw.report(dm.measure(dw.load_closed(self.ipc), BASE, NOW), {"trend_daily": "الترند اليومي"})
        self.assertEqual(far, 0)
        self.assertIn("⏳ الترند اليومي: لسه بتجمع — 2/30 صفقة", text)          # the manual close is not counted
        self.assertIn("PF 4.0 (الباكتست 2.2)", text)
        self.assertIn("➖ momentum_ls: مش متقاسة", text)
        self.assertIn("مفيش استراتيجية لازم تتقفل", text)
        for s in dm.SAMPLE: self.assertIn(s if s != "trend_daily" else "الترند اليومي", text)

    def test_a_strategy_far_from_the_baseline_after_its_sample_is_named_to_switch_off(self):
        self.write("rsi2_pullback", [trade(i * 0.5, -3.0 if i % 2 else 1.0) for i in range(16)])
        text, far = dw.report(dm.measure(dw.load_closed(self.ipc), BASE, NOW))
        self.assertEqual(far, 1)
        self.assertIn("❌ rsi2_pullback: بعيدة: تتقفل", text)
        self.assertIn("تتقفل، مش تتعدّل", text)

    def test_the_unit_is_read_only_and_weekly_away_from_monday(self):
        u = (ROOT / "deploy" / "vps" / "raqm-demo-weekly.service").read_text(encoding="utf-8")
        for part in ("User=raqmapi", "ProtectSystem=strict", "ReadOnlyPaths=/opt/raqm-api/app /opt/raqm-ipc",
                     "EnvironmentFile=/opt/raqm-live/.env.telegram", "scripts/demo_weekly.py --telegram", "SuccessExitStatus=1"):
            self.assertIn(part, u)
        self.assertIn("OnCalendar=Sun *-*-* 18:00:00 UTC", (ROOT / "deploy" / "vps" / "raqm-demo-weekly.timer").read_text(encoding="utf-8"))
        s = (ROOT / "deploy" / "vps" / "setup-live.sh").read_text(encoding="utf-8")
        self.assertIn("raqm-demo-weekly.timer", s)


if __name__ == "__main__":
    unittest.main()
