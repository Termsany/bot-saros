"""--ratio-weekday / the ratio_weekly variant (owner, 2026-11-17; research §41): the paper ratio pairs change only on
one weekday (Monday), with momentum_ls's rule — never twice a day, and as soon as 7 days pass if the day was missed."""
import json, os, shlex, subprocess, sys, tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
import bot as botmod
import bots.ratio_trend as rt

A, B = "AAA/USDT:USDT", "BBB/USDT:USDT"
KEY = f"{A}|{B}"
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "BINANCE_ENV": "demo"}
MON, TUE, WED = (datetime(2026, 11, d, tzinfo=timezone.utc) for d in (23, 24, 25))


def at(day, hour=0, minute=5):
    class Now(datetime):
        @classmethod
        def now(cls, tz=None): return day.replace(hour=hour, minute=minute)
    return Now


class Ticker:
    def __init__(self, px): self.px = px
    def fetch_ticker(self, s): return {"last": self.px[s]}
    def fetch_funding_rate_history(self, s, since=None, limit=None): return []


def book(switched):
    legs = [{"sym": A, "side": "long", "entry": 100.0, "qty": 1.0}, {"sym": B, "side": "short", "entry": 50.0, "qty": 2.0}]
    return {"pairs": {KEY: {"sign": 1, "time": switched.isoformat(), "legs": legs}}, "positions": {}, "history": [],
            "stats": {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0}, "ratio_members": [A, B],
            "ratio_members_at": switched.isoformat(), "ratio_switch": switched.isoformat(), "ratio_day": switched.isoformat()}


class SwitchDayTests(unittest.TestCase):
    def due(self, last, today, weekday=0):
        with mock.patch.dict(botmod.RATIO, {"weekday": weekday}):
            return rt.ratio_switch_due({"ratio_switch": last.isoformat() if last else None}, today)

    def test_every_day_without_the_flag(self):
        self.assertTrue(self.due(TUE, TUE, weekday=None))

    def test_monday_only_once_a_day_and_the_first_cycle_starts_at_once(self):
        self.assertTrue(self.due(None, WED))                  # a new bot takes the book at its first cycle
        self.assertTrue(self.due(MON.replace(day=16), MON))   # Monday after last Monday
        self.assertFalse(self.due(MON, MON))                  # never twice on one day
        self.assertFalse(self.due(MON, TUE)); self.assertFalse(self.due(MON, WED))

    def test_a_missed_monday_switches_as_soon_as_7_days_have_passed(self):
        self.assertFalse(self.due(MON.replace(day=16), MON.replace(day=22)))   # Sunday: 6 days
        self.assertTrue(self.due(MON.replace(day=16), TUE))                    # down all Monday: Tuesday, 8 days


class CycleTests(unittest.TestCase):
    def cycle(self, st, day, sig):
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.dict(botmod.RATIO, {"weekday": 0}), \
             mock.patch.dict(botmod.CONFIG, {"paper_trading": True, "public_dir": d, "public_name": "ratio_weekly"}), \
             mock.patch.object(rt, "datetime", at(day)), \
             mock.patch.object(botmod, "load_state", lambda: st), \
             mock.patch.object(botmod, "save_state", lambda s: None), \
             mock.patch.object(botmod, "process_paper_closes", lambda *a: None), \
             mock.patch.object(botmod, "notify", lambda *a, **k: None), \
             mock.patch.object(botmod, "ratio_members", lambda ex, cache: [A, B]), \
             mock.patch.object(botmod, "ratio_signal", lambda *a: sig):
            rt.run_once_ratio(Ticker({A: 100.0, B: 50.0}))
            return json.loads((Path(d) / "ratio_weekly.json").read_text(encoding="utf-8"))

    def test_a_turn_midweek_waits_for_monday(self):
        st = book(MON.replace(day=16))
        page = self.cycle(st, TUE.replace(day=17), -1)                     # Tuesday: the ratio turned
        self.assertEqual(st["pairs"][KEY]["sign"], 1)                       # kept as it was
        self.assertEqual(st["history"], [])
        self.assertEqual(page["next_switch"], MON.isoformat())
        self.cycle(st, MON, -1)                                              # Monday: the switch
        self.assertEqual(st["pairs"][KEY]["sign"], -1)
        self.assertEqual(st["history"][-1]["reason"], "الترند اتقلب")
        self.assertEqual(st["ratio_switch"], MON.isoformat())
        self.cycle(st, MON, 1)                                               # the same Monday again: nothing
        self.assertEqual(st["pairs"][KEY]["sign"], -1)

    def test_the_daily_bot_is_unchanged(self):
        st = book(MON.replace(day=16)); st.pop("ratio_switch")
        with mock.patch.dict(botmod.RATIO, {"weekday": None}):
            with tempfile.TemporaryDirectory() as d, \
                 mock.patch.dict(botmod.CONFIG, {"paper_trading": True, "public_dir": d, "public_name": None}), \
                 mock.patch.object(rt, "datetime", at(TUE.replace(day=17))), \
                 mock.patch.object(botmod, "load_state", lambda: st), \
                 mock.patch.object(botmod, "save_state", lambda s: None), \
                 mock.patch.object(botmod, "process_paper_closes", lambda *a: None), \
                 mock.patch.object(botmod, "notify", lambda *a, **k: None), \
                 mock.patch.object(botmod, "ratio_signal", lambda *a: -1):
                rt.run_once_ratio(Ticker({A: 100.0, B: 50.0}))
                page = json.loads((Path(d) / "ratio.json").read_text(encoding="utf-8"))
        self.assertEqual(st["pairs"][KEY]["sign"], -1)                      # flipped the same day, as always
        self.assertNotIn("ratio_switch", st)
        self.assertIsNone(page["next_switch"])


def show(argv):
    r = subprocess.run([sys.executable, str(ROOT / "bot.py"), *argv, "--show-config"], capture_output=True, text=True,
                       encoding="utf-8", env=ENV, cwd=ROOT, timeout=120)
    return r.returncode, (json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 else r.stderr)


class CliTests(unittest.TestCase):
    def test_the_unit_runs_the_no_btc_bot_switching_on_monday(self):
        unit = (ROOT / "deploy" / "vps" / "raqm-ratio-weekly.service").read_text(encoding="utf-8")
        line = next(l for l in unit.splitlines() if l.startswith("ExecStart="))
        code, cfg = show(shlex.split(line[line.index("bot.py") + len("bot.py"):]))
        self.assertEqual(code, 0, cfg)
        self.assertEqual((cfg["variant"], cfg["public_name"], cfg["state"], cfg["amount"]), ("ratio_weekly", "ratio_weekly", "state_ratio_weekly.json", 40.0))
        self.assertEqual((cfg["RATIO"]["weekday"], cfg["RATIO"]["exclude"], cfg["RATIO"]["trail"]), (0, ["BTC", "ETH"], 0.0))
        self.assertIn("ReadWritePaths=/opt/raqm-ratio-weekly /var/www/bot.da3m.io", unit)

    def test_paper_pairs_only(self):
        self.assertNotEqual(show(["--live", "--strategy", "ratio_weekly"])[0], 0)
        self.assertNotEqual(show(["--paper", "--strategy", "ratio_trend", "--ratio-net", "--ratio-weekday", "0"])[0], 0)
        self.assertNotEqual(show(["--paper", "--strategy", "momentum_ls", "--ratio-weekday", "0"])[0], 0)
        self.assertEqual(show(["--paper", "--strategy", "ratio_trend"])[1]["RATIO"]["weekday"], None)


if __name__ == "__main__":
    unittest.main()
