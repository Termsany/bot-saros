"""The momentum daily paper bot (owner, 2026-11-11; bot.py --strategy momentum_daily): the momentum_ls ranking, a new
basket every day at 00:00 UTC, held one day. Paper only; the unit, the watchdog and the page know it."""
import os, subprocess, sys, unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import bot as botmod
from test_live_momentum_ls import MomentumFakeBinance, ranked


def day(s):
    return datetime.fromisoformat(s + "T00:00:00+00:00")


class ScheduleTests(unittest.TestCase):
    def test_every_day_once(self):
        D = botmod.DAILY
        last = day("2026-11-12").isoformat()
        args = (D["every_days"], D["weekday"], D["hold_days"])
        self.assertFalse(botmod.momentum_due(last, day("2026-11-12"), *args))
        self.assertTrue(botmod.momentum_due(last, day("2026-11-13"), *args))
        self.assertTrue(botmod.momentum_due(last, day("2026-11-15"), *args))      # down two days: the next cycle
        self.assertFalse(botmod.momentum_hold_over(last, day("2026-11-13"), D["hold_days"], D["every_days"]))  # the rebalance closes it
        self.assertEqual(botmod.momentum_next(last, D["every_days"], D["weekday"]), day("2026-11-13"))


class PaperDaysTests(unittest.TestCase):
    def test_a_new_basket_each_day(self):
        state = {"positions": {}, "history": [], "stats": {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0}}
        clock = {"now": datetime(2026, 11, 12, 0, 5, tzinfo=timezone.utc)}
        notes = []
        rank = {"now": ranked()}

        class FakeDT(datetime):
            @classmethod
            def now(cls, tz=None): return clock["now"]

        from bots import momentum_ls as mls
        with mock.patch.dict(botmod.MOM, botmod.DAILY), \
             mock.patch.dict(botmod.CONFIG, {"paper_trading": True, "public_dir": None}), \
             mock.patch.object(botmod, "load_state", lambda: state), \
             mock.patch.object(botmod, "save_state", lambda s: None), \
             mock.patch.object(botmod, "process_paper_closes", lambda *a, **k: None), \
             mock.patch.object(botmod, "notify", notes.append), \
             mock.patch.object(botmod, "log", lambda *a, **k: None), \
             mock.patch.object(botmod, "momentum_rank", lambda ex: rank["now"]), \
             mock.patch.object(mls, "datetime", FakeDT):
            ex = MomentumFakeBinance()
            mls.run_once_momentum(ex)
            self.assertEqual((state["mom_last"], len(state["positions"])), ("2026-11-12T00:00:00+00:00", 10))
            clock["now"] = datetime(2026, 11, 12, 18, 0, tzinfo=timezone.utc)
            mls.run_once_momentum(ex)                                    # same day: nothing new
            self.assertEqual(len(state["history"]), 0)
            kept = state["positions"]["S16/USDT:USDT"]
            # next day: S0 leaves the shorts for the longs, S15 drops out, S5 comes in; the other 8 are kept as they are
            rank["now"] = ranked()[1:] + ranked()[:1]
            clock["now"] = datetime(2026, 11, 13, 0, 5, tzinfo=timezone.utc)
            mls.run_once_momentum(ex)
            self.assertEqual((state["mom_last"], len(state["positions"])), ("2026-11-13T00:00:00+00:00", 10))
            self.assertEqual(sorted((h["symbol"], h["side"]) for h in state["history"]), [("S0/USDT:USDT", "short"), ("S15/USDT:USDT", "long")])
            self.assertEqual(state["positions"]["S0/USDT:USDT"]["side"], "long")
            self.assertIn("S5/USDT:USDT", state["positions"])
            self.assertIs(state["positions"]["S16/USDT:USDT"], kept)            # not closed and reopened
        self.assertIn("تبديل يومي", notes[-1]); self.assertIn("امبارح", notes[-1])


class WiringTests(unittest.TestCase):
    def run_bot(self, *args):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("BINANCE", "ALLOW_LIVE", "RAQM_"))}
        e.update({"BINANCE_ENV": "live", "PYTHONIOENCODING": "utf-8"})
        return subprocess.run([sys.executable, "bot.py", *args], cwd=ROOT, env=e, capture_output=True, timeout=120,
                              encoding="utf-8", errors="replace")

    def test_paper_only(self):
        for args in (("--live", "--strategy", "momentum_daily"), ("--strategy", "momentum_ls", "--mom-daily")):
            r = self.run_bot(*args)
            self.assertEqual(r.returncode, 2, args); self.assertIn("paper", r.stderr, args)

    def test_the_variant_resolves(self):
        r = self.run_bot("--paper", "--strategy", "momentum_daily", "--show-config")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('"public_name": "momentum_daily"', r.stdout); self.assertIn('"every_days": 1', r.stdout)

    def test_the_unit_page_and_watchdog(self):
        u = (ROOT / "deploy/vps/raqm-momentum-daily.service").read_text(encoding="utf-8")
        self.assertIn("--paper --strategy momentum_daily --amount 100 --leverage 2", u)
        self.assertIn("WorkingDirectory=/opt/raqm-momentum-daily", u)
        page = ROOT / "deploy/vps/page"
        self.assertIn('id="mdSec"', (page / "index.html").read_text(encoding="utf-8"))
        self.assertIn("momentum_daily.json", (page / "assets/bots.js").read_text(encoding="utf-8"))
        self.assertIn('k: "momentum_daily"', (page / "assets/board.js").read_text(encoding="utf-8"))
        sys.path.insert(0, str(ROOT / "scripts")); import watchdog
        self.assertIn("momentum_daily", watchdog.PAPER_BOTS)


if __name__ == "__main__":
    unittest.main()
