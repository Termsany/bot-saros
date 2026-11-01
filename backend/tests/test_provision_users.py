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
               doc(U1, strategies=["trend_daily", "vol_breakout", "rsi2_pullback"]), doc(U1, leverage=6), doc(U1, leverage=True),
               doc(U1, risk_per_trade_pct=2), doc(U1, max_aggregate_risk_pct=5), doc(U1, risk_per_trade_pct=1, max_aggregate_risk_pct=0.5),
               doc(U1, capital_margin_override_usdt=2000), doc(U1, capital_usdt="1000")]
        for d in bad:
            with self.assertRaises(ValueError, msg=str(d)): pu.validate(U1, d)
        with self.assertRaises(ValueError): pu.validate("../etc", doc("../etc"))
        self.assertEqual(pu.validate(U1, doc(U1))["leverage"], 2)

    def test_the_strategies_are_the_bots(self):
        self.assertEqual(set(pu.STRATEGIES), botmod.LIVE_READY_STRATEGIES)

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
        return pu.plan(desired, list(allow), set(consent), {u: ("k", "s") for u in keys}, running or {}, flat)

    def kinds(self, actions):
        return [(a[0],) + tuple(x for x in a[1:3] if isinstance(x, str)) for a in actions]

    def test_a_user_passing_every_gate_gets_their_bot(self):
        self.assertEqual(self.kinds(self.plan()), [("user", U1), ("keys", U1), ("limits", U1), ("ensure", U1, "trend_daily")])

    def test_each_gate_alone_keeps_a_user_out(self):
        for kw in ({"allow": ()}, {"consent": ()}, {"keys": ()}, {"desired": {U1: doc(U1, enabled=False)}},
                   {"desired": {U1: doc(U1, strategies=[])}}):
            self.assertEqual(self.plan(**kw), [], kw)

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
        self.assertEqual(self.kinds(pu.plan({}, [U1], {U1}, {U1: ("k", "s")}, {U1: {"trend_daily"}}, lambda u, s: False)),
                         [("no_entries", U1)])


class DropinTests(unittest.TestCase):
    def test_the_bot_runs_as_the_user_on_demo_with_its_credential_and_own_folders(self):
        t = pu.dropin(U1, "trend_daily", pu.validate(U1, doc(U1)))
        for want in (f"User={pu.os_user(U1)}", "Environment=BINANCE_ENV=demo", "--expect-env demo", "--strategy trend_daily",
                     f"LoadCredential=binance:{pu.CRED_ROOT / U1 / 'binance'}", f"RAQM_RISK_DIR={pu.DATA_ROOT / U1 / 'risk'}",
                     f"RAQM_IPC_DIR={pu.IPC_ROOT / U1 / 'trend_daily'}", "--universe 10", "--leverage 2", "ExecStart=\n"):
            self.assertIn(want, t)
        self.assertNotIn("/opt/raqm-risk", t.replace("/opt/raqm-users/ipc", ""))      # never the owner's ledgers
        self.assertEqual(len(pu.os_user(U1)), 22)

    def test_the_template_alone_runs_nothing_and_loads_no_owner_file(self):
        t = (ROOT / "deploy" / "vps" / "raqm-user@.service").read_text(encoding="utf-8")
        self.assertIn("User=nobody", t); self.assertIn("ExecStart=/bin/false", t)
        self.assertIn("ConditionPathExists=/etc/systemd/system/raqm-user@%i.service.d/user.conf", t)
        self.assertFalse([l for l in t.splitlines() if l.startswith("EnvironmentFile")]); self.assertIn("BINANCE_API_KEY", t.split("UnsetEnvironment=")[1].splitlines()[0])


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
        acts = pu.plan({U1: self.d}, [U1], {U1}, {U1: ("key-1", "secret-1")}, running or {}, lambda u, s: flat)
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
            self.assertEqual(pu.read_consent(d / "c.sqlite3"), {U1})
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
