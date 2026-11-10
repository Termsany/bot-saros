"""The paper ratio bot keeps each pair's best running PnL, and its history row at close says it (owner, 2026-11-10:
"it closes at a loss when the trend turns, after it was in profit"; research/ratio_exit_study.py)."""
import sys, unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
import bot as botmod
import bots.ratio_trend as rt

A, B = "AAA/USDT:USDT", "BBB/USDT:USDT"


def state():
    t = datetime(2026, 11, 1, tzinfo=timezone.utc).isoformat()
    return {"pairs": {f"{A}|{B}": {"sign": 1, "time": t, "legs": [{"sym": A, "side": "long", "entry": 100.0, "qty": 1.0},
                                                                    {"sym": B, "side": "short", "entry": 50.0, "qty": 2.0}]}},
            "positions": {}, "history": [], "stats": {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0}}


class RatioPeakTests(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(botmod, "save_state", lambda s: None); p.start(); self.addCleanup(p.stop)

    def test_the_peak_rises_and_never_falls(self):
        st = state(); pr = st["pairs"][f"{A}|{B}"]
        rt._ratio_track_peaks(st, {A: 110.0, B: 50.0}); self.assertEqual(pr["peak"], 10.0)     # long +10, short 0
        rt._ratio_track_peaks(st, {A: 112.0, B: 49.0}); self.assertEqual(pr["peak"], 14.0)     # +12 and +2
        rt._ratio_track_peaks(st, {A: 95.0, B: 52.0}); self.assertEqual(pr["peak"], 14.0)      # now −9: kept
        rt._ratio_track_peaks(st, {A: 130.0}); self.assertEqual(pr["peak"], 14.0)              # B not read: skipped

    def test_the_close_keeps_the_peak_in_history(self):
        st = state(); key = f"{A}|{B}"
        rt._ratio_track_peaks(st, {A: 112.0, B: 49.0})
        since = int(datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp() * 1000)
        pnl = rt._ratio_close_pair(None, st, key, {A: 95.0, B: 52.0}, "الترند اتقلب", {(A, since): 0.0, (B, since): 0.0})
        h = st["history"][-1]
        self.assertLess(pnl, 0)
        self.assertEqual(h["peak"], 14.0)                                 # it was +14 before it closed at a loss

    def test_the_page_file_shows_it(self):
        src = (ROOT / "bots" / "ratio_trend.py").read_text(encoding="utf-8")
        self.assertIn('"peak": bot._r4(h.get("peak"))', src)
        self.assertIn('"ranks": pr.get("ranks"), "peak": pr.get("peak")})', src)


if __name__ == "__main__":
    unittest.main()
