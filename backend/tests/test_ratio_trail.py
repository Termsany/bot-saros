"""--ratio-trail (owner, 2026-11-10; research §35, B2): the paper ratio pairs leave when their ratio is 20% below its
best since entry, and stay flat until the 50-day sign turns."""
import sys, tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
import bot as botmod
import bots.ratio_trend as rt

A, B = "AAA/USDT:USDT", "BBB/USDT:USDT"
KEY = f"{A}|{B}"


def held(sign=1):
    t = datetime(2026, 11, 1, tzinfo=timezone.utc).isoformat()
    legs = [{"sym": A, "side": "long", "entry": 100.0, "qty": 1.0}, {"sym": B, "side": "short", "entry": 50.0, "qty": 2.0}]
    if sign == -1: legs = [{"sym": B, "side": "long", "entry": 50.0, "qty": 2.0}, {"sym": A, "side": "short", "entry": 100.0, "qty": 1.0}]
    return {"pairs": {KEY: {"sign": sign, "time": t, "legs": legs}}, "positions": {}, "history": [], "ratio_blocked": {},
            "stats": {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0}}


class Ticker:
    def __init__(self, px): self.px = px
    def fetch_ticker(self, s): return {"last": self.px[s]}
    def fetch_funding_rate_history(self, s, since=None, limit=None): return []


class TrailTests(unittest.TestCase):
    def setUp(self):
        for p in (mock.patch.dict(botmod.RATIO, {"trail": 0.20}), mock.patch.object(botmod, "save_state", lambda s: None)):
            p.start(); self.addCleanup(p.stop)

    def day(self, st, a, b):
        return rt._ratio_trail_exits(Ticker({A: a, B: b}), st, {}, {})

    def test_it_follows_the_best_and_leaves_20_percent_below_it(self):
        st = held()
        self.day(st, 130.0, 50.0); self.assertAlmostEqual(st["pairs"][KEY]["best"], 1.3)   # ratio +30%
        self.day(st, 106.0, 50.0); self.assertIn(KEY, st["pairs"])                          # 1.06 > 1.3 x 0.8 = 1.04
        self.day(st, 103.0, 50.0)                                                           # 1.03: out
        self.assertNotIn(KEY, st["pairs"])
        self.assertEqual(st["ratio_blocked"], {KEY: 1})
        self.assertEqual(st["history"][-1]["reason"], "trailing 20%")
        self.assertGreater(st["history"][-1]["pnl"], 0)                                     # it kept part of the gain

    def test_a_short_ratio_trade_trails_the_other_way(self):
        st = held(sign=-1)                                   # long B / short A: the trade wins when A/B falls
        self.day(st, 70.0, 50.0); self.assertAlmostEqual(st["pairs"][KEY]["best"], 100 / 70)
        self.day(st, 75.0, 50.0); self.assertIn(KEY, st["pairs"])                           # 1.333 > 1.429 x 0.8
        self.day(st, 90.0, 50.0); self.assertNotIn(KEY, st["pairs"])                       # 1.111: out
        self.assertEqual(st["ratio_blocked"], {KEY: -1})

    def test_from_the_entry_a_20_percent_loss_leaves_too(self):
        st = held()
        self.day(st, 79.0, 50.0)
        self.assertNotIn(KEY, st["pairs"])

    def test_a_trailed_pair_stays_flat_until_the_sign_turns(self):
        st = {"pairs": {}, "positions": {}, "history": [], "stats": {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0},
              "ratio_members": [A, B], "ratio_members_at": datetime.now(timezone.utc).isoformat(), "ratio_blocked": {KEY: 1}}
        ex = Ticker({A: 100.0, B: 50.0})
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.dict(botmod.CONFIG, {"paper_trading": True, "public_dir": None}), \
             mock.patch.object(botmod, "load_state", lambda: st), \
             mock.patch.object(botmod, "process_paper_closes", lambda *a: None), \
             mock.patch.object(botmod, "notify", lambda *a, **k: None):
            with mock.patch.object(botmod, "ratio_signal", lambda *a: 1):
                rt.run_once_ratio(ex)
            self.assertEqual(st["pairs"], {})                                                # same sign: flat
            st.pop("ratio_day")
            with mock.patch.object(botmod, "ratio_signal", lambda *a: -1):
                rt.run_once_ratio(ex)
            self.assertEqual(st["pairs"][KEY]["sign"], -1)                                   # turned: a new trade
            self.assertEqual(st["ratio_blocked"], {})

    def test_the_flag_is_paper_pairs_only(self):
        src = (ROOT / "bot.py").read_text(encoding="utf-8")
        self.assertIn('p.error("--ratio-trail: paper ratio_trend pairs only (not --ratio-net), a fraction like 0.20")', src)


if __name__ == "__main__":
    unittest.main()
