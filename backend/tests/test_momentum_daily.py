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


class LiveKeepTests(unittest.TestCase):
    """Real money (owner, 2026-11-11: both real accounts): a daily rebalance places orders only for the coins that
    change. FakeBinance on Demo settings, the real basket code."""

    def setUp(self):
        import tempfile
        from datetime import timedelta
        from backend.app import risk_manager as rm
        self.rm, self.timedelta = rm, timedelta
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
        botmod.MOM.update(botmod.DAILY)
        botmod._ENTRY_BLOCK["reason"] = ""

    def tearDown(self):
        botmod.CONFIG.clear(); botmod.CONFIG.update(self._cfg)
        botmod.MOM.clear(); botmod.MOM.update(self._mom)
        if self._env is None: os.environ.pop("BINANCE_ENV", None)
        else: os.environ["BINANCE_ENV"] = self._env
        botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH = self._paths
        self.td.cleanup()

    def test_only_the_changes_are_traded(self):
        ex = MomentumFakeBinance()
        with mock.patch.object(botmod, "momentum_rank", return_value=ranked()):
            botmod.run_once_momentum(ex)
        st = botmod.load_state(); self.assertEqual(len(st["positions"]), 10)
        kept_time = st["positions"]["S16/USDT:USDT"]["time"]
        # a day later: S0 moves from the shorts to the longs, S15 drops out, S5 comes in
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        st["mom_last"] = (today - self.timedelta(days=1)).isoformat(); st["recovery_required"] = {}; botmod.save_state(st)
        before = len(ex.orders)
        with mock.patch.object(botmod, "momentum_rank", return_value=ranked()[1:] + ranked()[:1]):
            botmod.run_once_momentum(ex)
        st = botmod.load_state()
        self.assertEqual((len(st["positions"]), st["mom_last"]), (10, today.isoformat()))
        self.assertEqual(st["positions"]["S0/USDT:USDT"]["side"], "long")
        self.assertIn("S5/USDT:USDT", st["positions"]); self.assertNotIn("S15/USDT:USDT", st["positions"])
        self.assertEqual(st["positions"]["S16/USDT:USDT"]["time"], kept_time)            # held, not reopened
        traded = {o["symbol"] for o in ex.orders[before:]}
        self.assertEqual(traded, {"S0/USDT:USDT", "S15/USDT:USDT", "S5/USDT:USDT"})

    def test_nothing_changes_no_order(self):
        ex = MomentumFakeBinance()
        with mock.patch.object(botmod, "momentum_rank", return_value=ranked()):
            botmod.run_once_momentum(ex)
        st = botmod.load_state(); today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        st["mom_last"] = (today - self.timedelta(days=1)).isoformat(); st["recovery_required"] = {}; botmod.save_state(st)
        before = len(ex.orders)
        with mock.patch.object(botmod, "momentum_rank", return_value=ranked()):
            botmod.run_once_momentum(ex)
        self.assertEqual(len(ex.orders), before)
        self.assertEqual(botmod.load_state()["mom_last"], today.isoformat())


class BufferTests(unittest.TestCase):
    """--mom-buffer (research §37): a held coin stays while among the strongest/weakest B; filled back to n."""

    def test_without_a_buffer_the_picks_are_the_ends(self):
        r = ranked()                                     # S0 weakest … S19 strongest
        self.assertEqual(botmod.momentum_picks(r, 5), [(s, x, "short") for s, x in r[:5]] + [(s, x, "long") for s, x in r[::-1][:5]])
        self.assertEqual(botmod.momentum_picks(r, 5, {"S13/USDT:USDT": "long"}, 5), botmod.momentum_picks(r, 5))

    def test_a_held_coin_within_the_buffer_stays(self):
        r = ranked()
        held = {"S13/USDT:USDT": "long", "S12/USDT:USDT": "long", "S6/USDT:USDT": "short", "S4/USDT:USDT": "short"}
        picks = botmod.momentum_picks(r, 5, held, 7)
        longs = [s for s, _, side in picks if side == "long"]; shorts = [s for s, _, side in picks if side == "short"]
        # S13 is 7th strongest: kept; S12 is 8th: out. S6 is 7th weakest: kept; S4 (5th) kept as well
        self.assertIn("S13/USDT:USDT", longs); self.assertNotIn("S12/USDT:USDT", longs)
        self.assertEqual(longs[1:], ["S19/USDT:USDT", "S18/USDT:USDT", "S17/USDT:USDT", "S16/USDT:USDT"])
        self.assertEqual(shorts, ["S4/USDT:USDT", "S6/USDT:USDT", "S0/USDT:USDT", "S1/USDT:USDT", "S2/USDT:USDT"])
        self.assertEqual(len(picks), 10)

    def test_held_on_the_other_side_is_not_kept(self):
        r = ranked()
        picks = botmod.momentum_picks(r, 5, {"S14/USDT:USDT": "short"}, 7)
        self.assertNotIn(("S14/USDT:USDT", "short"), [(s, side) for s, _, side in picks])

    def test_the_cli(self):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("BINANCE", "ALLOW_LIVE", "RAQM_"))}
        e.update({"BINANCE_ENV": "live", "PYTHONIOENCODING": "utf-8"})
        run = lambda *a: subprocess.run([sys.executable, "bot.py", *a], cwd=ROOT, env=e, capture_output=True, timeout=120, encoding="utf-8", errors="replace")
        r = run("--paper", "--strategy", "momentum_daily_b7", "--show-config")
        self.assertEqual(r.returncode, 0, r.stderr); self.assertIn('"buffer": 7', r.stdout); self.assertIn('"public_name": "momentum_daily_b7"', r.stdout)
        for a in (("--live", "--strategy", "momentum_ls", "--mom-daily", "--mom-buffer", "7"), ("--paper", "--strategy", "momentum_ls", "--mom-buffer", "7")):
            r = run(*a); self.assertEqual(r.returncode, 2, a); self.assertIn("--mom-buffer", r.stderr)
        u = (ROOT / "deploy/vps/raqm-momentum-daily-b7.service").read_text(encoding="utf-8")
        self.assertIn("--paper --strategy momentum_daily_b7 --amount 100 --leverage 2", u)
        self.assertIn('id="mbSec"', (ROOT / "deploy/vps/page/index.html").read_text(encoding="utf-8"))


class WiringTests(unittest.TestCase):
    def run_bot(self, *args):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("BINANCE", "ALLOW_LIVE", "RAQM_"))}
        e.update({"BINANCE_ENV": "live", "PYTHONIOENCODING": "utf-8"})
        return subprocess.run([sys.executable, "bot.py", *args], cwd=ROOT, env=e, capture_output=True, timeout=120,
                              encoding="utf-8", errors="replace")

    def test_momentum_ls_only(self):
        for args in (("--paper", "--strategy", "trend_daily", "--mom-daily"), ("--paper", "--strategy", "momentum_ls", "--mom-daily", "--momentum-retail")):
            r = self.run_bot(*args)
            self.assertEqual(r.returncode, 2, args); self.assertIn("--mom-daily", r.stderr, args)

    def test_real_money_runs_it(self):
        r = self.run_bot("--live", "--strategy", "momentum_ls", "--mom-daily", "--show-config")
        self.assertEqual(r.returncode, 0, r.stderr); self.assertIn('"every_days": 1', r.stdout); self.assertIn('"keep": true', r.stdout)
        sys.path.insert(0, str(ROOT / "scripts")); import provision_users as pu
        self.assertIn("--mom-daily", pu.EXTRA_ARGS["momentum_ls"])                    # every user's real bot

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
