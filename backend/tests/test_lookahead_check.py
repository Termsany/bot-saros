"""research/lookahead_check.py catches a simulator that reads the future and passes one that doesn't."""
import sys, unittest
from pathlib import Path

import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "research"))
import lookahead_check as la

DAY = la.DAY_MS
T0 = int(pd.Timestamp("2022-01-01").value // 1_000_000)
CUTS = ["2022-03-01", "2022-05-01", "2022-07-01"]


def market(n=240, coins=6, seed=7):
    rng = np.random.default_rng(seed); data = {}
    for i in range(coins):
        c = 100 * np.exp(np.cumsum(rng.normal(0, 0.04, n)))
        o = np.r_[c[0], c[:-1]]
        data[f"C{i}USDT"] = pd.DataFrame({"ts": T0 + np.arange(n) * DAY, "open": o, "high": np.maximum(o, c) * 1.01,
                                          "low": np.minimum(o, c) * 0.99, "close": c, "qvol": 1e6})
    return data, {s: {int(t): 0.0001 for t in df.ts} for s, df in data.items()}


def honest(data, fund):
    """Long at the next open after an up close, out at the following open."""
    out = []
    for s, df in data.items():
        c, o, ts = df.close.values, df.open.values, df.ts.values
        for i in range(1, len(df) - 2):
            if c[i] > c[i - 1]:
                out.append(dict(symbol=s, side="long", entry_ts=int(ts[i + 1]), entry=o[i + 1], exit_ts=int(ts[i + 2])))
    return out


def peeks(data, fund):
    """The same, but only when tomorrow's close is up too: reads one bar ahead."""
    out = []
    for s, df in data.items():
        c, o, ts = df.close.values, df.open.values, df.ts.values
        for i in range(1, len(df) - 2):
            if c[i] > c[i - 1] and c[i + 1] > c[i]:
                out.append(dict(symbol=s, side="long", entry_ts=int(ts[i + 1]), entry=o[i + 1], exit_ts=int(ts[i + 2])))
    return out


def picks_winners(data, fund):
    """Honest entries, but only on the coins that end up highest over the whole history: survivorship."""
    best = sorted(data, key=lambda s: data[s].close.iloc[-1] / data[s].close.iloc[0])[-2:]
    return [t for t in honest(data, fund) if t["symbol"] in best]


class LookaheadCheckTests(unittest.TestCase):
    def setUp(self):
        self.data, self.fund = market()

    def bad(self, sim):
        return [r for r in la.check(sim, self.data, self.fund, CUTS) if r[2] or r[3] or r[4]]

    def test_an_honest_simulator_passes(self):
        res = la.check(honest, self.data, self.fund, CUTS)
        self.assertTrue(all(k > 0 for _, k, *_ in res))               # it compared real entries
        self.assertEqual(self.bad(honest), [])

    def test_reading_tomorrows_close_is_caught(self):
        self.assertTrue(self.bad(peeks))

    def test_choosing_coins_by_their_future_is_caught(self):
        self.assertTrue(self.bad(picks_winners))

    def test_the_cut_is_what_a_bot_knows_at_the_dates_open(self):
        t = T0 + 50 * DAY
        d, f = la.cut(self.data, self.fund, t)
        x, full = d["C0USDT"], self.data["C0USDT"]
        self.assertEqual(len(x), 51 + la.PAD_DAYS)
        pd.testing.assert_frame_equal(x.iloc[:50], full.iloc[:50])                  # the past, untouched
        o = full.open.iloc[50]
        self.assertEqual(x.iloc[50][["open", "high", "low", "close", "qvol"]].tolist(), [o, o, o, o, 0.0])   # today: its open only
        after = x.iloc[51:]
        self.assertTrue((after[["open", "high", "low", "close"]] == o).all().all() and (after.qvol == 0).all())   # flat, empty
        self.assertTrue(all(max(v) < t for v in f.values()))

    def test_a_delisted_coin_keeps_its_history(self):
        data = dict(self.data); data["OLDUSDT"] = self.data["C1USDT"].iloc[:20].copy()
        d, _ = la.cut(data, self.fund, T0 + 50 * DAY)
        pd.testing.assert_frame_equal(d["OLDUSDT"], data["OLDUSDT"])

    def test_reading_the_entry_bars_close_is_caught(self):
        def same_day(data, fund):          # enters at the open, decided by that bar's own close
            return [dict(symbol=s, side="long", entry_ts=int(df.ts[k]), entry=df.open[k])
                    for s, df in data.items() for k in range(1, len(df)) if df.close[k] > df.open[k]]
        self.assertTrue(self.bad(same_day))

    def test_a_changed_price_counts(self):
        a = [dict(symbol="X", side="long", entry_ts=T0, entry=1.0)]
        b = [dict(symbol="X", side="long", entry_ts=T0, entry=1.1)]
        self.assertEqual(la.compare(a, b, T0), ([], [], [("X", "long", T0)]))

    def test_a_stop_order_from_the_open_may_fill_on_the_days_range(self):
        def breakout(data, fund):          # level known at the open (open + yesterday's range), filled on the day's high
            out = []
            for s, df in data.items():
                o, h, l = df.open.values, df.high.values, df.low.values
                for k in range(1, len(df)):
                    lvl = o[k] + 0.5 * (h[k - 1] - l[k - 1])
                    if h[k] >= lvl: out.append(dict(symbol=s, side="long", entry_ts=int(df.ts[k]), entry=lvl))
            return out
        self.assertTrue(self.bad(breakout))                                           # without the flag: the fill on T is "missing"
        self.assertEqual([r for r in la.check(breakout, self.data, self.fund, CUTS, intrabar=True) if r[2] or r[3] or r[4]], [])
        def breakout_peeks(data, fund):    # the same, only on days that close up: reads T's close
            return [t for t in breakout(data, fund) if data[t["symbol"]].set_index("ts").close[t["entry_ts"]]
                    > data[t["symbol"]].set_index("ts").open[t["entry_ts"]]]
        self.assertTrue([r for r in la.check(breakout_peeks, self.data, self.fund, CUTS, intrabar=True) if r[2] or r[3] or r[4]])

    def test_every_live_strategy_is_listed(self):
        for s in ("trend_daily", "momentum_ls", "listing_short", "ratio_trend", "vol_breakout", "rsi2_pullback", "trend_breakout"):
            self.assertIn(s, la.SIMS)


if __name__ == "__main__":
    unittest.main()
