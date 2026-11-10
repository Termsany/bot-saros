"""P2.1 (docs/phase2-design.md): a user's bot takes its Binance keys from its systemd credential only."""
import os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "backend"))
import bot as botmod

OWNER = {"BINANCE_API_KEY": "owner-key", "BINANCE_SECRET": "owner-secret"}


class CredentialKeysTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.d = Path(self.td.name)
    def tearDown(self): self.td.cleanup()

    def env(self, **kw):
        e = {k: v for k, v in os.environ.items() if k != "CREDENTIALS_DIRECTORY"}; e.update(kw)
        return mock.patch.dict(os.environ, e, clear=True)

    def test_the_owners_bots_still_read_the_environment(self):
        with self.env(**OWNER):
            self.assertEqual(botmod._binance_keys(), ("owner-key", "owner-secret"))

    def test_a_users_bot_reads_its_credential(self):
        (self.d / "binance").write_text('BINANCE_API_KEY=user-key\nBINANCE_SECRET="user-secret"\nOTHER=x\n', encoding="utf-8")
        with self.env(CREDENTIALS_DIRECTORY=str(self.d), **OWNER):
            self.assertEqual(botmod._binance_keys(), ("user-key", "user-secret"))

    def test_a_missing_or_incomplete_credential_never_falls_back_to_other_keys(self):
        with self.env(CREDENTIALS_DIRECTORY=str(self.d), **OWNER):
            self.assertEqual(botmod._binance_keys(), ("", ""))                     # no file
            (self.d / "binance").write_text("BINANCE_API_KEY=user-key\n", encoding="utf-8")
            self.assertEqual(botmod._binance_keys(), ("user-key", ""))             # no secret
            ex, err = botmod.get_exchange(auth=True)
        self.assertIsNone(ex); self.assertTrue(err)

    def test_the_exchange_is_built_with_the_users_keys(self):
        (self.d / "binance").write_text("BINANCE_API_KEY=user-key\nBINANCE_SECRET=user-secret\n", encoding="utf-8")
        with self.env(CREDENTIALS_DIRECTORY=str(self.d), BINANCE_ENV="demo", **OWNER):
            ex, err = botmod.get_exchange(auth=True)
        self.assertIsNone(err); self.assertEqual((ex.apiKey, ex.secret), ("user-key", "user-secret"))


if __name__ == "__main__":
    unittest.main()
