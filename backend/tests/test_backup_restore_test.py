"""Restore tests (owner, 2026-11-08): every daily archive is test-restored on the server before it is sent (a failure
still sends it and alerts), and `backup_crypto.py verify` opens and checks an encrypted one on the owner's computer.
On the first of the month the caption reminds the owner to run that check."""
import io, json, sqlite3, sys, tarfile, tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import backup, backup_crypto

PASS = b"a long passphrase 123"
NOW = datetime(2026, 11, 4, 3, 0, tzinfo=timezone.utc)


class RestoreTestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); d = cls.d = Path(cls.td.name)
        backup_crypto.keygen(d / "keys", PASS)
        cls.pub_path = d / "keys" / "backup-public.pem"
        cls.priv = (d / "keys" / "backup-private.pem").read_bytes()
        state, live = d / "state", d / "risk-live"
        state.mkdir(); live.mkdir()
        (state / "live-momentum_ls.json").write_text(json.dumps({"positions": {"A/USDT:USDT": {}}}), encoding="utf-8")
        con = sqlite3.connect(live / "risk_state.sqlite3"); con.execute("create table t(x)"); con.commit(); con.close()
        cls.good, _ = backup.build(NOW, {"state": state, "risk-live": live})
        cls.missing, _ = backup.build(NOW, {"state": state})              # no real ledger in it

    @classmethod
    def tearDownClass(cls):
        cls.td.cleanup()

    def run_main(self, data, when=NOW, pub=None):
        sent = []
        clock = mock.Mock(wraps=datetime); clock.now.return_value = when
        with mock.patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"}), \
             mock.patch.object(backup, "datetime", clock), \
             mock.patch.object(backup_crypto, "PUBLIC_KEY", pub or self.pub_path), \
             mock.patch.object(backup, "all_sources", return_value={}), \
             mock.patch.object(backup, "build", return_value=(data, 3)), \
             mock.patch.object(backup, "_post", side_effect=lambda m, f, files=None: sent.append((m, f, files))):
            backup.main()
        return sent

    def test_the_daily_restore_test(self):
        self.assertEqual(backup.restore_test(self.good), (True, []))
        ok, bad = backup.restore_test(self.missing)
        self.assertFalse(ok); self.assertTrue(any("risk-live/risk_state.sqlite3" in b for b in bad))
        ok, bad = backup.restore_test(b"not an archive")
        self.assertFalse(ok); self.assertIn("مقدرناش نفكها", bad[0])

    def test_a_good_archive_says_it_was_tested(self):
        sent = self.run_main(self.good)
        self.assertEqual([s[0] for s in sent], ["sendDocument"])
        self.assertIn("✅ اتجربت تتفك", sent[0][1]["caption"])
        self.assertNotIn("🗓️", sent[0][1]["caption"])                    # not the first of the month

    def test_a_failed_restore_test_still_sends_and_alerts(self):
        sent = self.run_main(self.missing)
        self.assertEqual([s[0] for s in sent], ["sendDocument", "sendMessage"])
        self.assertIn("❌", sent[0][1]["caption"]); self.assertIn("تجربة فكها فشلت", sent[1][1]["text"])

    def test_the_first_of_the_month_reminds_the_owner(self):
        sent = self.run_main(self.good, when=datetime(2026, 12, 1, 3, tzinfo=timezone.utc))
        self.assertIn("backup_crypto.py verify", sent[0][1]["caption"])
        sent = self.run_main(self.good, when=datetime(2026, 12, 1, 3, tzinfo=timezone.utc), pub=self.d / "absent.pem")
        self.assertNotIn("🗓️", sent[0][1]["caption"])                    # nothing to verify while unencrypted

    def test_verify_opens_and_checks_an_encrypted_backup(self):
        enc = self.d / "raqm-backup-20261104.tar.gz.enc"
        enc.write_bytes(backup_crypto.encrypt(self.good, self.pub_path.read_bytes()))
        res = backup_crypto.verify_backup(enc, self.priv, PASS)
        self.assertTrue(all(ok for ok, _ in res), res)
        self.assertFalse(backup_crypto.verify_backup(enc, self.priv, b"wrong passphrase!!")[0][0])
        enc.write_bytes(backup_crypto.encrypt(self.missing, self.pub_path.read_bytes()))
        self.assertFalse(all(ok for ok, _ in backup_crypto.verify_backup(enc, self.priv, PASS)))

    def test_verify_a_users_backup(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            info = tarfile.TarInfo("raqm-users-backup-20261104/u.tar.gz"); info.size = len(self.good)
            tar.addfile(info, io.BytesIO(self.good))
        enc = self.d / "raqm-users-backup-20261104.tar.gz.enc"
        enc.write_bytes(backup_crypto.encrypt(buf.getvalue(), self.pub_path.read_bytes()))
        res = backup_crypto.verify_backup(enc, self.priv, PASS)
        self.assertTrue(all(ok for ok, _ in res), res); self.assertIn("1 مستخدم", res[-1][1])


if __name__ == "__main__":
    unittest.main()
