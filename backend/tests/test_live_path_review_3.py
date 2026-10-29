"""Fixes from the pre-production review, part 3 (2026-10-29): trade and funding history over the whole holding
period, fees in other coins, the single-leg rejected-stop path, and the real-orders deploy script."""
import os, shutil, subprocess, sys, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import bot as botmod
from backend.app import risk_manager as rm
from test_trend_live import FakeBinance

SYM = "SOL/USDT:USDT"
DAY = 86_400_000


class WindowedTrades:
    """Like Binance userTrades: a query never reaches past since+7d, and returns at most ``limit`` rows."""
    def __init__(self, rows): self.rows, self.calls = rows, []
    def fetch_my_trades(self, sym, since=None, limit=500, params=None):
        until = (params or {}).get("until", since + 7 * DAY - 1)
        self.calls.append((since, until)); assert until - since < 7 * DAY, "window longer than 7 days"
        return [r for r in self.rows if since <= r["timestamp"] <= until][:limit]


class TradeHistoryTests(unittest.TestCase):
    def test_closing_fill_of_a_long_hold_is_found(self):
        opened = datetime.now(timezone.utc) - timedelta(days=10)
        t0 = int(opened.timestamp() * 1000)
        ex = WindowedTrades([{"id": "1", "timestamp": t0 + 1000, "side": "buy", "amount": 5.0, "price": 100.0, "fee": {"cost": 0.2}},
                             {"id": "2", "timestamp": t0 + 9 * DAY, "side": "sell", "amount": 5.0, "price": 90.0, "fee": {"cost": 0.18}}])
        fill = botmod._authoritative_close_fill(ex, SYM, {"time": opened.isoformat(), "side": "long", "qty": 5.0})
        self.assertIsNotNone(fill); self.assertEqual(fill["price"], 90.0)
        self.assertGreaterEqual(len(ex.calls), 2)

    def test_a_full_page_is_continued(self):
        t0 = int((datetime.now(timezone.utc) - timedelta(days=2)).timestamp() * 1000)
        rows = [{"id": str(i), "timestamp": t0 + i, "side": "sell", "amount": 1.0, "price": 1.0} for i in range(25)]
        with mock.patch.object(botmod, "HISTORY_PAGE", 10):
            self.assertEqual(len(botmod._trades_since(WindowedTrades(rows), SYM, t0)), 25)


class FundingHistoryTests(unittest.TestCase):
    def test_every_page_is_counted(self):
        t0 = 1_700_000_000_000
        rows = [{"id": str(i), "timestamp": t0 + i * 8 * 3600_000, "amount": -0.01} for i in range(250)]
        def fetch(sym, since=None, limit=100):
            return [r for r in rows if since is None or r["timestamp"] >= since][:limit]
        with mock.patch.object(botmod, "HISTORY_PAGE", 100):
            got = botmod._funding_since(fetch, SYM, t0)
        self.assertEqual(len(got), 250); self.assertAlmostEqual(sum(r["amount"] for r in got), -2.5)


class FeeTests(unittest.TestCase):
    def test_fee_in_another_coin_is_unknown_not_dollars(self):
        self.assertIsNone(botmod._usdt_fee_cost({"fee": {"cost": 0.0003, "currency": "BNB"}}))
        self.assertIsNone(botmod._usdt_fee_cost({"fee": None}))
        self.assertEqual(botmod._usdt_fee_cost({"fee": {"cost": 0.04, "currency": "USDT"}}), 0.04)

    def test_unknown_entry_fee_is_not_zero(self):
        pos = {"entry": 100.0, "qty": 1.0, "contract_size": 1.0, "entry_fee_cost": None, "entry_fee_rate": None}
        close = {"average": 110.0, "filled": 1.0, "fee": {"cost": 0.044, "currency": "USDT"}}
        with self.assertRaises(RuntimeError): botmod._refresh_fee_evidence(None, SYM, pos, close)


class RejectedStopTests(unittest.TestCase):
    def setUp(self):
        self._cfg = dict(botmod.CONFIG); self._env = os.environ.get("BINANCE_ENV"); os.environ["BINANCE_ENV"] = "demo"
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._saved = (botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH)
        botmod.STATE_PATH = Path(self.td.name) / "s.json"; botmod.LOG_PATH = Path(self.td.name) / "l.log"; botmod.RISK_PATH = Path(self.td.name) / "r.json"
        rm.save_risk_state(botmod.RISK_PATH, rm._default_state({"risk_per_trade_pct": 100.0, "max_aggregate_risk_pct": 100.0,
            "max_correlated_risk_pct": 100.0, "max_daily_loss_pct": 100.0, "max_drawdown_pct": 100.0}))
        botmod.CONFIG.update({"paper_trading": False, "market": "future", "leverage": 2, "trade_amount_usdt": 100, "use_percent_risk": False})
        botmod._ENTRY_BLOCK["reason"] = ""
        self.notified = []
        for target, value in (("notify", self.notified.append), ("_live_activation_gate", lambda s: (True, "")),
                              ("_refresh_funding_evidence", lambda *a, **k: None)):
            p = mock.patch.object(botmod, target, value); p.start(); self.addCleanup(p.stop)
        self.state = botmod.load_state()
    def tearDown(self):
        botmod.CONFIG.clear(); botmod.CONFIG.update(self._cfg)
        if self._env is None: os.environ.pop("BINANCE_ENV", None)
        else: os.environ["BINANCE_ENV"] = self._env
        botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH = self._saved; botmod._ENTRY_BLOCK["reason"] = ""
        self.td.cleanup()

    def enter(self, ex):
        return botmod._single_leg_live_entry(ex, self.state, SYM, "long", 100.0, 100.0, 60.0, None, "rsi2_pullback")

    def test_closed_at_once_releases_the_reservation(self):
        ex = FakeBinance(fail_stop=True)
        self.assertIsNone(self.enter(ex))
        self.assertEqual(ex.positions["SOL/USDT"], 0.0)
        self.assertEqual(list(rm.load_risk_state(botmod.RISK_PATH)["open_risk"]), [])
        self.assertNotIn(SYM, self.state.get("recovery_required", {})); self.assertNotIn(SYM, self.state["positions"])

    def test_failed_close_is_recovery_with_an_alert(self):
        ex = FakeBinance(fail_stop=True, fail_close=True)
        self.assertIsNone(self.enter(ex))
        self.assertIn(SYM, self.state["recovery_required"]); self.assertTrue(self.notified)
        self.assertEqual(rm.load_risk_state(botmod.RISK_PATH)["open_risk"][f"rsi2_pullback:{SYM}"]["status"], "recovery")


class SetupLiveScriptTests(unittest.TestCase):
    SCRIPT = ROOT / "deploy" / "vps" / "setup-live.sh"

    def test_code_comes_from_a_pinned_commit_not_writable_folders(self):
        s = self.SCRIPT.read_text(encoding="utf-8")
        self.assertIn('git -C "$SRC" archive "$SHA"', s)
        for writable in ('"$B/$f"', '"$B/backend/app', "/opt/raqm-api/app/scripts", '"$B/venv/bin/pip"', "/opt/raqm-api/venv/bin/python"):
            self.assertNotIn(writable, s)

    @unittest.skipUnless(shutil.which("sh"), "no POSIX sh")
    def test_refuses_without_a_full_commit_sha(self):
        for args in ([], ["main"], ["abc123"]):
            r = subprocess.run(["sh", str(self.SCRIPT), *args], capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 2, args); self.assertIn("usage", r.stderr)


if __name__ == "__main__":
    unittest.main()
