"""The Demo measurement baseline (research/baseline_stats.py): per-trade results as % of margin, drawdown in margins."""
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "research"))
import baseline_stats as bl

DAY = 86_400_000


class BaselineStatsTests(unittest.TestCase):
    def test_units(self):
        t0 = 1_704_067_200_000                                             # 2024-01-01
        trades = [{"entry_ts": t0, "exit_ts": t0 + DAY, "pnl": 10.0},        # +50% of a $20 margin
                  {"entry_ts": t0 + 2 * DAY, "exit_ts": t0 + 3 * DAY, "pnl": -20.0},
                  {"entry_ts": t0 + 4 * DAY, "exit_ts": t0 + 61 * DAY, "pnl": 4.0}]
        r = bl.stats(trades)["all"]
        self.assertEqual((r["trades"], r["win_rate"], r["avg_win_pct"], r["avg_loss_pct"]), (3, 66.7, 35.0, -100.0))
        self.assertEqual((r["profit_factor"], r["max_dd_margins"], r["net_margins"]), (0.7, 1.0, -0.3))
        self.assertEqual(bl.stats(trades)["max_open"], 1)


if __name__ == "__main__":
    unittest.main()
