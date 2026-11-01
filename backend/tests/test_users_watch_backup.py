"""P2.5 (docs/phase2-design.md): the users' bots are watched and backed up like the owner's."""
import io, json, sys, tarfile, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
import watchdog as wd
import backup

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
U1 = "11111111-1111-4111-8111-111111111111"


class UserWatchdogTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.d = Path(self.td.name)
        self.units, self.ipc = self.d / "units", self.d / "ipc"
    def tearDown(self): self.td.cleanup()

    def bot(self, uid, s, **status):
        (self.units / f"raqm-user@{uid}--{s}.service.d").mkdir(parents=True)
        (self.units / f"raqm-user@{uid}--{s}.service.d" / "user.conf").write_text("[Service]\n", encoding="utf-8")
        if status is not None:
            (self.ipc / uid / s).mkdir(parents=True, exist_ok=True)
            st = {"updated": NOW.isoformat(), "env": "demo", "positions": [], "review": {}, "entry_block": "", **status}
            (self.ipc / uid / s / "live_status.json").write_text(json.dumps(st), encoding="utf-8")

    def seen(self, active=lambda u, s: True):
        return wd.user_problems(NOW, bots=wd.user_bots(self.units), active=active, ipc=self.ipc)

    def test_the_bots_come_from_the_provisioners_drop_ins(self):
        self.bot(U1, "trend_daily"); (self.units / "raqm-user@junk.service.d").mkdir(); (self.units / "raqm-demo@x.service.d").mkdir()
        self.assertEqual(wd.user_bots(self.units), [(U1, "trend_daily")])

    def test_a_healthy_user_bot_sends_nothing(self):
        self.bot(U1, "trend_daily"); self.assertEqual(self.seen(), {})

    def test_the_same_problems_as_the_owners_bots(self):
        self.bot(U1, "trend_daily", positions=[{"symbol": "SOL/USDT", "unprotected": True}])
        self.bot(U1, "vol_breakout", updated=(NOW - timedelta(minutes=20)).isoformat())
        seen = self.seen()
        self.assertEqual(set(seen), {f"stop:user:{U1}:trend_daily:SOL/USDT", f"stale:user:{U1}:vol_breakout"})
        self.assertIn(U1[:8], seen[f"stop:user:{U1}:trend_daily:SOL/USDT"][0])
        self.assertEqual(set(self.seen(active=lambda u, s: False)), {f"down:user:{U1}:trend_daily", f"down:user:{U1}:vol_breakout"})

    def test_a_users_kill_switch_is_one_alert_from_their_status(self):
        self.bot(U1, "trend_daily", entry_block="Central Risk Manager kill switch is tripped — drawdown")
        self.bot(U1, "vol_breakout", entry_block="Central Risk Manager kill switch is tripped — drawdown")
        self.assertEqual(set(self.seen()), {f"kill:user:{U1}"})

    def test_a_status_file_replaced_by_a_link_is_not_followed(self):
        self.bot(U1, "trend_daily")
        f = self.ipc / U1 / "trend_daily" / "live_status.json"; target = self.d / "elsewhere.json"
        target.write_text(f.read_text(encoding="utf-8"), encoding="utf-8"); f.unlink()
        try:
            f.symlink_to(target)
        except OSError:
            self.skipTest("symlinks not available here")
        self.assertEqual(set(self.seen()), {f"stale:user:{U1}:trend_daily"})

    def test_the_owners_watchdog_alerts_when_the_users_one_fails(self):
        seen = wd.problems(NOW, unit=lambda e, s: (False, False), ipc=self.ipc, ledgers={}, failed=lambda n: n == "raqm-watchdog-users.service")
        self.assertEqual(set(seen), {"watchdog-users"})

    def test_the_units_read_only_with_one_capability(self):
        unit = (ROOT / "deploy" / "vps" / "raqm-watchdog-users.service").read_text(encoding="utf-8")
        self.assertIn("CapabilityBoundingSet=CAP_DAC_READ_SEARCH\n", unit); self.assertIn("watchdog.py --users", unit)
        setup = (ROOT / "deploy" / "vps" / "setup-live.sh").read_text(encoding="utf-8")
        for t in ("raqm-watchdog-users.timer", "raqm-backup-users.timer"): self.assertIn(f"enable --now {t}", setup)


class UsersBackupTests(unittest.TestCase):
    def test_each_user_is_archived_as_themselves_and_bundled(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            d = Path(d); (d / U1).mkdir(); (d / "not-a-user").mkdir()
            calls = []
            data, n = backup.users_archive(NOW, data_root=d, dump=lambda uid, p: calls.append(uid) or b"user-archive")
        self.assertEqual((n, calls), (1, [U1]))
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            self.assertEqual({m.name: tar.extractfile(m).read() for m in tar.getmembers()},
                             {f"raqm-users-backup-20261101/{U1}.tar.gz": b"user-archive"})

    def test_a_user_dump_holds_only_their_ledger_and_state(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            d = Path(d); (d / "risk").mkdir(); (d / "state").mkdir()
            (d / "state" / "trend_daily.json").write_text("{}", encoding="utf-8")
            data, n = backup.build(NOW, {"risk": d / "risk", "state": d / "state"})
        self.assertEqual(n, 1)

    def test_the_users_backup_runs_each_part_as_that_user(self):
        unit = (ROOT / "deploy" / "vps" / "raqm-backup-users.service").read_text(encoding="utf-8")
        self.assertIn("backup.py --users", unit)
        src = (ROOT / "scripts" / "backup.py").read_text(encoding="utf-8")
        self.assertIn('"runuser", "-u", "ru" + uid.replace("-", "")[:20]', src)
        import provision_users as pu
        self.assertEqual("ru" + U1.replace("-", "")[:20], pu.os_user(U1))      # same account the provisioner made


if __name__ == "__main__":
    unittest.main()


class UsersBackupReviewTests(unittest.TestCase):
    """P2.7 review: one user's part failing doesn't lose the others; the user's process gets no environment."""
    def test_one_failing_user_still_sends_the_rest(self):
        U2 = "22222222-2222-4222-8222-222222222222"
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            d = Path(d); (d / U1).mkdir(); (d / U2).mkdir()
            def dump(uid, p):
                if uid == U1: raise RuntimeError("no such user")
                return b"ok"
            with self.assertRaises(backup.PartialBackup) as cm:
                backup.users_archive(NOW, data_root=d, dump=dump)
        self.assertEqual(cm.exception.n, 1); self.assertIn(U1[:8], str(cm.exception))

    def test_the_dump_runs_with_an_empty_environment(self):
        src = (ROOT / "scripts" / "backup.py").read_text(encoding="utf-8")
        self.assertIn('"/usr/bin/env", "-i", "PATH=/usr/bin:/bin"', src)
