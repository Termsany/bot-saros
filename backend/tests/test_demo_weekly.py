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


def leg(t, pct, pnl=0.0, **kw):
    return dict({"symbol": "X/USDT:USDT", "side": "long", "opened": (t - timedelta(days=3)).isoformat(), "time": t.isoformat(),
                 "pnl": pnl, "pnl_pct": pct, "reason": "تبديل أسبوعي", "by": None}, **kw)


class RealAndExperimentTests(unittest.TestCase):
    """The real momentum_ls next to its backtest, and the Wednesday experiment next to it over the same weeks."""
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(); self.ipc = Path(self.td.name)
    def tearDown(self): self.td.cleanup()

    def write(self, folder, rows, env):
        (self.ipc / folder).mkdir(parents=True, exist_ok=True)
        (self.ipc / folder / "closed.json").write_text(json.dumps({"env": env, "closed": rows}), encoding="utf-8")

    def text(self, now=NOW):
        return "\n".join(dw.real_and_experiment(self.ipc, BASE, now))

    def test_the_real_account_counts_from_the_go_live_in_margins_and_dollars(self):
        ain = leg(datetime(2026, 11, 6, 0, 40, tzinfo=timezone.utc), -79.97, -20.79, reason="وقف المنصة",
                  opened="2026-11-03T15:24:53.669402+00:00")                                   # the real AIN leg
        self.write("momentum_ls", [ain, leg(datetime(2026, 11, 2, tzinfo=timezone.utc), 50.0, 13.0)], "live")   # before go-live
        t = self.text()
        self.assertIn("لسه بتجمع — 1/30 رجل", t)
        self.assertIn("صافي -0.8 مارجن", t); self.assertIn("بالدولار: -20.79$", t)
        self.assertIn("الباكتست: PF 1.19", t)
        self.assertIn("لسه ما بدأتش", t)

    def test_a_demo_file_in_the_real_folder_is_not_the_real_account(self):
        self.write("momentum_ls", [leg(datetime(2026, 11, 6, tzinfo=timezone.utc), 10.0)], "demo")
        self.assertIn("ملف الصفقات المقفولة مش موجود", self.text())

    def test_the_experiment_is_compared_with_the_real_bot_over_its_own_weeks(self):
        start = datetime(2026, 11, 11, tzinfo=timezone.utc)
        self.write("momentum_ls", [leg(datetime(2026, 11, 9, tzinfo=timezone.utc), 30.0),        # before the experiment
                                   leg(datetime(2026, 11, 16, tzinfo=timezone.utc), -10.0)], "live")
        self.write("momentum_wed", [leg(start + timedelta(days=6), 20.0, opened=start.isoformat()),
                                    leg(start + timedelta(days=6), -5.0, opened=start.isoformat(), reason="قفل يدوي من Binance")], "demo")
        t = self.text(datetime(2026, 11, 20, tzinfo=timezone.utc))
        self.assertIn("الأربع: 1/80 رجل", t)                      # the manual close isn't counted
        self.assertIn("الاتنين: 1 رجل", t)                        # only the real legs since the experiment began
        self.assertIn("لسه بتجمع: القرار بعد 80 رجل", t)

    def test_after_eight_weeks_it_says_which_one_did_better(self):
        start = datetime(2026, 11, 11, tzinfo=timezone.utc)
        exp = [leg(start + timedelta(days=6 + 7 * (i // 10)), 2.0, opened=(start + timedelta(days=7 * (i // 10))).isoformat()) for i in range(80)]
        self.write("momentum_wed", exp, "demo")
        self.write("momentum_ls", [leg(start + timedelta(days=5 + 7 * w), 1.0) for w in range(8)], "live")
        self.assertIn("✅ الأربع مش أسوأ", self.text(datetime(2027, 1, 15, tzinfo=timezone.utc)))
        self.write("momentum_wed", [dict(r, pnl_pct=-2.0) for r in exp], "demo")
        self.assertIn("❌ الأربع أسوأ", self.text(datetime(2027, 1, 15, tzinfo=timezone.utc)))


if __name__ == "__main__":
    unittest.main()
