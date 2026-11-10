"""One list of strategies (lib/strategies.json, development-plan 3.4).

The site and the API read the file. bot.py, the modules the real-money bot imports and the server scripts keep their
own lists (nothing to read at start-up on the order path), so this checks every one of them against the file: a
strategy added, renamed or dropped in one place and not the others fails CI.
"""
import ast, json, re, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from app import strategy_catalog as sc

CAT = json.loads((ROOT / "lib" / "strategies.json").read_text(encoding="utf-8"))["strategies"]
IDS = [s["id"] for s in CAT]


def assigned(path, name):
    """The literal value assigned to `name` at the top of a Python file, read without importing it."""
    for node in ast.parse((ROOT / path).read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {path}")


class StrategyCatalogTests(unittest.TestCase):
    def test_the_file_is_well_formed(self):
        self.assertEqual(len(IDS), len(set(IDS)))
        for s in CAT:
            self.assertEqual(set(s), {"id", "name", "nameAr", "live", "planned", "demoSample"}, s["id"])
            self.assertRegex(s["live"], r"^[a-z0-9]+$")
        planned = [s["planned"] for s in CAT]
        self.assertEqual(planned, sorted(planned, reverse=True), "planned strategies come first: the plans unlock them in order")
        self.assertEqual(len({s["live"] for s in CAT}), len(CAT))

    def test_the_api_reads_it(self):
        import app.main as m
        from app import admin_control, demo_measure, live_bots_feed
        self.assertEqual(list(m.LIVE_STRATEGIES), IDS)
        self.assertEqual(m.STRATEGY_ORDER, [s["id"] for s in CAT if s["planned"]])
        self.assertEqual(admin_control.STRATEGIES, (*IDS, "default"))
        self.assertEqual(demo_measure.SAMPLE, {s["id"]: s["demoSample"] for s in CAT})
        self.assertEqual(live_bots_feed.STRATEGY_FILES, {s["id"]: s["live"] + ".json" for s in CAT})
        self.assertEqual(sc.NAME_AR["trend_daily"], "ترند يومي")

    def test_the_real_money_bot_and_its_modules_match(self):
        self.assertEqual(assigned("bot.py", "LIVE_READY_STRATEGIES"), set(IDS))
        self.assertEqual(set(assigned("backend/app/user_bots.py", "STRATEGIES")), set(IDS))
        self.assertEqual(set(assigned("backend/app/testnet_readiness.py", "ALL_STRATEGIES")), {*IDS, "default"})

    def test_the_server_scripts_match(self):
        for path in ("scripts/watchdog.py", "scripts/live_report.py", "scripts/realbot_export.py"):
            self.assertEqual(set(assigned(path, "STRATEGIES")), set(IDS), path)
        e2e = (ROOT / "scripts" / "demo_e2e.py").read_text(encoding="utf-8")
        listed = re.search(r'for st in \(([^)]*)\)\]', e2e).group(1)
        self.assertEqual(set(re.findall(r'"([a-z0-9_]+)"', listed)), set(IDS))

    def test_the_numbers_the_site_shows_cover_every_strategy(self):
        baseline = json.loads((ROOT / "lib" / "demo-baseline.json").read_text(encoding="utf-8"))["strategies"]
        self.assertEqual(set(baseline), set(IDS))
        stats = json.loads((ROOT / "lib" / "bot-stats.json").read_text(encoding="utf-8"))["bots"]
        self.assertTrue({s["id"] for s in CAT if s["planned"]} <= set(stats))
        self.assertEqual(set(assigned("research/baseline_stats.py", "LABELS")), set(IDS))

    def test_no_page_keeps_its_own_strategy_names(self):
        """The site's names come from the file (lib/strategies.ts NAME_AR): a page with its own list drifts (the admin
        page had two, with different names for the same strategy, 2026-11-04)."""
        for f in [*(ROOT / "components").glob("*.tsx"), *(ROOT / "app").rglob("*.tsx")]:
            text = f.read_text(encoding="utf-8")
            listed = re.findall(r'\b(?:%s)\s*:\s*"[^"]*[\u0600-\u06FF][^"]*"' % "|".join(IDS), text)
            self.assertEqual(listed, [], f"{f.relative_to(ROOT)} names strategies itself: use NAME_AR from lib/strategies")

    def test_the_plans_unlock_exactly_the_planned_ones(self):
        ts = (ROOT / "lib" / "strategies.ts").read_text(encoding="utf-8")
        counts = [int(c) for c in re.findall(r'count:(\d+)', ts)]
        self.assertEqual(max(counts), sum(1 for s in CAT if s["planned"]))
        self.assertIn('import CATALOG from "./strategies.json"', ts)


if __name__ == "__main__":
    unittest.main()
