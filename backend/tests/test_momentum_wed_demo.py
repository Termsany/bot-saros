"""The momentum day experiment (research/README.md §23, owner 2026-11-06): on Demo, momentum_ls opens on Wednesday
and closes after 6 days (bot.py --mom-weekday 2 --mom-hold 6), flat until the next Wednesday. The defaults — what the
real bot runs — never close early; the two options are refused on real money. FakeBinance only, no network."""
import os, subprocess, sys, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "backend")); sys.path.insert(0, str(Path(__file__).resolve().parent))
import bot as botmod
from backend.app import risk_manager as rm
from test_live_momentum_ls import MomentumFakeBinance, ranked


def day(s):
    return datetime.fromisoformat(s + "T00:00:00+00:00")


class HoldRuleTests(unittest.TestCase):
    def test_a_full_week_never_closes_early(self):
        last = day("2026-11-09").isoformat()
        for d in range(1, 15):
            self.assertFalse(botmod.momentum_hold_over(last, day("2026-11-09") + timedelta(days=d), 7, 7))

    def test_wednesday_six_closes_on_tuesday_and_reopens_on_wednesday(self):
        last = day("2026-11-11").isoformat()                       # a Wednesday basket
        self.assertFalse(botmod.momentum_hold_over(last, day("2026-11-16"), 6, 7))   # Monday: 5 days
        self.assertTrue(botmod.momentum_hold_over(last, day("2026-11-17"), 6, 7))    # Tuesday 00:00: 6 days, close
        self.assertFalse(botmod.momentum_due(last, day("2026-11-17"), 7, 2))         # nothing opens on Tuesday
        self.assertTrue(botmod.momentum_due(last, day("2026-11-18"), 7, 2))          # Wednesday: the next basket
        self.assertEqual(botmod.momentum_next(last, 7, 2), day("2026-11-18"))
        self.assertFalse(botmod.momentum_hold_over(None, day("2026-11-17"), 6, 7))   # no basket yet: nothing to close


class DemoBasketTests(unittest.TestCase):
    def setUp(self):
        self._cfg, self._mom = dict(botmod.CONFIG), dict(botmod.MOM)
        self._env = os.environ.get("BINANCE_ENV"); os.environ["BINANCE_ENV"] = "demo"
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._paths = (botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH)
        botmod.STATE_PATH = Path(self.td.name) / "state.json"; botmod.LOG_PATH = Path(self.td.name) / "t.log"
        botmod.RISK_PATH = Path(self.td.name) / "risk_state.json"
        rm.save_risk_state(botmod.RISK_PATH, rm._default_state({"risk_per_trade_pct": 100.0, "max_aggregate_risk_pct": 100.0,
                           "max_correlated_risk_pct": 100.0, "max_daily_loss_pct": 100.0, "max_drawdown_pct": 100.0}))
        botmod.CONFIG.update({"paper_trading": False, "market": "future", "leverage": 2, "trade_amount_usdt": 100,
                              "enabled_strategies": ["momentum_ls"], "max_open_positions": 50, "public_dir": None})
        botmod._ENTRY_BLOCK["reason"] = ""
        self.today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    def tearDown(self):
        botmod.CONFIG.clear(); botmod.CONFIG.update(self._cfg)
        botmod.MOM.clear(); botmod.MOM.update(self._mom)
        if self._env is None: os.environ.pop("BINANCE_ENV", None)
        else: os.environ["BINANCE_ENV"] = self._env
        botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH = self._paths
        self.td.cleanup()

    def open_basket(self, ex):
        # opened on its own rebalance day (a basket opens only in its week's first days, momentum_due)
        with mock.patch.object(botmod, "momentum_rank", return_value=ranked()), mock.patch.dict(botmod.MOM, {"weekday": self.today.weekday()}):
            botmod.run_once_momentum(ex)
        self.assertEqual(len(botmod.load_state()["positions"]), 10)

    def age(self, days):
        st = botmod.load_state(); st["mom_last"] = (self.today - timedelta(days=days)).isoformat(); st["recovery_required"] = {}
        botmod.save_state(st)

    def test_after_six_days_the_basket_closes_and_nothing_opens_until_its_day(self):
        botmod.MOM.update({"weekday": (self.today.weekday() + 1) % 7, "hold_days": 6})   # tomorrow is the rebalance day
        ex = MomentumFakeBinance(); self.open_basket(ex)
        self.age(6)
        with mock.patch.object(botmod, "momentum_rank", return_value=ranked()) as rank:
            botmod.run_once_momentum(ex)
        st = botmod.load_state()
        self.assertEqual(st["positions"], {})
        self.assertEqual([k for k in rm.load_risk_state(botmod.RISK_PATH)["open_risk"] if k.startswith("momentum_ls:")], [])
        rank.assert_not_called()                                    # flat until the next rebalance day
        self.assertEqual(sum(1 for h in st["history"]), 10)         # each leg booked as closed

    def test_on_its_day_the_next_basket_opens(self):
        botmod.MOM.update({"weekday": self.today.weekday(), "hold_days": 6})
        ex = MomentumFakeBinance(); self.open_basket(ex)
        self.age(7)                                                  # last week's basket, closed on day 6 in real life
        with mock.patch.object(botmod, "momentum_rank", return_value=ranked()):
            botmod.run_once_momentum(ex)                            # hold over → closed, then today's rebalance opens
        self.assertEqual(len(botmod.load_state()["positions"]), 10)

    def test_the_full_week_never_closes_early(self):
        botmod.MOM.update({"hold_days": 7})                         # a full week's hold (the crowd bot's)
        ex = MomentumFakeBinance(); self.open_basket(ex)
        botmod.MOM.update({"weekday": (self.today.weekday() + 1) % 7})
        self.age(6)
        botmod.run_once_momentum(ex)
        self.assertEqual(len(botmod.load_state()["positions"]), 10)


class DeployAndWatchTests(unittest.TestCase):
    VPS = ROOT / "deploy" / "vps"

    def test_the_unit_is_demo_with_its_own_folder_and_state(self):
        u = (self.VPS / "raqm-demo-momwed.service").read_text(encoding="utf-8")
        self.assertIn("--live --expect-env demo --strategy momentum_ls --mom-weekday 2 --mom-hold 6", u)
        self.assertIn("Environment=BINANCE_ENV=demo", u); self.assertIn("EnvironmentFile=/opt/raqm-live/.env.live", u)
        self.assertNotIn(".env.real", u); self.assertNotIn("allow-live", u)
        self.assertIn("RAQM_IPC_DIR=/opt/raqm-ipc/momentum_wed", u); self.assertIn("RAQM_RISK_DIR=/opt/raqm-risk-demo", u)
        self.assertIn("--state state/demo-momentum_wed.json", u)
        self.assertIn("Conflicts=raqm-demo@momentum_ls.service", u)

    def test_setup_installs_it_and_its_folder_but_never_starts_it(self):
        s = (self.VPS / "setup-live.sh").read_text(encoding="utf-8")
        self.assertIn("/etc/systemd/system/raqm-demo-momwed.service", s)
        self.assertNotRegex(s, r"(enable|start|restart)[^\n]*raqm-demo-momwed")
        self.assertRegex(s, r"for s in [^\n]*momentum_wed; do")

    def test_the_watchdog_watches_it_as_a_demo_bot(self):
        sys.path.insert(0, str(ROOT / "scripts")); import watchdog as wd
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as d:
            ledgers = {"demo": Path(d) / "demo", "live": Path(d) / "live"}
            rm.save_risk_state(ledgers["demo"] / "risk_state.json", rm._default_state())
            units = {("demo", "momentum_wed"): (True, False)}
            out = wd.problems(now, unit=lambda e, s: units.get((e, s), (False, False)), ipc=Path(d) / "ipc", ledgers=ledgers,
                              failed=lambda n: False, accounts={})
            self.assertIn("down:demo:momentum_wed", out)
        names = []
        with mock.patch.object(wd.subprocess, "run", side_effect=lambda a, **k: names.append(a[-1]) or mock.Mock(stdout="")):
            wd.unit("demo", "momentum_wed"); wd.unit("demo", "trend_daily"); wd.unit("live", "momentum_ls")
        self.assertEqual(names[::2], ["raqm-demo-momwed", "raqm-demo@trend_daily", "raqm-live@momentum_ls"])


class RealMoneyRefusedTests(unittest.TestCase):
    def run_bot(self, env, *args):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("BINANCE", "ALLOW_LIVE", "RAQM_"))}
        e.update({"BINANCE_ENV": env, "PYTHONIOENCODING": "utf-8"})
        return subprocess.run([sys.executable, "bot.py", *args], cwd=ROOT, env=e, capture_output=True, timeout=120,
                              encoding="utf-8", errors="replace")

    def test_the_experiment_options_are_refused_on_real_money(self):
        for args in (("--live", "--strategy", "momentum_ls", "--mom-hold", "6"), ("--live", "--strategy", "momentum_ls", "--mom-weekday", "2"),
                     ("--strategy", "momentum_ls", "--mom-hold", "6")):
            r = self.run_bot("live", *args)
            self.assertEqual(r.returncode, 2, args)
            self.assertIn("Demo", r.stderr, args)


if __name__ == "__main__":
    unittest.main()
