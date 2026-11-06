"""A live strategy on its own Binance sub-account (backend/app/live_accounts.py, deploy/vps/tools/live_account.py,
docs/trend-daily-live-plan.md §2): the registry refuses anything ambiguous, the unit's drop-in leaves nothing of the
main account's files in the bot's environment, the tool never moves a running bot or one with open trades, and the
preflight, the watchdog and the backup each look at that account's own files and ledger."""
import json, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts")); sys.path.insert(0, str(ROOT / "deploy" / "vps" / "tools"))
from backend.app import live_accounts as la
from backend.app import risk_manager as rm
import live_account as tool
import live_preflight as lp
import watchdog as wd
import backup

LISTS = ("EnvironmentFile", "ReadWritePaths", "InaccessiblePaths", "LoadCredential", "UnsetEnvironment")


def effective(*texts):
    """systemd's merge of a unit and its drop-ins for the settings these files use: list settings accumulate and an
    empty assignment clears them; Environment= is per variable, the last one wins."""
    lists = {k: [] for k in LISTS}; env = {}
    for text in texts:
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith(("#", "[")) or "=" not in line: continue
            k, v = line.split("=", 1)
            if k in lists:
                if v == "": lists[k] = []
                else: lists[k] += v.split() if k in ("ReadWritePaths", "InaccessiblePaths", "UnsetEnvironment") else [v]
            elif k == "Environment":
                v = v.strip('"'); n, _, val = v.partition("="); env[n] = val
    return lists, env


class RegistryTests(unittest.TestCase):
    def test_a_missing_registry_means_every_strategy_on_the_main_account(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(la.load(Path(d) / "accounts.json"), {})
            self.assertIsNone(la.account_of("momentum_ls", {}))

    def test_anything_ambiguous_is_refused_not_read_as_empty(self):
        for doc in ({"accounts": {"main": {"strategies": ["trend_daily"]}}},       # reserved
                    {"accounts": {"demo": {"strategies": ["trend_daily"]}}},       # /opt/raqm-risk-demo is the Demo ledger
                    {"accounts": {"Trend!": {"strategies": ["trend_daily"]}}},
                    {"accounts": {"a": {"strategies": ["trend_daily"]}}},          # too short
                    {"accounts": {"t1": {"strategies": ["trend_daily"]}, "t2": {"strategies": ["trend_daily"]}}},
                    {"accounts": {"trend": {"strategies": "trend_daily"}}},
                    {"accounts": {"trend": {"strategies": ["../x"]}}},
                    {"accounts": []}, []):
            with self.subTest(doc=doc), self.assertRaises(la.RegistryError):
                la.validate(doc)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "accounts.json"; p.write_text("{not json", encoding="utf-8")
            with self.assertRaises(la.RegistryError): la.load(p)

    def test_dump_and_load_round_trip(self):
        acc = {"trend": ["trend_daily"]}
        self.assertEqual(la.validate(json.loads(la.dump(acc))), acc)
        self.assertEqual(la.account_of("trend_daily", acc), "trend")


class DropinTests(unittest.TestCase):
    BASE = (ROOT / "deploy" / "vps" / "raqm-live@.service").read_text(encoding="utf-8")

    def merged(self, strategy="trend_daily"):
        return effective(self.BASE.replace("%i", strategy), la.dropin_text("trend", strategy))

    def test_nothing_of_the_main_account_reaches_the_bot(self):
        lists, env = self.merged()
        self.assertNotIn("/opt/raqm-live/.env.real", lists["EnvironmentFile"])
        self.assertNotIn("/opt/raqm-live/allow-live.env", lists["EnvironmentFile"])
        self.assertIn("/etc/raqm-live/accounts/trend/allow-live.env", lists["EnvironmentFile"])
        self.assertEqual(env["RAQM_RISK_DIR"], "/opt/raqm-risk-accounts/trend")
        self.assertEqual(lists["LoadCredential"], ["binance:/etc/raqm-live/accounts/trend/binance"])   # keys only from here
        self.assertTrue({"BINANCE_API_KEY", "BINANCE_SECRET"} <= set(lists["UnsetEnvironment"]))
        self.assertNotIn("/opt/raqm-risk", lists["ReadWritePaths"])
        self.assertIn("/opt/raqm-risk-accounts/trend", lists["ReadWritePaths"])
        self.assertTrue({"-/opt/raqm-live/.env.real", "-/opt/raqm-live/allow-live.env", "-/opt/raqm-risk"} <= set(lists["InaccessiblePaths"]))

    def test_the_strategys_own_settings_and_telegram_are_kept(self):
        lists, env = self.merged()
        self.assertIn("-/opt/raqm-live/strategies/trend_daily.env", lists["EnvironmentFile"])
        self.assertIn("-/opt/raqm-live/.env.telegram", lists["EnvironmentFile"])
        self.assertEqual(env["BINANCE_ENV"], "live")

    def test_without_a_drop_in_the_unit_is_unchanged(self):
        lists, env = effective(self.BASE.replace("%i", "momentum_ls"))
        self.assertIn("/opt/raqm-live/.env.real", lists["EnvironmentFile"])
        self.assertEqual(env["RAQM_RISK_DIR"], "/opt/raqm-risk")

    def test_bad_names_never_reach_a_unit_file(self):
        for name, s in (("main", "trend_daily"), ("trend", "x;rm"), ("trend\nX", "trend_daily")):
            with self.subTest(name=name, s=s), self.assertRaises(la.RegistryError):
                la.dropin_text(name, s)


class FakeHost(tool.Host):
    def __init__(self, d):
        super().__init__(registry=d / "etc" / "accounts.json", accounts_dir=d / "etc" / "accounts", risk_root=d / "opt",
                         units=d / "units", main_ledger=d / "opt" / "raqm-risk")
        self.running, self.held, self.reloads = set(), {}, 0
    def active(self, unit): return unit in self.running
    def reload(self): self.reloads += 1
    def chown(self, path, user, group): pass
    def open_risk(self, ledger_dir, strategy): return self.held.get((Path(ledger_dir), strategy), 0)


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.d = Path(self.td.name); self.h = FakeHost(self.d)
    def tearDown(self): self.td.cleanup()
    def dropin(self, s="trend_daily"): return self.h.units / f"raqm-live@{s}.service.d" / "account.conf"

    def test_add_writes_the_drop_in_the_registry_and_the_folders_but_no_key(self):
        tool.main(["add", "trend", "trend_daily"], host=self.h)
        self.assertEqual(la.load(self.h.registry), {"trend": ["trend_daily"]})
        self.assertEqual(self.dropin().read_text(encoding="utf-8"),
                         la.dropin_text("trend", "trend_daily", self.h.accounts_dir, self.h.risk_root))
        self.assertTrue((self.h.accounts_dir / "trend").is_dir() and (self.h.risk_root / "trend").is_dir())
        self.assertFalse((self.h.accounts_dir / "trend" / "binance").exists())          # keys are the owner's to write
        self.assertEqual(self.h.reloads, 1)
        tool.main(["add", "trend", "trend_daily"], host=self.h)                          # again: nothing changes
        self.assertEqual(self.h.reloads, 1)

    def test_a_running_bot_or_one_with_open_trades_never_changes_account(self):
        self.h.running.add("raqm-live@trend_daily")
        with self.assertRaises(SystemExit): tool.main(["add", "trend", "trend_daily"], host=self.h)
        self.h.running.clear(); self.h.held[(self.h.main_ledger, "trend_daily")] = 2
        with self.assertRaises(SystemExit): tool.main(["add", "trend", "trend_daily"], host=self.h)
        self.assertFalse(self.dropin().exists()); self.assertEqual(la.load(self.h.registry), {})

    def test_one_account_per_strategy_and_names_checked(self):
        tool.main(["add", "trend", "trend_daily"], host=self.h)
        with self.assertRaises(SystemExit): tool.main(["add", "other", "trend_daily"], host=self.h)
        for bad in (["add", "main", "rsi2_pullback"], ["add", "Bad", "rsi2_pullback"], ["add", "trend", "../x"]):
            with self.subTest(bad=bad), self.assertRaises(SystemExit): tool.main(bad, host=self.h)

    def test_remove_puts_it_back_on_the_main_account_only_when_flat(self):
        tool.main(["add", "trend", "trend_daily"], host=self.h)
        self.h.held[(self.h.risk_root / "trend", "trend_daily")] = 1
        with self.assertRaises(SystemExit): tool.main(["remove", "trend", "trend_daily"], host=self.h)
        self.assertTrue(self.dropin().exists())
        self.h.held.clear()
        tool.main(["remove", "trend", "trend_daily"], host=self.h)
        self.assertFalse(self.dropin().exists()); self.assertEqual(la.load(self.h.registry), {})


class PreflightAccountTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); t = Path(self.td.name)
        self.paths = {"live": t / "live", "api_env": t / "api.env", "evidence": t / "ev.json", "ledger": t / "risk" / "risk_state.json",
                      "unit": t / "raqm-live@.service", "units": t / "units", "registry": t / "accounts.json",
                      "accounts_dir": t / "accounts", "risk_root": t / "opt"}
        self.paths["live"].mkdir()
        (self.paths["live"] / ".env.real").write_text("BINANCE_API_KEY=mainkey\nBINANCE_SECRET=s\n", encoding="utf-8")
        self.paths["registry"].write_text(la.dump({"trend": ["trend_daily"]}), encoding="utf-8")
        self.acct = self.paths["accounts_dir"] / "trend"; self.acct.mkdir(parents=True)
        (self.paths["risk_root"] / "trend").mkdir(parents=True)
        d = self.paths["units"] / "raqm-live@trend_daily.service.d"; d.mkdir(parents=True)
        (d / "account.conf").write_text(la.dropin_text("trend", "trend_daily", self.paths["accounts_dir"], self.paths["risk_root"]), encoding="utf-8")
        owners = {".env.real": "raqmlive", "binance": "root", "allow-live.env": "root"}
        self.patches = [mock.patch.object(lp, "_owner", lambda p: owners.get(Path(p).name)), mock.patch.object(lp, "_mode", lambda p: 0o600)]
        for p in self.patches: p.start()
    def tearDown(self):
        for p in self.patches: p.stop()
        self.td.cleanup()

    def rows(self, key="trendkey"):
        (self.acct / "binance").write_text(f"BINANCE_API_KEY={key}\nBINANCE_SECRET=s2\n", encoding="utf-8")
        (self.acct / "allow-live.env").write_text("ALLOW_LIVE_TRADING=true\nBINANCE_LIVE_ACCOUNT=trend\n", encoding="utf-8")
        seen = {}
        real = lp.check_binance
        def spy(keys, *a, **k): seen["keys"] = keys; return real(keys, *a, **k)
        with mock.patch.object(lp, "check_binance", spy):
            out = {name: (ok, why) for name, ok, why in lp.run(self.paths, "trend_daily", clients=(PFut(), PSpot()))}
        return out, seen

    def test_the_strategys_own_files_ledger_and_key_are_checked(self):
        out, seen = self.rows()
        self.assertEqual(seen["keys"]["BINANCE_API_KEY"], "trendkey")                   # the account's key, not .env.real's
        self.assertTrue(out["account"][0]); self.assertIn("trend", out["account"][1])
        self.assertTrue(out["raqm-live@trend_daily drop-in for 'trend'"][0])
        self.assertTrue(out["its key is not the main account's"][0])
        self.assertTrue(out["real account keys file"][0])
        self.assertFalse(out["real-money risk ledger"][0]); self.assertIn("trend", out["real-money risk ledger"][1])

    def test_the_main_accounts_key_or_a_changed_drop_in_fails(self):
        out, _ = self.rows(key="mainkey")
        self.assertFalse(out["its key is not the main account's"][0])
        (self.paths["units"] / "raqm-live@trend_daily.service.d" / "account.conf").write_text("[Service]\n", encoding="utf-8")
        out, _ = self.rows()
        self.assertFalse(out["raqm-live@trend_daily drop-in for 'trend'"][0])

    def test_a_broken_registry_is_one_failed_check(self):
        self.paths["registry"].write_text("{", encoding="utf-8")
        rows = lp.run(self.paths, "trend_daily", clients=(PFut(), PSpot()))
        self.assertEqual([(n, ok) for n, ok, _ in rows], [("accounts registry", False)])

    def test_a_missing_ledger_is_reported_never_created(self):
        led = self.paths["risk_root"] / "trend"
        out, _ = self.rows()
        self.assertFalse(out["real-money risk ledger"][0])
        self.assertEqual(list(led.iterdir()), [])
        rm.save_risk_state(led / "risk_state.json", rm._default_state())
        out, _ = self.rows()
        self.assertTrue(out["real-money risk ledger"][0])

    def test_a_strategy_not_in_the_registry_stays_on_the_main_account(self):
        rows = {n: (ok, why) for n, ok, why in lp.run(self.paths, "momentum_ls", clients=(PFut(), PSpot()))}
        self.assertIn("main", rows["account"][1])


class PFut:
    def fetch_position_mode(self): return {"hedged": False}
    def fetch_balance(self): return {"USDT": {"total": 500.0}}
    def fetch_positions(self, symbols=None): return []


class PSpot:
    def sapi_get_account_apirestrictions(self): return {"enableWithdrawals": False, "ipRestrict": True, "enableFutures": True}


class WatchdogAndBackupTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); d = Path(self.td.name)
        self.ipc, self.root = d / "ipc", d / "opt"
        self.ledgers = {"demo": d / "risk-demo", "live": d / "risk"}
        for p in (self.ledgers["live"], self.root / "trend"):
            rm.save_risk_state(p / "risk_state.json", rm._default_state())
        for s in ("momentum_ls", "trend_daily"):
            (self.ipc / s).mkdir(parents=True)
            (self.ipc / s / "live_status.json").write_text(json.dumps({"updated": wd.datetime.now(wd.timezone.utc).isoformat(), "env": "live",
                                                                    "positions": [], "review": {}, "entry_block": ""}), encoding="utf-8")
    def tearDown(self): self.td.cleanup()

    def seen(self, accounts):
        units = {("live", "momentum_ls"): (True, True), ("live", "trend_daily"): (True, True)}
        return wd.problems(wd.datetime.now(wd.timezone.utc), unit=lambda e, s: units.get((e, s), (False, False)), ipc=self.ipc,
                           ledgers=self.ledgers, failed=lambda n: False, accounts=accounts, risk_root=self.root)

    def test_each_account_has_its_own_kill_switch_alert(self):
        self.assertEqual(self.seen({"trend": ["trend_daily"]}), {})
        rm.trip_kill_switch(self.root / "trend" / "risk_state.json", "drawdown 50%")
        out = self.seen({"trend": ["trend_daily"]})
        self.assertIn("kill:live:trend", out); self.assertNotIn("kill:live", out)
        self.assertIn("(trend)", out["kill:live:trend"][0])

    def test_an_unreadable_account_ledger_is_its_own_problem(self):
        out = self.seen({"other": ["trend_daily"]})            # registered, but its ledger doesn't exist yet
        self.assertIn("ledger:live:other", out)
        self.assertFalse((self.root / "other").exists())  # and the watchdog didn't make one

    def test_the_backup_takes_every_accounts_ledger(self):
        src = backup.all_sources(accounts={"trend": ["trend_daily"]}, risk_root=self.root)
        self.assertEqual(src["risk-live-trend"], self.root / "trend")
        self.assertEqual(src["risk-live"], Path("/opt/raqm-risk"))
        self.assertEqual(set(backup.all_sources(accounts={})), set(backup.SOURCES))


if __name__ == "__main__":
    unittest.main()
