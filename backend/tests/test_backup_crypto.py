"""Encrypted backups (security plan item 11, owner 2026-11-08): the server locks, only the owner's private key opens."""
import sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import backup, backup_crypto

PASS = b"a long passphrase 123"


class BackupCryptoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); d = Path(cls.td.name)
        backup_crypto.keygen(d, PASS)
        cls.pub, cls.priv = (d / "backup-public.pem").read_bytes(), (d / "backup-private.pem").read_bytes()
        cls.dir = d

    @classmethod
    def tearDownClass(cls):
        cls.td.cleanup()

    def test_only_the_private_key_with_its_passphrase_opens_a_backup(self):
        blob = backup_crypto.encrypt(b"the archive", self.pub)
        self.assertTrue(blob.startswith(backup_crypto.MAGIC)); self.assertNotIn(b"the archive", blob)
        self.assertEqual(backup_crypto.decrypt(blob, self.priv, PASS), b"the archive")
        with self.assertRaises(Exception): backup_crypto.decrypt(blob, self.priv, b"wrong passphrase!!")
        bad = blob[:-1] + bytes([blob[-1] ^ 1])
        with self.assertRaises(Exception): backup_crypto.decrypt(bad, self.priv, PASS)      # a changed byte is caught
        self.assertNotEqual(backup_crypto.encrypt(b"x", self.pub), backup_crypto.encrypt(b"x", self.pub))   # a new key each time
        self.assertNotIn(b"PRIVATE", self.pub); self.assertIn(b"ENCRYPTED PRIVATE KEY", self.priv)

    def test_a_weak_key_is_refused(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        small = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        with self.assertRaises(ValueError): backup_crypto.encrypt(b"x", small)

    def run_main(self, pubkey_path):
        sent = []
        with mock.patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"}), \
             mock.patch.object(backup_crypto, "PUBLIC_KEY", pubkey_path), \
             mock.patch.object(backup, "all_sources", return_value={}), \
             mock.patch.object(backup, "build", return_value=(b"archive bytes", 3)), \
             mock.patch.object(backup, "_post", side_effect=lambda m, f, files=None: sent.append((m, f, files))):
            backup.main()
        return sent[0]

    def test_with_the_key_installed_telegram_gets_only_the_locked_file(self):
        m, f, files = self.run_main(self.dir / "backup-public.pem")
        name, data = files["document"]
        self.assertTrue(name.endswith(".tar.gz.enc")); self.assertIn("🔒", f["caption"])
        self.assertNotIn(b"archive bytes", data)
        self.assertEqual(backup_crypto.decrypt(data, self.priv, PASS), b"archive bytes")

    def test_without_the_key_it_still_goes_and_says_it_is_not_encrypted(self):
        m, f, files = self.run_main(self.dir / "absent.pem")
        self.assertEqual(files["document"], ("raqm-backup-" + files["document"][0][12:20] + ".tar.gz", b"archive bytes"))
        self.assertIn("مش متشفّرة", f["caption"])

    def test_a_broken_key_sends_nothing_in_the_clear(self):
        (self.dir / "broken.pem").write_text("not a key", encoding="utf-8")
        sent = []
        with mock.patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"}), \
             mock.patch.object(backup_crypto, "PUBLIC_KEY", self.dir / "broken.pem"), \
             mock.patch.object(backup, "all_sources", return_value={}), \
             mock.patch.object(backup, "build", return_value=(b"archive bytes", 3)), \
             mock.patch.object(backup, "_post", side_effect=lambda m, f, files=None: sent.append((m, f, files))):
            with self.assertRaises(Exception): backup.main()
        self.assertEqual([s[0] for s in sent], ["sendMessage"])                       # the failure, never the archive


if __name__ == "__main__":
    unittest.main()
