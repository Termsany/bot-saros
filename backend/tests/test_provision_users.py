"""P2.2 (docs/phase2-design.md): the provisioner that runs users' strategies on the owner's order path, Demo only."""
import json, os, sqlite3, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
import provision_users as pu
import bot as botmod

U1, U2 = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"


def doc(uid, **kw):
    d = {"user_id": uid, "env": "demo", "enabled": True, "strategies": ["trend_daily"], "leverage": 2,
         "risk_per_trade_pct": 1.0, "max_aggregate_risk_pct": 3.0, "capital_usdt": 1000, "capital_margin_override_usdt": 20}
    d.update(kw); return d


class ValidateTests(unittest.TestCase):
    def test_real_money_is_refused_whatever_the_desired_state_says(self):
        for env in ("live", "testnet", None, "DEMO"):
            with self.assertRaises(ValueError): pu.validate(U1, doc(U1, env=env))

    def test_everything_is_checked(self):
        bad = [doc(U1, user_id=U2), doc(U1, strategies=["ict"]), doc(U1, strategies=["trend_daily", "trend_daily"]),
               doc(U1, strategies=["momentum_ls"], max_aggregate_risk_pct=9.0), doc(U1, leverage=6), doc(U1, leverage=True),
               doc(U1, risk_per_trade_pct=2), doc(U1, max_aggregate_risk_pct=5), doc(U1, risk_per_trade_pct=1, max_aggregate_risk_pct=0.5),
               doc(U1, capital_margin_override_usdt=2000), doc(U1, capital_usdt="1000")]
        for d in bad:
            with self.assertRaises(ValueError, msg=str(d)): pu.validate(U1, d)
        with self.assertRaises(ValueError): pu.validate("../etc", doc("../etc"))
        self.assertEqual(pu.validate(U1, doc(U1))["leverage"], 2)

    def test_the_strategies_are_the_bots(self):
        self.assertEqual(set(pu.STRATEGIES), botmod.LIVE_READY_STRATEGIES)

    def test_strategy_policy_is_account_based_and_fail_closed(self):
        self.assertEqual(pu.strategy_policy(["trend_daily", "vol_breakout", "rsi2_pullback"])["slots"], 3)
        self.assertEqual(pu.strategy_policy(["momentum_ls"])["slots"], 10)
        self.assertFalse(pu.strategy_policy(["momentum_ls"], available_slots=9)["accepted"])

    def test_desired_files_are_read_as_hostile(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            d = Path(d)
            (d / f"{U1}.json").write_text(json.dumps(doc(U1)), encoding="utf-8")
            (d / f"{U2}.json").write_text(json.dumps(doc(U2, env="live")), encoding="utf-8")
            (d / "big.json").write_text("x" * 20000, encoding="utf-8")
            good, bad = pu.read_desired(d)
        self.assertEqual(set(good), {U1}); self.assertEqual(set(bad), {f"{U2}.json", "big.json"})


class PlanTests(unittest.TestCase):
    def plan(self, desired=None, allow=(U1,), consent=(U1,), keys=(U1,), running=None, flat=lambda u, s: True):
        desired = {u: pu.validate(u, d) for u, d in (desired or {U1: doc(U1)}).items()}
        return pu.plan(desired, list(allow), {u: "demo" for u in consent}, {u: ("k", "s") for u in keys}, running or {}, flat)

    def kinds(self, actions):     # what is done to the machine (each user's page answer is checked on its own)
        return [(a[0],) + tuple(x for x in a[1:3] if isinstance(x, str)) for a in actions if a[0] != "answer"]

    def answer(self, actions, uid=U1):
        return next(a[2]["state"] for a in actions if a[0] == "answer" and a[1] == uid)

    def test_a_user_passing_every_gate_gets_their_bot(self):
        acts = self.plan()
        self.assertEqual(self.kinds(acts), [("user", U1), ("keys", U1), ("limits", U1), ("ensure", U1, "trend_daily")])
        self.assertEqual(self.answer(acts), "running")

    def test_each_gate_alone_keeps_a_user_out_and_their_page_says_which(self):
        for kw, why in (({"allow": ()}, "waiting_approval"), ({"consent": ()}, "no_consent"), ({"keys": ()}, "no_keys"),
                        ({"desired": {U1: doc(U1, enabled=False)}}, "off"), ({"desired": {U1: doc(U1, strategies=[])}}, "off")):
            acts = self.plan(**kw)
            self.assertEqual(self.kinds(acts), [], kw); self.assertEqual(self.answer(acts), why, kw)

    def test_past_the_cap_the_page_says_no_place(self):
        users = [f"{i}{i}{i}{i}{i}{i}{i}{i}-1111-4111-8111-111111111111" for i in range(1, 7)]
        acts = self.plan(desired={u: doc(u) for u in users}, allow=users, consent=users, keys=users)
        self.assertEqual([self.answer(acts, u) for u in users], ["running"] * pu.MAX_USERS + ["no_place"] * 2)

    def test_the_cap_follows_the_allow_list_order(self):
        users = [f"{i}{i}{i}{i}{i}{i}{i}{i}-1111-4111-8111-111111111111" for i in range(1, 7)]
        actions = self.plan(desired={u: doc(u) for u in users}, allow=users[::-1], consent=users, keys=users)
        started = [a[1] for a in actions if a[0] == "user"]
        self.assertEqual(started, users[::-1][:pu.MAX_USERS])

    def test_switched_off_stops_entries_at_once_but_the_service_only_when_flat(self):
        off = {U1: doc(U1, enabled=False)}
        open_ = self.plan(desired=off, running={U1: {"trend_daily"}}, flat=lambda u, s: False)
        self.assertEqual(self.kinds(open_), [("no_entries", U1)])                       # keys kept: the exits need them
        done = self.plan(desired=off, running={U1: {"trend_daily"}}, flat=lambda u, s: True)
        self.assertEqual(self.kinds(done), [("no_entries", U1), ("stop", U1, "trend_daily"), ("wipe_keys", U1)])

    def test_a_dropped_strategy_stops_only_when_flat_and_the_user_keeps_their_keys(self):
        running = {U1: {"trend_daily", "vol_breakout"}}
        self.assertNotIn("stop", [a[0] for a in self.plan(running=running, flat=lambda u, s: s != "vol_breakout")])
        acts = self.plan(running=running)
        self.assertIn(("stop", U1, "vol_breakout"), [a[:3] for a in acts]); self.assertNotIn("wipe_keys", [a[0] for a in acts])

    def test_a_user_whose_desired_file_disappears_or_turns_invalid_is_wound_down(self):
        self.assertEqual(self.kinds(pu.plan({}, [U1], {U1: "demo"}, {U1: ("k", "s")}, {U1: {"trend_daily"}}, lambda u, s: False)),
                         [("no_entries", U1)])


class DropinTests(unittest.TestCase):
    def test_the_bot_runs_as_the_user_on_demo_with_its_credential_and_own_folders(self):
        t = pu.dropin(U1, "trend_daily", pu.validate(U1, doc(U1)))
        for want in (f"User={pu.os_user(U1)}", "Environment=BINANCE_ENV=demo", "--expect-env demo", "--strategy trend_daily",
                     f"LoadCredential=binance:{pu.CRED_ROOT / U1 / 'binance'}", f"RAQM_RISK_DIR={pu.DATA_ROOT / U1 / 'risk'}",
                     f"RAQM_IPC_DIR={pu.IPC_ROOT / (U1 + '--trend_daily')}", "--universe 10", "--leverage 2", "ExecStart=\n"):
            self.assertIn(want, t)
        self.assertNotIn("/opt/raqm-risk", t.replace("/opt/raqm-users/ipc", ""))      # never the owner's ledgers
        self.assertEqual(len(pu.os_user(U1)), 22)

    def test_the_template_alone_runs_nothing_and_loads_no_owner_file(self):
        t = (ROOT / "deploy" / "vps" / "raqm-user@.service").read_text(encoding="utf-8")
        self.assertIn("User=nobody", t); self.assertIn("ExecStart=/bin/false", t)
        self.assertIn("ConditionPathExists=/etc/systemd/system/raqm-user@%i.service.d/user.conf", t)
        self.assertFalse([l for l in t.splitlines() if l.startswith("EnvironmentFile")]); self.assertIn("BINANCE_API_KEY", t.split("UnsetEnvironment=")[1].splitlines()[0])

    def test_template_fences_an_instance_ipc_path_only(self):
        t = (ROOT / "deploy" / "vps" / "raqm-user@.service").read_text(encoding="utf-8")
        self.assertIn("ReadWritePaths=/opt/raqm-users/ipc/%i", t)
        self.assertNotIn("-/opt/raqm-users/ipc", t)


class FakeSystem:
    def __init__(self): self.files, self.calls, self.limits = {}, [], []
    def run(self, *cmd): self.calls.append(cmd)
    def write(self, path, text, mode, owner=None): self.files[str(path)] = (text, mode)
    def read(self, path): return self.files.get(str(path), (None,))[0]
    def remove(self, path): self.files.pop(str(path), None)
    def ensure_user(self, uid): self.calls.append(("useradd", pu.os_user(uid)))
    def set_limits(self, uid, d): self.limits.append(uid)
    def no_entries(self, uid): self.calls.append(("no_entries", uid))


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.d = pu.validate(U1, doc(U1)); self.fs = FakeSystem(); self.logs = []
    def run_once(self, flat=True, running=None):
        acts = pu.plan({U1: self.d}, [U1], {U1: "demo"}, {U1: ("key-1", "secret-1")}, running or {}, lambda u, s: flat)
        pu.apply(acts, {U1: ("key-1", "secret-1")}, self.fs, log=self.logs.append)

    def test_first_run_writes_keys_0600_and_starts_the_service(self):
        self.run_once()
        text, mode = self.fs.files[str(pu.CRED_ROOT / U1 / "binance")]
        self.assertEqual((text, mode), ("BINANCE_API_KEY=key-1\nBINANCE_SECRET=secret-1\n", 0o600))
        self.assertIn(("systemctl", "restart", pu.unit(U1, "trend_daily")), self.fs.calls)

    def test_a_second_run_with_nothing_changed_does_nothing(self):
        self.run_once(); self.fs.calls.clear(); self.fs.limits.clear()
        self.run_once(running={U1: {"trend_daily"}})
        self.assertEqual([c for c in self.fs.calls if c[0] == "systemctl" and c[1] != "daemon-reload"], [])
        self.assertEqual(self.fs.limits, [])

    def test_new_settings_never_restart_a_bot_with_an_open_trade(self):
        self.run_once(); self.fs.calls.clear()
        self.d = pu.validate(U1, doc(U1, leverage=3))
        self.run_once(flat=False, running={U1: {"trend_daily"}})
        self.assertNotIn(("systemctl", "restart", pu.unit(U1, "trend_daily")), self.fs.calls)
        self.run_once(flat=True, running={U1: {"trend_daily"}})
        self.assertIn(("systemctl", "restart", pu.unit(U1, "trend_daily")), self.fs.calls)

    def test_one_users_failure_does_not_stop_the_rest(self):
        class Boom(FakeSystem):
            def ensure_user(self, uid): raise RuntimeError("useradd failed")
        fs = Boom(); pu.apply([("user", U1), ("wipe_keys", U2)], {}, fs, log=self.logs.append)
        self.assertTrue(any("useradd failed" in l for l in self.logs))


class ReadTests(unittest.TestCase):
    def test_consent_and_keys(self):
        from cryptography.fernet import Fernet
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            d = Path(d); key = Fernet.generate_key()
            con = sqlite3.connect(d / "c.sqlite3")
            con.execute("CREATE TABLE user_live_activation (user_id TEXT, exchange TEXT, enabled INTEGER)")
            con.executemany("INSERT INTO user_live_activation VALUES (?,?,?)", [(U1, "binance", 1), (U2, "binance", 0)]); con.commit(); con.close()
            self.assertEqual(pu.read_consent(d / "c.sqlite3"), {U1: "live"})        # before the environment was kept
            from backend.app import user_live_activation as ula
            ula.enable_user_live(d / "n.sqlite3", user_id=U2, exchange="binance", confirm=ula.CONSENT_TEXT, actor="t", environment="demo")
            self.assertEqual(pu.read_consent(d / "n.sqlite3"), {U2: "demo"})
            (d / ".env").write_text(f"OTHER=1\nVAULT_MASTER_KEY={key.decode()}\n", encoding="utf-8")
            vault = {U1: {"binance": {"apiKey": "a", "secret": "b"}}, U2: {"binance": {"apiKey": "a"}}}
            (d / "v.json").write_bytes(Fernet(key).encrypt(json.dumps(vault).encode()))
            self.assertEqual(pu.read_keys([U1, U2], vault=d / "v.json", api_env=d / ".env"), {U1: ("a", "b")})
            (d / "allow").write_text(f"{U1}\nnot-a-uid\n", encoding="utf-8")
            self.assertEqual(pu.read_allow(d / "allow"), [U1])
            st = d / "s.json"
            self.assertTrue(pu.is_flat(st))
            st.write_text(json.dumps({"positions": {"X": {}}}), encoding="utf-8"); self.assertFalse(pu.is_flat(st))
            st.write_text("{broken", encoding="utf-8"); self.assertFalse(pu.is_flat(st))


if __name__ == "__main__":
    unittest.main()


class ReviewFindingsTests(unittest.TestCase):
    """P2.7 independent review (2026-11-01): each finding reproduced here before it was fixed."""
    class StatefulSystem(FakeSystem):
        """Keeps the user's yes/no per strategy like the real ledger, so wind-down and coming back can be checked."""
        def __init__(self): super().__init__(); self.chosen = {}
        def set_limits(self, uid, d): self.limits.append(uid); self.chosen[uid] = list(d["strategies"])
        def no_entries(self, uid): self.calls.append(("no_entries", uid)); self.chosen[uid] = []

    def run_once(self, fs, d, wanted=True, flat=True, running=None):
        desired = {U1: pu.validate(U1, d)}
        acts = pu.plan(desired, [U1], {U1: "demo"} if wanted else {}, {U1: ("k", "s")}, running or {}, lambda u, s: flat)
        pu.apply(acts, {U1: ("k", "s")}, fs, log=lambda m: None)

    def test_off_then_on_with_the_same_settings_trades_again(self):
        fs = self.StatefulSystem(); d = doc(U1)
        self.run_once(fs, d); self.assertEqual(fs.chosen[U1], ["trend_daily"])
        self.run_once(fs, d, wanted=False, flat=False, running={U1: {"trend_daily"}}); self.assertEqual(fs.chosen[U1], [])
        self.run_once(fs, d, wanted=False, flat=False, running={U1: {"trend_daily"}})
        self.assertEqual([c for c in fs.calls if c[0] == "no_entries"], [("no_entries", U1)])   # once, not every minute
        self.run_once(fs, d, running={U1: {"trend_daily"}}); self.assertEqual(fs.chosen[U1], ["trend_daily"])

    def test_a_consent_db_that_cant_be_read_skips_the_run_instead_of_winding_everyone_down(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            self.assertEqual(pu.read_consent(Path(d) / "absent.sqlite3"), {})        # no record yet: nobody
            (Path(d) / "broken.sqlite3").write_text("not a database", encoding="utf-8")
            with self.assertRaises(Exception): pu.read_consent(Path(d) / "broken.sqlite3")
            (Path(d) / ".env").write_text("OTHER=1\n", encoding="utf-8")
            with self.assertRaises(RuntimeError): pu.read_keys([U1], vault=Path(d) / "v.json", api_env=Path(d) / ".env")

    def test_a_demo_consent_never_counts_for_real_money(self):
        self.assertTrue(pu.consent_ok({U1: "demo"}, U1, "demo")); self.assertTrue(pu.consent_ok({U1: "live"}, U1, "demo"))
        self.assertFalse(pu.consent_ok({U1: "demo"}, U1, "live")); self.assertFalse(pu.consent_ok({}, U1, "demo"))

    def test_a_running_user_keeps_their_place_when_someone_higher_on_the_list_arrives(self):
        users = [f"{i}{i}{i}{i}{i}{i}{i}{i}-1111-4111-8111-111111111111" for i in range(1, 6)]
        desired = {u: pu.validate(u, doc(u)) for u in users}
        running = {u: {"trend_daily"} for u in users[1:]}                          # 4 running, the first one arrives
        acts = pu.plan(desired, users, {u: "demo" for u in users}, {u: ("k", "s") for u in users}, running, lambda u, s: False)
        self.assertNotIn("no_entries", [a[0] for a in acts])
        self.assertEqual(next(a[2]["state"] for a in acts if a[0] == "answer" and a[1] == users[0]), "no_place")

    def test_a_user_whose_setup_failed_gets_no_bot_started(self):
        class Boom(FakeSystem):
            def set_limits(self, uid, d): raise RuntimeError("ledger")
        fs = Boom(); self.run_once(fs, doc(U1))
        self.assertFalse([c for c in fs.calls if c[:2] == ("systemctl", "restart")])

    def test_keys_that_would_break_the_credential_lines_are_not_used(self):
        from cryptography.fernet import Fernet
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            d = Path(d); key = Fernet.generate_key()
            (d / ".env").write_text(f"VAULT_MASTER_KEY={key.decode()}\n", encoding="utf-8")
            (d / "v.json").write_bytes(Fernet(key).encrypt(json.dumps({U1: {"binance": {"apiKey": "a\nBINANCE_SECRET=x", "secret": "b"}}}).encode()))
            self.assertEqual(pu.read_keys([U1], vault=d / "v.json", api_env=d / ".env"), {})

    def test_the_request_folders_are_made_by_root_with_the_apis_group(self):
        src = (ROOT / "scripts" / "provision_users.py").read_text(encoding="utf-8")
        self.assertIn('for p in (ipc_instance(uid, s), ipc_instance(uid, s) / "commands", ipc_instance(uid, s) / "results")', src)
        self.assertNotIn("os.makedirs(", src)                                       # not as the user (setgid was lost)
        self.assertIn('"/usr/bin/env", "-i"', src)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "needs FIFOs")
    def test_a_fifo_in_place_of_a_file_does_not_hang_root(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            f = Path(d) / "x.json"; os.mkfifo(f)
            with self.assertRaises(ValueError): pu._read_small(f)
            self.assertFalse(pu.is_flat(f))

    def test_the_units_time_out_and_the_users_bots_are_fenced_off(self):
        V = ROOT / "deploy" / "vps"
        for u in ("raqm-users-provision.service", "raqm-watchdog-users.service", "raqm-backup-users.service"):
            self.assertIn("TimeoutStartSec=", (V / u).read_text(encoding="utf-8"), u)
        t = (V / "raqm-user@.service").read_text(encoding="utf-8")
        for want in ("ProtectProc=invisible", "CapabilityBoundingSet=\n", "-/opt/raqm-live", "-/opt/raqm-api", "-/opt/raqm-risk "):
            self.assertIn(want, t)
