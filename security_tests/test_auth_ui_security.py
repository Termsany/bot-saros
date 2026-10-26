import os
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BACKEND))


class AuthUiSourceAuditTests(unittest.TestCase):
    def test_auth_page_has_no_project_url_or_raw_diagnostics(self):
        source = (ROOT / "app/auth/page.tsx").read_text(encoding="utf-8")
        forbidden = [
            "peefsudacgowngwvnouk.supabase.co",
            "Supabase Auth",
            "e.message",
            "e as any",
            "console.",
        ]
        for value in forbidden:
            self.assertNotIn(value, source)

    def test_password_recovery_flow_is_present_and_safe(self):
        source = (ROOT / "app/auth/page.tsx").read_text(encoding="utf-8")
        for value in (
            "PASSWORD_RECOVERY",
            "onAuthStateChange",
            "resetPasswordForEmail",
            "updateUser({ password: newPassword })",
            "newPassword !== confirmPassword",
            "newPassword.length < 8",
            "window.location.origin}/auth",
            "replaceState",
        ):
            self.assertIn(value, source)
        for value in ("error.message", "error as any", "access_token", "refresh_token", "console."):
            self.assertNotIn(value, source)

    def test_client_artifacts_have_no_private_key_markers(self):
        roots = [ROOT / "app/auth", ROOT / "components", ROOT / "lib/supabase.ts", ROOT / "next.config.js", ROOT / ".next/static"]
        files = []
        for root in roots:
            if root.is_file():
                files.append(root)
            elif root.exists():
                files.extend(p for p in root.rglob("*") if p.is_file())
        text = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in files)
        for pattern in (r"peefsudacgowngwvnouk\.supabase\.co", r"service_role", r"SUPABASE_SERVICE_KEY", r"STRIPE_SECRET_KEY", r"whsec_"):
            self.assertIsNone(re.search(pattern, text, re.IGNORECASE), pattern)


class BackendAuthRejectionAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from app import auth
        from app.main import app

        cls.auth = auth
        cls.app = app
        cls.client = TestClient(app)

        async def verify(token):
            users = {
                "user-token": {"id": "user", "email": "user@example.com", "email_confirmed": True},
                "admin-token": {"id": "admin", "email": "admin@example.com", "email_confirmed": True},
            }
            if token not in users:
                raise auth.HTTPException(401, "invalid")
            return users[token]

        cls.verify = verify

    def setUp(self):
        async def fake_verify(token):
            users = {
                "user-token": {"id": "user", "email": "user@example.com", "email_confirmed": True},
                "admin-token": {"id": "admin", "email": "admin@example.com", "email_confirmed": True},
            }
            if token not in users:
                raise self.auth.HTTPException(401, "invalid")
            return users[token]

        self.patch = mock.patch.object(self.auth, "_verify_token", fake_verify)
        self.patch.start()
        self.env = mock.patch.dict(os.environ, {"ADMIN_EMAILS": "admin@example.com", "ALLOW_LIVE_TRADING": "false"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.patch.stop()

    def test_protected_endpoint_rejects_anonymous_request(self):
        response = self.client.get("/api/user/me")
        self.assertEqual(response.status_code, 401)

    def test_admin_endpoint_rejects_authenticated_non_admin(self):
        response = self.client.get("/api/keys/status", headers={"Authorization": "Bearer user-token"})
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
