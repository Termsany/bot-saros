"""One more copy of a live strategy on its own Binance sub-account (owner, 2026-11-07: momentum_ls on a second account
of $300 next to the main one). The copy gets its own unit, status folder, state, keys and ledger; the main account's
bot and files never change. The registry, the tool, the preflight, the watchdog, the backup, the check and the API
each follow the copy on its own."""
import json, os, sys, tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "backend")); sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "deploy" / "vps" / "tools")); sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend.app import live_accounts as la
from backend.app import risk_manager as rm
import live_account as tool
import live_preflight as lp
import watchdog as wd
import backup
import rebalance_check as rc
from test_live_accounts import effective, FakeHost, PFut, PSpot
from test_security import ApiAuthTests
from test_admin_live_strategies import trusted_evidence

DOC = {"accounts": {"trend": {"strategies": ["trend_daily"]}}, "copies": {"mom2": {"strategies": ["momentum_ls"]}}}


class RegistryTests(unittest.TestCase):
    def test_a_copy_runs_a_strategy_the_main_account_keeps(self):
        self.assertEqual(la.validate(DOC), {"trend": ["trend_daily"]})               # load() is unchanged
        self.assertEqual(la.validate_copies(DOC), {"mom2": ["momentum_ls"]})
        self.assertIsNone(la.account_of("momentum_ls", la.validate(DOC)))             # momentum stays on main

    def test_ambiguous_copies_are_refused(self):
        for doc in ({"copies": {"trend": {"strategies": ["momentum_ls"]}}, "accounts": {"trend": {"strategies": ["trend_daily"]}}},
                    {"copies": {"mom2": {"strategies": []}}}, {"copies": {"main": {"strategies": ["momentum_ls"]}}},
                    {"copies": {"mom2": {"strategies": ["../x"]}}}, {"copies": []}):
            with self.subTest(doc=doc), self.assertRaises(la.RegistryError):
                la.validate(doc)

    def test_load_copies_and_dump_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "accounts.json"
            self.assertEqual(la.load_copies(p), {})
            p.write_text(la.dump(la.validate(DOC), la.validate_copies(DOC)), encoding="utf-8")
            self.assertEqual(la.load_copies(p), {"mom2": ["momentum_ls"]}); self.assertEqual(la.load(p), {"trend": ["trend_daily"]})

    def test_the_copy_unit_uses_only_its_own_account(self):
        lists, env = effective(la.copy_unit_text("mom2").replace("%i", "momentum_ls"))
        self.assertEqual(lists["EnvironmentFile"], ["-/opt/raqm-live/.env.telegram", "/etc/raqm-live/accounts/mom2/allow-live.env",
                                                    "-/opt/raqm-live/strategies/mom2-momentum_ls.env"])
        self.assertEqual(lists["LoadCredential"], ["binance:/etc/raqm-live/accounts/mom2/binance"])
        self.assertTrue({"BINANCE_API_KEY", "BINANCE_SECRET"} <= set(lists["UnsetEnvironment"]))
        self.assertEqual(env["RAQM_IPC_DIR"], "/opt/raqm-ipc/acct-mom2/momentum_ls")
        self.assertEqual(env["RAQM_RISK_DIR"], "/opt/raqm-risk-accounts/mom2"); self.assertEqual(env["BINANCE_ENV"], "live")
        self.assertTrue({"-/opt/raqm-live/.env.real", "-/opt/raqm-live/allow-live.env", "-/opt/raqm-risk"} <= set(lists["InaccessiblePaths"]))
        text = la.copy_unit_text("mom2")
        self.assertIn("--live --expect-env live --strategy %i", text); self.assertIn("--state state/live-mom2-%i.json", text)
        self.assertNotIn("/opt/raqm-live/.env.real\n", text.replace("-/opt/raqm-live/.env.real", ""))
        self.assertEqual(la.copy_state("mom2", "momentum_ls"), "state/live-mom2-momentum_ls.json")


class CopyHost(FakeHost):
    def __init__(self, d):
        super().__init__(d); self.ipc_root = d / "ipc"


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.d = Path(self.td.name); self.h = CopyHost(self.d)
    def tearDown(self): self.td.cleanup()

    def test_add_copy_writes_its_unit_folders_and_registry_and_starts_nothing(self):
        tool.main(["add-copy", "mom2", "momentum_ls"], host=self.h)
        self.assertEqual(la.load_copies(self.h.registry), {"mom2": ["momentum_ls"]})
        self.assertEqual((self.h.units / "raqm-live-mom2@.service").read_text(encoding="utf-8"),
                         la.copy_unit_text("mom2", self.h.accounts_dir, self.h.risk_root))
        for p in ("acct-mom2/momentum_ls", "acct-mom2/momentum_ls/commands", "acct-mom2/momentum_ls/results"):
            self.assertTrue((self.h.ipc_root / p).is_dir(), p)
        self.assertTrue((self.h.risk_root / "mom2").is_dir()); self.assertFalse((self.h.accounts_dir / "mom2" / "binance").exists())
        self.assertFalse((self.h.units / "raqm-live@momentum_ls.service.d").exists())          # the main bot untouched
        self.assertEqual(self.h.reloads, 1)

    def test_moving_another_strategy_keeps_the_copies(self):
        tool.main(["add-copy", "mom2", "momentum_ls"], host=self.h)
        tool.main(["add", "trend", "trend_daily"], host=self.h)
        self.assertEqual(la.load_copies(self.h.registry), {"mom2": ["momentum_ls"]}); self.assertEqual(la.load(self.h.registry), {"trend": ["trend_daily"]})
        with self.assertRaises(SystemExit): tool.main(["add-copy", "trend", "momentum_ls"], host=self.h)   # a moved account
        with self.assertRaises(SystemExit): tool.main(["add", "mom2", "rsi2_pullback"], host=self.h)       # a copy account

    def test_remove_copy_only_when_stopped_and_flat(self):
        tool.main(["add-copy", "mom2", "momentum_ls"], host=self.h)
        self.h.running.add("raqm-live-mom2@momentum_ls")
        with self.assertRaises(SystemExit): tool.main(["remove-copy", "mom2", "momentum_ls"], host=self.h)
        self.h.running.clear(); self.h.held[(self.h.risk_root / "mom2", "momentum_ls")] = 10
        with self.assertRaises(SystemExit): tool.main(["remove-copy", "mom2", "momentum_ls"], host=self.h)
        self.h.held.clear()
        tool.main(["remove-copy", "mom2", "momentum_ls"], host=self.h)
        self.assertEqual(la.load_copies(self.h.registry), {}); self.assertFalse((self.h.units / "raqm-live-mom2@.service").exists())


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); t = Path(self.td.name)
        self.paths = {"live": t / "live", "api_env": t / "api.env", "evidence": t / "ev.json", "ledger": t / "risk" / "risk_state.json",
                      "unit": t / "raqm-live@.service", "units": t / "units", "registry": t / "accounts.json",
                      "accounts_dir": t / "accounts", "risk_root": t / "opt"}
        self.paths["live"].mkdir(); self.paths["units"].mkdir()
        (self.paths["live"] / ".env.real").write_text("BINANCE_API_KEY=mainkey\nBINANCE_SECRET=s\n", encoding="utf-8")
        self.paths["registry"].write_text(la.dump({}, {"mom2": ["momentum_ls"]}), encoding="utf-8")
        a = self.paths["accounts_dir"] / "mom2"; a.mkdir(parents=True)
        (a / "binance").write_text("BINANCE_API_KEY=mom2key\nBINANCE_SECRET=s2\n", encoding="utf-8")
        (a / "allow-live.env").write_text("ALLOW_LIVE_TRADING=true\nBINANCE_LIVE_ACCOUNT=mom2\n", encoding="utf-8")
        (self.paths["units"] / "raqm-live-mom2@.service").write_text(
            la.copy_unit_text("mom2", self.paths["accounts_dir"], self.paths["risk_root"]), encoding="utf-8")
        rm.save_risk_state(self.paths["risk_root"] / "mom2" / "risk_state.json", rm._default_state())
        owners = {".env.real": "raqmlive", "binance": "root", "allow-live.env": "root"}
        self.patches = [mock.patch.object(lp, "_owner", lambda p: owners.get(Path(p).name)), mock.patch.object(lp, "_mode", lambda p: 0o600)]
        for p in self.patches: p.start()
    def tearDown(self):
        for p in self.patches: p.stop()
        self.td.cleanup()

    def rows(self, copy="mom2"):
        seen = {}
        real = lp.check_binance
        with mock.patch.object(lp, "check_binance", lambda keys, *a, **k: seen.setdefault("keys", keys) and real(keys, *a, **k)):
            return {n: (ok, why) for n, ok, why in lp.run(self.paths, "momentum_ls", clients=(PFut(), PSpot()), copy=copy)}, seen

    def test_the_copy_is_checked_on_its_own_files_unit_ledger_and_key(self):
        out, seen = self.rows()
        self.assertEqual(seen["keys"]["BINANCE_API_KEY"], "mom2key")
        self.assertIn("(a copy)", out["account"][1])
        self.assertTrue(out["raqm-live-mom2@ unit"][0]); self.assertTrue(out["its key is not the main account's"][0])
        self.assertTrue(out["real-money risk ledger"][0]); self.assertIn("mom2", out["real-money risk ledger"][1])

    def test_a_changed_unit_or_an_unregistered_copy_fails(self):
        (self.paths["units"] / "raqm-live-mom2@.service").write_text("[Service]\n", encoding="utf-8")
        self.assertFalse(self.rows()[0]["raqm-live-mom2@ unit"][0])
        out, _ = self.rows(copy="other")
        self.assertEqual(list(out), ["accounts registry"])

    def test_without_the_option_momentum_stays_the_main_accounts(self):
        out, seen = self.rows(copy=None)
        self.assertIn("main", out["account"][1]); self.assertEqual(seen["keys"]["BINANCE_API_KEY"], "mainkey")


class WatchBackupCheckTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); d = Path(self.td.name)
        self.ipc, self.root = d / "ipc", d / "opt"
        self.ledgers = {"demo": d / "risk-demo", "live": d / "risk"}
        for p in (self.ledgers["live"], self.root / "mom2"):
            rm.save_risk_state(p / "risk_state.json", rm._default_state())
        for folder in (self.ipc / "momentum_ls", la.copy_ipc("mom2", "momentum_ls", self.ipc)):
            folder.mkdir(parents=True)
            (folder / "live_status.json").write_text(json.dumps({"updated": datetime.now(timezone.utc).isoformat(), "env": "live",
                                                                  "positions": [], "review": {}, "entry_block": ""}), encoding="utf-8")
    def tearDown(self): self.td.cleanup()

    def seen(self, copy_units):
        return wd.problems(datetime.now(timezone.utc), unit=lambda e, s: (True, True) if (e, s) == ("live", "momentum_ls") else (False, False),
                           ipc=self.ipc, ledgers=self.ledgers, failed=lambda n: False, accounts={}, risk_root=self.root,
                           copies={"mom2": ["momentum_ls"]}, copy_unit=lambda name: copy_units.get(name, (False, False)))

    def test_the_watchdog_watches_the_copy_and_its_kill_switch_on_their_own(self):
        self.assertEqual(self.seen({"raqm-live-mom2@momentum_ls": (True, True)}), {})
        self.assertIn("down:live:mom2:momentum_ls", self.seen({"raqm-live-mom2@momentum_ls": (True, False)}))
        rm.trip_kill_switch(self.root / "mom2" / "risk_state.json", "drawdown 50%")
        out = self.seen({"raqm-live-mom2@momentum_ls": (True, True)})
        self.assertIn("kill:live:mom2", out); self.assertNotIn("kill:live", out)
        self.assertEqual(self.seen({}), {})                        # not enabled yet: not watched, its kill switch neither

    def test_the_backup_takes_the_copy_accounts_ledger(self):
        src = backup.all_sources(accounts={}, copies={"mom2": ["momentum_ls"]}, risk_root=self.root)
        self.assertEqual(src["risk-live-mom2"], self.root / "mom2")

    def test_the_check_reads_the_copy_with_its_own_key_and_files(self):
        state, status = rc.files_of("momentum_ls", "mom2")
        self.assertEqual(state.name, "live-mom2-momentum_ls.json"); self.assertEqual(status.parent.name, "momentum_ls")
        self.assertEqual(status.parent.parent.name, "acct-mom2")
        d = Path("/etc/raqm-live/accounts")
        self.assertTrue(rc.key_source("momentum_ls", {}, str(d / "mom2"), d, copy="mom2")[0])
        self.assertFalse(rc.key_source("momentum_ls", {}, "", d, copy="mom2")[0])                 # the main key: refused
        self.assertTrue(rc.key_source("momentum_ls", {}, "", d)[0])                               # main, as before
        self.assertIn("(حساب mom2)", rc.report([], True, "momentum_ls", "mom2")[0])


class ApiTests(ApiAuthTests):
    def setUp(self):
        super().setUp()
        import app.main as m; self.m = m
        t = Path(self.tmp.name)
        (t / "live").mkdir(); (t / "demo").mkdir(); (t / "accounts" / "mom2").mkdir(parents=True)
        (t / "accounts.json").write_text(la.dump({}, {"mom2": ["momentum_ls"]}), encoding="utf-8")
        self.ipc = t / "ipc"
        for folder, n in ((self.ipc / "momentum_ls", 10), (la.copy_ipc("mom2", "momentum_ls", self.ipc), 3)):
            folder.mkdir(parents=True)
            (folder / "live_status.json").write_text(json.dumps({"updated": datetime.now(timezone.utc).isoformat(), "env": "live",
                                                                  "positions": [{"symbol": "X"}] * n}), encoding="utf-8")
        self.patches = [mock.patch.dict(os.environ, {"RAQM_RISK_DIR": str(t / "live"), "RAQM_RISK_DIR_DEMO": str(t / "demo"),
                                                     "ALLOW_LIVE_TRADING": "true", "READINESS_EXPECTED_COMMIT_SHA": "a" * 40}),
                        mock.patch.object(m, "BOT_DIR", t), mock.patch.object(m, "LIVE_ACTIVATION_PATH", t / "live" / "act.sqlite3"),
                        mock.patch.object(m, "ACCOUNTS_REGISTRY", t / "accounts.json"), mock.patch.object(m, "ACCOUNTS_RISK_ROOT", t / "accounts"),
                        mock.patch.object(m, "IPC_DIR", self.ipc)]
        for p in self.patches: p.start()
        (t / "readiness_evidence.json").write_text(json.dumps(trusted_evidence(m.LIVE_STRATEGIES)), encoding="utf-8")
        m._rate_hits.clear()
    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        super().tearDown()

    def get(self, **q):
        return self.c.get("/api/live/strategies", headers=self.h("admin-token"), params=q).json()

    def test_the_main_account_keeps_momentum_and_the_copy_shows_its_own_bot(self):
        main = self.get(env="live")
        self.assertIn("momentum_ls", [r["id"] for r in main["strategies"]])
        self.assertIn({"name": "mom2", "strategies": ["momentum_ls"], "copy": True}, main["accounts"])
        self.assertEqual(next(r for r in main["strategies"] if r["id"] == "momentum_ls")["positions"], 10)
        copy = self.get(env="live", acct="mom2")
        self.assertEqual([r["id"] for r in copy["strategies"]], ["momentum_ls"])
        self.assertEqual(copy["strategies"][0]["positions"], 3)                 # its own folder, not the main bot's

    def test_the_copys_capital_goes_to_its_own_ledger(self):
        r = self.c.post("/api/live/capital", headers=self.h("admin-token"),
                        json={"env": "live", "acct": "mom2", "capital_usdt": 300, "capital_margin_override_usdt": 24, "capital_reserve_pct": 20})
        self.assertEqual(r.status_code, 200, r.text)
        t = Path(self.tmp.name)
        self.assertEqual(rm.load_risk_state(t / "accounts" / "mom2" / "risk_state.json")["limits"]["capital_usdt"], 300)
        self.assertIsNone(rm.load_risk_state(t / "live" / "risk_state.json")["limits"].get("capital_usdt"))
        self.assertEqual(r.json()["plan"]["max_open"], 10)                     # 300 × 80% ÷ 24: one basket


if __name__ == "__main__":
    unittest.main()
