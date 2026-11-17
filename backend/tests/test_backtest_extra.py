"""The rest of the paper bots on the backtest page (owner, 2026-11-17): research/extra_bots_stats.py writes their numbers
(lib/extra-stats.json) and trades (data/extra-trades.json); the site lists them (lib/strategies.ts EXTRA_DETAILS) and
app/api/bot-trades serves them to every plan. The three must name the same bots."""
import json, re, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


class ExtraBacktestTests(unittest.TestCase):
    def setUp(self):
        self.stats = json.loads((ROOT / "lib" / "extra-stats.json").read_text(encoding="utf-8"))
        self.trades = json.loads((ROOT / "data" / "extra-trades.json").read_text(encoding="utf-8"))
        ts = (ROOT / "lib" / "strategies.ts").read_text(encoding="utf-8")
        block = ts[ts.index("const EXTRA_DETAILS"):ts.index("const EXTRA_MEASURED")]
        self.site = re.findall(r"^  (\w+): \{ name:", block, flags=re.M)

    def test_the_same_bots_everywhere(self):
        self.assertEqual(len(self.site), 10)
        self.assertEqual(list(self.stats["bots"]), self.site)
        self.assertEqual(list(self.trades["trades"]), self.site)

    def test_x2_only_and_the_planned_four_are_not_here(self):
        plans = {"trend_daily", "momentum_ls", "listing_short", "ratio_trend"}
        self.assertFalse(plans & set(self.site))
        for k, by_lev in self.trades["trades"].items():
            self.assertEqual(list(by_lev), ["2"], k)
            self.assertGreater(len(by_lev["2"]), 100, k)
            self.assertEqual(round(sum(r[6] for r in by_lev["2"]), 0), round(self.stats["bots"][k]["pnl"], 0), k)

    def test_the_route_opens_them_to_every_plan(self):
        route = (ROOT / "app" / "api" / "bot-trades" / "route.ts").read_text(encoding="utf-8")
        self.assertIn('import EXTRA from "@/data/extra-trades.json"', route)
        self.assertIn("if(!open && idx >= count)", route)              # the plan check skips them
        self.assertIn("backtestSpanDays(from, to) > maxDays", route)    # the day limit does not


if __name__ == "__main__":
    unittest.main()
