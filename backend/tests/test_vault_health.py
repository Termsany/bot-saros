"""The API says whether users' Demo key vault opens (2026-11-04: it silently didn't, for days)."""
import os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
from cryptography.fernet import Fernet
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import user_keys_vault as ukv


class VaultHealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = [mock.patch.object(ukv, "VAULT_PATH", Path(self.tmp.name) / "user_vault.json"),
                  mock.patch.dict(os.environ, {"VAULT_MASTER_KEY": Fernet.generate_key().decode()})]
        for p in self.p: p.start()

    def tearDown(self):
        for p in reversed(self.p): p.stop()
        self.tmp.cleanup()

    def test_empty_ok_unreadable(self):
        self.assertEqual(ukv.vault_health(), "empty")
        ukv.save_user_keys("u1", "binance", "KEY-123", "SECRET-456")
        self.assertEqual(ukv.vault_health(), "ok")
        with mock.patch.dict(os.environ, {"VAULT_MASTER_KEY": Fernet.generate_key().decode()}):   # another key
            self.assertEqual(ukv.vault_health(), "unreadable")

    def test_health_carries_it_and_never_a_key(self):
        import app.main as m
        from fastapi.testclient import TestClient
        ukv.save_user_keys("u1", "binance", "KEY-123", "SECRET-456")
        r = TestClient(m.app).get("/api/health")
        self.assertEqual((r.status_code, r.json()["vault"]), (200, "ok"))
        self.assertNotIn("KEY-123", r.text); self.assertNotIn("SECRET-456", r.text)


if __name__ == "__main__":
    unittest.main()
