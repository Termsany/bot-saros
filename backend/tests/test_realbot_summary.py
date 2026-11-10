"""realbot.da3m.io's summary (development-plan 7.1) compares the real basket with the backtest: the page's numbers are
the baseline's (lib/demo-baseline.json), never typed in apart from it."""
import json, re, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent


class RealbotSummaryTests(unittest.TestCase):
    def test_the_pages_backtest_numbers_are_the_baselines(self):
        html = (ROOT / "deploy" / "vps" / "realbot" / "index.html").read_text(encoding="utf-8")
        m = re.search(r"const BACKTEST = \{momentum_ls: \{([^}]*)\}\}", html)
        self.assertIsNotNone(m)
        page = {k: float(v) for k, v in re.findall(r"(\w+): (-?[\d.]+)", m.group(1))}
        base = json.loads((ROOT / "lib" / "demo-baseline.json").read_text(encoding="utf-8"))["strategies"]["momentum_ls"]["all"]
        self.assertEqual(page, {k: base[k] for k in page})
        self.assertEqual(set(page), {"win_rate", "avg_win_pct", "avg_loss_pct", "profit_factor"})

    def test_the_summary_waits_for_the_measurements_sample(self):
        html = (ROOT / "deploy" / "vps" / "realbot" / "index.html").read_text(encoding="utf-8")
        self.assertIn("const SAMPLE = 30", html)
        self.assertIn('$("summary").innerHTML = summary(D.bots)', html)


if __name__ == "__main__":
    unittest.main()
