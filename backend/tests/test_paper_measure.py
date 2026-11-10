"""The paper candidates against their own backtest in the weekly report (owner, 2026-11-08): lib/paper-baseline.json
holds both, each paper bot's public history is read in % of its margin from its own start, demo_measure's rules."""
import json, sys, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(ROOT / "backend"))
import demo_weekly as dw

NOW = datetime(2026, 12, 20, tzinfo=timezone.utc)
START = datetime(2026, 11, 7, 18, tzinfo=timezone.utc)


def trade(day, pnl, **kw):
    t = START + timedelta(days=day)
    return {"symbol": "X/USDT", "pnl": pnl, "opened": (t - timedelta(days=1)).isoformat(), "time": t.isoformat(), **kw}


class PaperMeasureTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.pub = Path(self.td.name)

    def tearDown(self):
        self.td.cleanup()

    def write(self, name, history, margin=100.0):
        (self.pub / f"{name}.json").write_text(json.dumps({"margin": margin, "started": START.isoformat(), "history": history}), encoding="utf-8")

    def test_the_baseline_file_has_both_candidates_in_the_demo_units(self):
        base = json.loads(dw.PAPER_BASELINE.read_text(encoding="utf-8"))["strategies"]
        self.assertEqual(set(base), set(dw.PAPER))
        demo = json.loads(dw.BASELINE.read_text(encoding="utf-8"))["strategies"]["rsi2_pullback"]["all"]
        for name in dw.PAPER:
            self.assertEqual(set(base[name]["all"]), set(demo))                       # the same figures
        self.assertEqual(base["rsi2_btc"]["all"]["win_rate"], 70.4)                   # research §28
        self.assertEqual(base["retail_fade"]["all"]["trades"], 1518)                  # research §29

    def test_rows_are_in_percent_of_margin(self):
        rows = dw.paper_rows({"margin": 20, "history": [{"pnl": 5}, {"pnl": "x"}, {}]})
        self.assertEqual([r["pnl_pct"] for r in rows], [25.0])
        self.assertEqual(dw.paper_rows({"margin": 0, "history": [{"pnl": 5}]}), [])

    def test_collecting_then_in_range_or_far(self):
        self.write("rsi2_btc", [trade(1, 10.0), trade(2, -12.0, reason="قفل يدوي")])    # the manual close doesn't count
        self.write("retail_fade", [trade(d, 5.0 if d % 2 else -4.0) for d in range(40)], margin=20.0)
        text = "\n".join(dw.paper_lines(NOW, self.pub))
        self.assertIn("1/15 صفقة", text)
        self.assertIn("36", text)
        self.assertRegex(text, r"ضد الجمهور.*(قريبة من الباكتست|محتاجة نظرة)")
        self.write("rsi2_btc", [trade(d, -15.0 if d % 3 else 4.0) for d in range(20)])    # PF far under 1
        text = "\n".join(dw.paper_lines(NOW, self.pub))
        self.assertRegex(text, r"RSI-2 \+ فلتر BTC.*بعيدة")

    def test_a_missing_file_says_so(self):
        text = "\n".join(dw.paper_lines(NOW, self.pub))
        self.assertIn("ملفه مش موجود", text)
        self.assertIn("مش موجود", "\n".join(dw.paper_lines(NOW, self.pub, self.pub / "nope.json")))


if __name__ == "__main__":
    unittest.main()
