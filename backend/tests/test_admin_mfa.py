"""2FA for the admin (owner, 2026-11-07): once an authenticator is set, a password-only session is not admin."""
import asyncio, base64, json, os, sys, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import auth

ADMIN = "owner@example.com"


def token(claims: dict) -> str:
    b = lambda o: base64.urlsafe_b64encode(json.dumps(o).encode()).decode().rstrip("=")
    return f"{b({'alg': 'ES256'})}.{b(claims)}.sig"


class FakeResp:
    def __init__(self, status, body): self.status_code, self._b = status, body
    def json(self): return self._b


def supabase_user(factors):
    return {"id": "u-1", "email": ADMIN, "email_confirmed_at": "2026-01-01T00:00:00Z", "factors": factors}


class AdminMfa(unittest.TestCase):
    def setUp(self):
        auth._CACHE.clear()
        self.env = mock.patch.dict(os.environ, {"SUPABASE_URL": "https://sb.test", "SUPABASE_ANON_KEY": "anon",
                                                "ADMIN_EMAILS": ADMIN, "ADMIN_USER_IDS": "", "ADMIN_REQUIRE_MFA": ""})
        self.env.start()

    def tearDown(self):
        self.env.stop(); auth._CACHE.clear()

    def admin(self, factors, aal, extra_env=None):
        """require_admin against a mocked Supabase /auth/v1/user, with a token carrying `aal`."""
        async def get(self_, url, headers=None):
            return FakeResp(200, supabase_user(factors))
        with mock.patch("httpx.AsyncClient.get", get), mock.patch.dict(os.environ, extra_env or {}):
            return asyncio.run(auth.require_admin(f"Bearer {token({'sub': 'u-1', 'aal': aal})}"))

    def refused(self, *a, **k):
        with self.assertRaises(HTTPException) as e:
            self.admin(*a, **k)
        self.assertEqual(e.exception.status_code, 403)
        return e.exception.detail

    def test_no_authenticator_yet_password_is_still_enough(self):
        self.assertEqual(self.admin([], "aal1")["email"], ADMIN)

    def test_with_an_authenticator_a_password_only_session_is_refused(self):
        self.assertIn("mfa_required", self.refused([{"id": "f", "factor_type": "totp", "status": "verified"}], "aal1"))

    def test_with_an_authenticator_a_session_that_passed_it_is_admin(self):
        u = self.admin([{"id": "f", "factor_type": "totp", "status": "verified"}], "aal2")
        self.assertEqual((u["mfa_enrolled"], u["aal"]), (True, "aal2"))

    def test_an_unfinished_enrollment_does_not_count(self):
        self.assertFalse(self.admin([{"id": "f", "factor_type": "totp", "status": "unverified"}], "aal1")["mfa_enrolled"])

    def test_required_flag_refuses_an_admin_without_an_authenticator(self):
        self.assertIn("mfa_enroll_required", self.refused([], "aal1", {"ADMIN_REQUIRE_MFA": "1"}))

    def test_a_garbled_or_missing_aal_is_aal1(self):
        self.assertEqual(auth._token_aal("not-a-jwt"), "aal1")
        self.assertEqual(auth._token_aal(token({"aal": "aal9"})), "aal1")
        self.assertEqual(auth._token_aal(token({})), "aal1")

    def test_cron_secret_is_not_affected(self):
        with mock.patch.dict(os.environ, {"CRON_SECRET": "s3"}):
            self.assertEqual(asyncio.run(auth.require_admin_or_cron("", "s3"))["id"], "cron")

    def test_user_me_tells_the_site_whether_to_ask_for_the_code(self):
        from app.main import app
        async def fake(tok):
            return {"id": "u-1", "email": ADMIN, "email_confirmed": True, "mfa_enrolled": True, "aal": "aal1"}
        with mock.patch.object(auth, "_verify_token", fake):
            c = TestClient(app)
            j = c.get("/api/user/me", headers={"Authorization": "Bearer x"}).json()
            self.assertEqual(j, {"admin": True, "mfa": {"enrolled": True, "aal": "aal1", "required": False}})
            self.assertEqual(c.get("/api/admin/user-bots", headers={"Authorization": "Bearer x"}).status_code, 403)

    def test_a_normal_user_gets_no_mfa_block(self):
        from app.main import app
        async def fake(tok):
            return {"id": "u-2", "email": "someone@example.com", "email_confirmed": True, "mfa_enrolled": False, "aal": "aal1"}
        with mock.patch.object(auth, "_verify_token", fake):
            self.assertEqual(TestClient(app).get("/api/user/me", headers={"Authorization": "Bearer x"}).json(), {"admin": False})


if __name__ == "__main__":
    unittest.main()
