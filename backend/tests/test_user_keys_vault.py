"""Per-user encrypted key vault — key isolation between users (TDD)."""
import sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from unittest import mock
from app import user_keys_vault as ukv


class UserKeysVaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.patches = [mock.patch.object(ukv, "VAULT_PATH", Path(self.tmp.name) / "user_vault.json")]
        for p in self.patches:
            p.start()
        import os
        self._old_master = os.environ.get("VAULT_MASTER_KEY")
        from cryptography.fernet import Fernet
        os.environ["VAULT_MASTER_KEY"] = Fernet.generate_key().decode()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        import os
        if self._old_master is None:
            os.environ.pop("VAULT_MASTER_KEY", None)
        else:
            os.environ["VAULT_MASTER_KEY"] = self._old_master
        self.tmp.cleanup()

    def test_save_and_load_roundtrip(self):
        ukv.save_user_keys("user-a", "binance", "AKEY", "ASECRET", "")
        loaded = ukv.load_user_keys("user-a", "binance")
        self.assertEqual(loaded["apiKey"], "AKEY")
        self.assertEqual(loaded["secret"], "ASECRET")
        self.assertTrue(loaded["paper"])  # new keys always start paper

    def test_users_are_isolated_from_each_other(self):
        ukv.save_user_keys("user-a", "binance", "AKEY", "ASECRET", "")
        ukv.save_user_keys("user-b", "binance", "BKEY", "BSECRET", "")
        a = ukv.load_user_keys("user-a", "binance")
        b = ukv.load_user_keys("user-b", "binance")
        self.assertEqual(a["apiKey"], "AKEY")
        self.assertEqual(b["apiKey"], "BKEY")
        # user-a cannot read user-b's keys via any path
        self.assertIsNone(ukv.load_user_keys("user-a", "bybit"))  # a never configured bybit
        self.assertNotEqual(a["apiKey"], b["apiKey"])

    def test_delete_only_removes_that_users_keys(self):
        ukv.save_user_keys("user-a", "binance", "AKEY", "ASECRET", "")
        ukv.save_user_keys("user-b", "binance", "BKEY", "BSECRET", "")
        self.assertTrue(ukv.delete_user_keys("user-a", "binance"))
        self.assertIsNone(ukv.load_user_keys("user-a", "binance"))
        b = ukv.load_user_keys("user-b", "binance")
        self.assertEqual(b["apiKey"], "BKEY")  # untouched

    def test_status_never_exposes_secrets(self):
        ukv.save_user_keys("user-a", "binance", "AKEY", "ASECRET", "")
        status = ukv.user_key_status("user-a")
        self.assertTrue(status["binance"]["configured"])
        self.assertNotIn("apiKey", status["binance"])
        self.assertNotIn("secret", status["binance"])

    def test_unknown_exchange_rejected(self):
        with self.assertRaises(ValueError):
            ukv.save_user_keys("user-a", "not-an-exchange", "K", "S", "")

    def test_missing_user_status_is_all_unconfigured(self):
        status = ukv.user_key_status("nobody")
        self.assertTrue(all(not v["configured"] for v in status.values()))


if __name__ == "__main__":
    unittest.main()
