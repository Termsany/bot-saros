"""momentum_ls rebalances at the first cycle after 00:00 UTC on Monday (owner, 2026-11-03), not every 7 days from
whenever it started: a basket opened on Tuesday 2026-11-03 is rebuilt on Monday 2026-11-09. Never twice on one day; a
missed Monday (bot down all day) is caught up once 7 days have passed; no rebalance yet means now."""
import sys, unittest
from datetime import datetime, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
import bot as botmod


def day(s):
    return datetime.fromisoformat(s + "T00:00:00+00:00")


class MomentumScheduleTests(unittest.TestCase):
    def test_monday_is_the_anchor(self):
        self.assertEqual(botmod.MOM["weekday"], 0)
        self.assertEqual(day("2026-11-09").weekday(), 0)          # the first Monday after the live start

    def test_a_tuesday_basket_is_rebuilt_on_the_next_monday(self):
        last = day("2026-11-03").isoformat()                      # Tuesday, the first real basket
        for d in ("2026-11-04", "2026-11-05", "2026-11-06", "2026-11-07", "2026-11-08"):
            self.assertFalse(botmod.momentum_due(last, day(d)), d)
        self.assertTrue(botmod.momentum_due(last, day("2026-11-09")))
        self.assertEqual(botmod.momentum_next(last), day("2026-11-09"))

    def test_never_twice_on_one_monday(self):
        last = day("2026-11-09").isoformat()
        self.assertFalse(botmod.momentum_due(last, day("2026-11-09")))
        self.assertTrue(botmod.momentum_due(last, day("2026-11-16")))
        self.assertEqual(botmod.momentum_next(last), day("2026-11-16"))

    def test_a_missed_monday_is_caught_up_after_seven_days(self):
        last = day("2026-11-09").isoformat()
        self.assertFalse(botmod.momentum_due(last, day("2026-11-15")))   # Sunday, 6 days
        self.assertTrue(botmod.momentum_due(last, day("2026-11-17")))    # Tuesday: Monday 16 was missed

    def test_no_rebalance_yet_is_now(self):
        self.assertTrue(botmod.momentum_due(None, day("2026-11-04")))
        self.assertIsNone(botmod.momentum_next(None))

    def test_without_a_weekday_it_is_every_seven_days(self):
        last = day("2026-11-03").isoformat()
        self.assertFalse(botmod.momentum_due(last, day("2026-11-09"), weekday=None))
        self.assertTrue(botmod.momentum_due(last, day("2026-11-10"), weekday=None))
        self.assertEqual(botmod.momentum_next(last, weekday=None), day("2026-11-10"))


if __name__ == "__main__":
    unittest.main()
