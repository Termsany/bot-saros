"""The Demo-vs-baseline table (backend/app/demo_measure.py, owner 2026-11-01): samples and rules agreed before any result."""
import json, os, sys, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "backend")); sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend.app import demo_measure as dm
import bot as botmod

NOW = datetime(2026, 12, 1, tzinfo=timezone.utc)
BASE = {"strategies": {"trend_daily": {"all": {"win_rate": 30.4, "avg_loss_pct": -11.0, "profit_factor": 2.2, "max_dd_margins": 15.6}},
                       "rsi2_pullback": {"all": {"win_rate": 65.4, "avg_loss_pct": -10.0, "profit_factor": 1.73, "max_dd_margins": 2.4}}}}


def row(day, pct, **kw):
    t = datetime(2026, 11, 1, tzinfo=timezone.utc) + timedelta(days=day)
    return {"symbol": "X/USDT:USDT", "opened": (t - timedelta(hours=5)).isoformat(), "time": t.isoformat(), "pnl_pct": pct, "reason": "إشارة", **kw}


class CountedTests(unittest.TestCase):
    def test_only_the_strategies_own_exits_since_the_start_count(self):
        rows = [row(1, 10.0),
                row(2, 5.0, reason="قفل يدوي من الموقع", by="owner@example.com"),
                row(3, -4.0, reason="قفل يدوي من Binance"),
                row(4, -11.0, reason="وقف المنصة"),
                {**row(5, 3.0), "opened": "2026-10-30T02:46:12+00:00"},                # opened before the start
                {"time": "2026-10-30T04:26:45+00:00", "opened": "2026-10-30T02:00:00+00:00", "pnl_pct": 4.0},
                {**row(6, 1.0), "pnl_pct": None}]
        self.assertEqual([p for _, p in dm.counted(rows)], [10.0, -11.0])

    def test_the_figures_are_in_the_baselines_units(self):
        st = dm.stats(dm.counted([row(1, 50.0), row(2, -10.0), row(3, -20.0), row(4, 40.0)]), NOW)
        self.assertEqual((st["trades"], st["win_rate"], st["avg_win_pct"], st["avg_loss_pct"], st["profit_factor"]), (4, 50.0, 45.0, -15.0, 3.0))
        self.assertEqual((st["max_dd_margins"], st["net_margins"]), (0.3, 0.6))          # +0.5, then −0.1 −0.2


class VerdictTests(unittest.TestCase):
    def table(self, s, pcts):
        return dm.measure({s: [row(i % 28, p) for i, p in enumerate(pcts)]}, BASE, NOW)["strategies"][s]

    def test_samples_agreed_before_any_result(self):
        self.assertEqual({s: dm.SAMPLE[s] for s in ("trend_daily", "ratio_trend", "vol_breakout", "trend_breakout")}, dict.fromkeys(
            ("trend_daily", "ratio_trend", "vol_breakout", "trend_breakout"), 30))
        self.assertEqual((dm.SAMPLE["rsi2_pullback"], dm.SAMPLE["listing_short"], dm.SAMPLE["momentum_ls"]), (15, 15, None))

    def test_collecting_until_the_sample_then_in_range(self):
        self.assertEqual(self.table("trend_daily", [50.0, -10.0] * 5)["status"], "collecting")
        self.assertEqual(self.table("trend_daily", [55.0, -11.0, -11.0] * 10)["status"], "in_range")

    def test_far_after_the_sample_when_profit_factor_under_one(self):
        t = self.table("trend_daily", [10.0, -11.0, -11.0] * 10)
        self.assertEqual(t["status"], "far"); self.assertIn("profit factor", t["reasons"][0])

    def test_far_when_the_drawdown_is_over_one_and_a_half_times_the_baseline(self):
        t = self.table("rsi2_pullback", [-40.0] * 10 + [100.0] * 5)       # −4 margins against 2.4 × 1.5 = 3.6
        self.assertEqual(t["status"], "far"); self.assertIn("التراجع", t["reasons"][0])

    def test_a_drawdown_past_the_limit_shows_before_the_sample_without_a_verdict(self):
        t = self.table("rsi2_pullback", [-40.0] * 10)
        self.assertEqual(t["status"], "attention")

    def test_a_win_rate_far_from_the_baseline_is_a_look_not_a_verdict(self):
        t = self.table("trend_daily", [30.0, 30.0, -11.0] * 10)            # 66.7% against 30.4%
        self.assertEqual(t["status"], "attention"); self.assertIn("نسبة الكسب", t["reasons"][0])

    def test_momentum_is_not_measured(self):
        self.assertEqual(self.table("momentum_ls", [10.0] * 40)["status"], "not_measured")


class ClosedFileTests(unittest.TestCase):
    """live_status.json keeps the last 30 closed trades only; the measurement needs every one."""
    def test_the_bot_writes_every_closed_trade_once_per_change(self):
        state = {"positions": {}, "history": [{**row(i, 1.0), "type": "live", "entry": 1, "qty": 1} for i in range(40)] + [{"type": "paper"}]}
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d, mock.patch.dict(botmod._CLOSED_WRITTEN, {"n": None}), \
             mock.patch.object(botmod, "_write_json_atomic", wraps=botmod._write_json_atomic) as w:
            botmod._write_closed(Path(d), state); botmod._write_closed(Path(d), state)
            doc = json.loads((Path(d) / "closed.json").read_text(encoding="utf-8"))
        self.assertEqual(w.call_count, 1)
        self.assertEqual(len(doc["closed"]), 40); self.assertEqual(set(doc["closed"][0]), {"symbol", "side", "opened", "time", "pnl", "pnl_pct", "reason", "by"})


class EndpointTests(unittest.TestCase):
    def test_the_admin_endpoint_reads_demo_files_only(self):
        from test_security import ApiAuthTests
        import app.main as m
        t = ApiAuthTests(); t.setUp()
        try:
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d, mock.patch.object(m, "IPC_DIR", Path(d)):
                for s, env in (("trend_daily", "demo"), ("vol_breakout", "live")):
                    (Path(d) / s).mkdir()
                    (Path(d) / s / "closed.json").write_text(json.dumps({"env": env, "closed": [row(1, 10.0)]}), encoding="utf-8")
                self.assertEqual(t.c.get("/api/live/measurement", headers=t.h("user-token")).status_code, 403)
                r = t.c.get("/api/live/measurement", headers=t.h("admin-token")).json()
            self.assertTrue(r["baseline_available"])
            self.assertEqual((r["strategies"]["trend_daily"]["demo"]["trades"], r["strategies"]["vol_breakout"]["demo"]["trades"]), (1, 0))
            self.assertEqual(r["strategies"]["trend_daily"]["baseline"]["profit_factor"], 2.2)
        finally:
            t.tearDown()


if __name__ == "__main__":
    unittest.main()
