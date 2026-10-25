"""collect_market_data.py: backfill without gaps, no duplicates on the next run, coins listed mid-window."""
import sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
import collect_market_data as cm

H = cm.HOUR
NOW = 1_800_000_000_000 // H * H + 20 * 60_000          # 20 minutes past an hour


def fake_binance(first_ts):
    """Hourly rows from first_ts; like Binance, at most 500 per call and only within [startTime, endTime]."""
    def fetch(path, p):
        lo = max(p["startTime"], first_ts); lo = -(-lo // H) * H
        hi = min(p["endTime"], NOW // H * H)                # like Binance: includes the current, unfinished hour
        ts = list(range(lo, hi + 1, H))[:500]
        return [{"timestamp": t, "sumOpenInterest": "1", "sumOpenInterestValue": "2", "CMCCirculatingSupply": "3",
                 "longShortRatio": "1.5", "longAccount": "0.6", "shortAccount": "0.4", "buySellRatio": "1", "buyVol": "5", "sellVol": "5"}
                for t in ts]
    return fetch


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = cm.open_db(str(Path(self.td.name) / "m.sqlite"))
    def tearDown(self):
        self.db.close(); self.td.cleanup()

    def hours(self, table, sym):
        return [r[0] for r in self.db.execute(f"SELECT ts FROM {table} WHERE symbol=? ORDER BY ts", (sym,))]

    def test_backfill_is_continuous_and_rerun_adds_nothing(self):
        f = fake_binance(0)
        added, errors = cm.collect(self.db, ["BTCUSDT"], fetch=f, now_ms=NOW, pause=0)
        ts = self.hours("oi", "BTCUSDT")
        self.assertEqual(errors, 0)
        self.assertTrue(all(b - a == H for a, b in zip(ts, ts[1:])))          # no gap at the page boundary
        self.assertGreaterEqual(len(ts), 29 * 24 - 1)
        self.assertEqual(cm.collect(self.db, ["BTCUSDT"], fetch=f, now_ms=NOW, pause=0)[0], 0)

    def test_next_day_only_adds_the_new_hours(self):
        f = fake_binance(0)
        cm.collect(self.db, ["BTCUSDT"], fetch=f, now_ms=NOW - 24 * H, pause=0)
        before = len(self.hours("taker", "BTCUSDT"))
        cm.collect(self.db, ["BTCUSDT"], fetch=f, now_ms=NOW, pause=0)
        self.assertEqual(len(self.hours("taker", "BTCUSDT")) - before, 24)

    def test_coin_listed_inside_the_window(self):
        listed = NOW - 3 * 24 * H
        cm.collect(self.db, ["NEWUSDT"], fetch=fake_binance(listed), now_ms=NOW, pause=0)
        ts = self.hours("ls_top_pos", "NEWUSDT")
        self.assertEqual(ts[0], -(-listed // H) * H)
        self.assertTrue(all(b - a == H for a, b in zip(ts, ts[1:])))


if __name__ == "__main__":
    unittest.main()
