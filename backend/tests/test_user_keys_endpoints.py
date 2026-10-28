"""API-level tests for /api/user/keys/* and /api/user/live/* — any registered
user can manage their own key and live-enable record; cross-user access is
rejected because every endpoint is scoped by the authenticated session's own
user id, never by a client-supplied id."""
import asyncio, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient
from app import auth, keys_vault, user_keys_vault, user_live_activation

USER_A = {"id": "u-aaa", "email": "a@example.com", "email_confirmed": True}
USER_B = {"id": "u-bbb", "email": "b@example.com", "email_confirmed": True}
TOKENS = {"a-token": USER_A, "b-token": USER_B}


async def fake_verify(token):
    if token not in TOKENS:
        raise auth.HTTPException(401, "invalid")
    return TOKENS[token]


class UserKeysEndpointsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        from cryptography.fernet import Fernet
        self.patches = [
            mock.patch.object(auth, "_verify_token", fake_verify),
            mock.patch.object(keys_vault, "VAULT_PATH", Path(self.tmp.name) / "vault.json"),
            mock.patch.object(user_keys_vault, "VAULT_PATH", Path(self.tmp.name) / "user_vault.json"),
            mock.patch.dict(os.environ, {"ADMIN_EMAILS": "admin@example.com", "ALLOW_LIVE_TRADING": "",
                                         "VAULT_MASTER_KEY": Fernet.generate_key().decode()}),
        ]
        for p in self.patches:
            p.start()
        import app.main as mainmod
        mainmod.app.dependency_overrides = {}
        self._orig_botdir = mainmod.BOT_DIR
        self.botdir = Path(self.tmp.name) / "botdir"
        self.botdir.mkdir()
        mainmod.BOT_DIR = self.botdir
        mainmod.USER_LIVE_ACTIVATION_PATH = self.botdir / "user_live_activation.sqlite3"
        import app.auth as authmod
        authmod._verify_token = fake_verify
        self.mainmod = mainmod
        self.client = TestClient(mainmod.app)

    def tearDown(self):
        self.mainmod.BOT_DIR = self._orig_botdir
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def h(self, tok):
        return {"Authorization": f"Bearer {tok}"}

    def test_user_can_save_and_see_only_their_own_key(self):
        r = self.client.post("/api/user/keys/save", headers=self.h("a-token"),
                              json={"exchange": "binance", "apiKey": "AKEY", "secret": "ASECRET"})
        self.assertEqual(r.status_code, 200)
        status_a = self.client.get("/api/user/keys/status", headers=self.h("a-token")).json()
        self.assertTrue(status_a["binance"]["configured"])
        status_b = self.client.get("/api/user/keys/status", headers=self.h("b-token")).json()
        self.assertFalse(status_b["binance"]["configured"])

    def test_cross_user_key_access_is_rejected_by_identity_not_by_request_body(self):
        self.client.post("/api/user/keys/save", headers=self.h("a-token"),
                          json={"exchange": "binance", "apiKey": "AKEY", "secret": "ASECRET"})
        # user B cannot read A's key even though the endpoint takes no user_id param to spoof
        status_b = self.client.get("/api/user/keys/status", headers=self.h("b-token")).json()
        self.assertFalse(status_b["binance"]["configured"])
        # user B deleting "binance" only ever deletes their own (nonexistent) entry
        r = self.client.post("/api/user/keys/delete", headers=self.h("b-token"), json={"exchange": "binance"})
        self.assertEqual(r.json(), {"ok": False})
        status_a = self.client.get("/api/user/keys/status", headers=self.h("a-token")).json()
        self.assertTrue(status_a["binance"]["configured"])  # untouched by B's delete

    def test_unauthenticated_requests_are_rejected(self):
        r = self.client.get("/api/user/keys/status")
        self.assertEqual(r.status_code, 401)
        r = self.client.post("/api/user/live/enable", json={"exchange": "binance", "confirm": "x"})
        self.assertEqual(r.status_code, 401)

    def test_live_enable_requires_keys_first(self):
        r = self.client.post("/api/user/live/enable", headers=self.h("a-token"),
                              json={"exchange": "binance", "confirm": user_live_activation.CONSENT_TEXT})
        self.assertEqual(r.status_code, 400)
        self.assertIn("API key", r.json()["detail"])

    def test_live_enable_requires_exact_consent_text(self):
        self.client.post("/api/user/keys/save", headers=self.h("a-token"),
                          json={"exchange": "binance", "apiKey": "AKEY", "secret": "ASECRET"})
        r = self.client.post("/api/user/live/enable", headers=self.h("a-token"),
                              json={"exchange": "binance", "confirm": "sure whatever"})
        self.assertEqual(r.status_code, 400)
        status = self.client.get("/api/user/live/status", headers=self.h("a-token")).json()
        self.assertFalse(status["enabled"])

    def test_live_enable_end_to_end_defaults_and_isolation_from_other_users(self):
        self.client.post("/api/user/keys/save", headers=self.h("a-token"),
                          json={"exchange": "binance", "apiKey": "AKEY", "secret": "ASECRET"})
        r = self.client.post("/api/user/live/enable", headers=self.h("a-token"),
                              json={"exchange": "binance", "confirm": user_live_activation.CONSENT_TEXT})
        self.assertEqual(r.status_code, 200)
        status_a = self.client.get("/api/user/live/status", headers=self.h("a-token")).json()
        self.assertTrue(status_a["enabled"])
        self.assertEqual(status_a["leverage"], 2)
        self.assertEqual(status_a["risk_per_trade_pct"], 0.25)
        self.assertEqual(status_a["max_aggregate_risk_pct"], 1.0)
        # user B is completely unaffected — their own record (none) stays disabled
        status_b = self.client.get("/api/user/live/status", headers=self.h("b-token")).json()
        self.assertFalse(status_b["enabled"])

    def test_disable_only_affects_the_caller(self):
        self.client.post("/api/user/keys/save", headers=self.h("a-token"),
                          json={"exchange": "binance", "apiKey": "AKEY", "secret": "ASECRET"})
        self.client.post("/api/user/live/enable", headers=self.h("a-token"),
                          json={"exchange": "binance", "confirm": user_live_activation.CONSENT_TEXT})
        r = self.client.post("/api/user/live/disable", headers=self.h("b-token"))
        self.assertEqual(r.status_code, 200)
        status_a = self.client.get("/api/user/live/status", headers=self.h("a-token")).json()
        self.assertTrue(status_a["enabled"])  # B's disable call never touched A's record

    def test_admin_live_activation_env_flag_and_module_are_unaffected(self):
        """The admin's own ALLOW_LIVE_TRADING / live_activation.py path is untouched."""
        from app import live_activation
        self.assertFalse(self.mainmod.live_trading_allowed())
        with self.assertRaises(PermissionError):
            live_activation.activate(self.mainmod.LIVE_ACTIVATION_PATH, environment="live", account="admin",
                                      approved_by="admin", strategies=["trend_daily"],
                                      risk_allocation={"trend_daily": 1.0}, readiness={"trend_daily": True})


if __name__ == "__main__":
    unittest.main()
