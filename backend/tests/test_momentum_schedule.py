"""momentum_ls opens on Wednesday 00:00 UTC and closes after 6 days, on Tuesday 00:00, flat until the next Wednesday
(owner, 2026-11-11; research/README.md §23 — it was Monday and the full week from 2026-11-03). Once per week. A missed
Wednesday (bot down, entries blocked) is caught up on Thursday at the latest, and the late basket keeps the week's
Tuesday close (mom_last records the week's start); later than that the bot waits for the next Wednesday."""
import sys, tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
import bot as botmod


def day(s):
    return datetime.fromisoformat(s + "T00:00:00+00:00")


class MomentumScheduleTests(unittest.TestCase):
    def test_wednesday_six_is_the_default(self):
        M = botmod.MOM
        self.assertEqual((M["weekday"], M["hold_days"], M["every_days"], M["catch_up_days"]), (2, 6, 7, 1))
        self.assertEqual(day("2026-11-18").weekday(), 2)
        self.assertEqual(botmod.RETAIL["hold_days"], 7)                 # the crowd bot keeps its full week

    def test_a_week(self):
        last = day("2026-11-18").isoformat()                            # Wednesday's basket
        for d in ("2026-11-18", "2026-11-19", "2026-11-20", "2026-11-23", "2026-11-24"):
            self.assertFalse(botmod.momentum_due(last, day(d)), d)      # never twice in its week
        for d in ("2026-11-23",):
            self.assertFalse(botmod.momentum_hold_over(last, day(d)), d)
        self.assertTrue(botmod.momentum_hold_over(last, day("2026-11-24")))   # Tuesday 00:00: close
        self.assertTrue(botmod.momentum_due(last, day("2026-11-25")))         # Wednesday: the next one
        self.assertEqual(botmod.momentum_next(last), day("2026-11-25"))

    def test_the_switch_from_monday(self):
        last = day("2026-11-09").isoformat()                            # the last Monday basket
        self.assertTrue(botmod.momentum_due(last, day("2026-11-11")))   # Wednesday
        self.assertTrue(botmod.momentum_due(last, day("2026-11-12")))   # Thursday: one day late is still caught up
        for d in ("2026-11-13", "2026-11-14", "2026-11-15", "2026-11-16", "2026-11-17"):
            self.assertFalse(botmod.momentum_due(last, day(d)), d)      # not on Monday any more, nor later in the week
        self.assertTrue(botmod.momentum_hold_over(last, day("2026-11-15")))  # a Monday basket still open closes by Sunday
        self.assertTrue(botmod.momentum_due(last, day("2026-11-18")))

    def test_a_late_basket_keeps_the_weeks_close(self):
        self.assertEqual(botmod.momentum_slot(day("2026-11-19")), day("2026-11-18"))
        self.assertEqual(botmod.momentum_slot(day("2026-11-24")), day("2026-11-18"))
        self.assertEqual(botmod.momentum_slot(day("2026-11-18")), day("2026-11-18"))
        last = botmod.momentum_slot(day("2026-11-19")).isoformat()      # opened Thursday, recorded as Wednesday
        self.assertTrue(botmod.momentum_hold_over(last, day("2026-11-24")))

    def test_no_rebalance_yet(self):
        self.assertTrue(botmod.momentum_due(None, day("2026-11-18")))
        self.assertTrue(botmod.momentum_due(None, day("2026-11-19")))
        self.assertFalse(botmod.momentum_due(None, day("2026-11-21")))  # waits for Wednesday
        self.assertIsNone(botmod.momentum_next(None))

    def test_without_a_weekday_it_is_every_seven_days(self):
        last = day("2026-11-03").isoformat()
        self.assertFalse(botmod.momentum_due(last, day("2026-11-09"), weekday=False))
        self.assertTrue(botmod.momentum_due(last, day("2026-11-10"), weekday=False))
        self.assertEqual(botmod.momentum_next(last, weekday=False), day("2026-11-10"))


class PaperWeekTests(unittest.TestCase):
    """The paper bot through a whole week, on a fake exchange: opens Thursday (one day late), records Wednesday,
    closes Tuesday, reopens Wednesday."""

    def test_paper_week(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from test_live_momentum_ls import MomentumFakeBinance, ranked
        td = tempfile.TemporaryDirectory(); self.addCleanup(td.cleanup)
        ex = MomentumFakeBinance()
        state = {"positions": {}, "history": [], "stats": {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0}}
        saved = {}
        clock = {"now": datetime(2026, 11, 19, 0, 5, tzinfo=timezone.utc)}

        class FakeDT(datetime):
            @classmethod
            def now(cls, tz=None): return clock["now"]

        from bots import momentum_ls as mls
        with mock.patch.dict(botmod.CONFIG, {"paper_trading": True, "public_dir": None}),              mock.patch.object(botmod, "load_state", lambda: state),              mock.patch.object(botmod, "save_state", lambda s: saved.update(s)),              mock.patch.object(botmod, "process_paper_closes", lambda *a, **k: None),              mock.patch.object(botmod, "notify", lambda *a, **k: None),              mock.patch.object(botmod, "log", lambda *a, **k: None),              mock.patch.object(botmod, "momentum_rank", lambda ex: ranked()),              mock.patch.object(mls, "datetime", FakeDT):
            mls.run_once_momentum(ex)
            self.assertEqual(state["mom_last"], "2026-11-18T00:00:00+00:00")
            self.assertEqual(len(state["positions"]), 10)
            clock["now"] = datetime(2026, 11, 24, 0, 5, tzinfo=timezone.utc)      # Tuesday
            mls.run_once_momentum(ex)
            self.assertEqual(state["positions"], {})
            clock["now"] = datetime(2026, 11, 25, 0, 5, tzinfo=timezone.utc)      # Wednesday
            mls.run_once_momentum(ex)
            self.assertEqual((state["mom_last"], len(state["positions"])), ("2026-11-25T00:00:00+00:00", 10))


if __name__ == "__main__":
    unittest.main()
