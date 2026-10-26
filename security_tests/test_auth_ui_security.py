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
    def test_auth_page_does_not_derive_recovery_mode_from_url_string(self):
        source = (ROOT / "app/auth/page.tsx").read_text(encoding="utf-8")
        # Regression guard for the recovery-mode spoofing vulnerability:
        # recovery UI must never be entered by hand-parsing
        # window.location.search / window.location.hash for "type=recovery".
        # That is attacker-controlled (e.g. a crafted /auth?type=recovery
        # link) and let anyone trick an already-logged-in victim into
        # resubmitting their password via updateUser() with no genuine
        # Supabase recovery session behind it.
        self.assertNotIn("window.location.search", source)
        self.assertNotIn("window.location.hash", source)
        self.assertNotIn('get("type")', source)
        self.assertNotIn("URLSearchParams", source)
        # The only call that may set recovery mode is inside the
        # onAuthStateChange("PASSWORD_RECOVERY") handler.
        set_mode_recovery_sites = [
            m.start() for m in re.finditer(r'setMode\("recovery"\)', source)
        ]
        self.assertEqual(len(set_mode_recovery_sites), 1)
        guard_index = source.index('event === "PASSWORD_RECOVERY"')
        self.assertLess(
            guard_index,
            set_mode_recovery_sites[0],
            "setMode(\"recovery\") must be reached only through the "
            "PASSWORD_RECOVERY auth-state-change guard",
        )

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


class AuthRecoveryBehaviorRegressionTests(unittest.TestCase):
    """Executes the real app/auth/page.tsx component logic (transpiled, with
    only unresolvable module imports mocked) against a fake React + mocked
    Supabase client to prove, behaviorally, that:
      * a spoofed `?type=recovery` / `#type=recovery` URL alone never
        enters recovery mode and never reaches updateUser(), and
      * a genuine PASSWORD_RECOVERY onAuthStateChange event does enter
        recovery mode and does call updateUser() exactly once.
    See security_tests/js_harness/compileAndRunRecoveryHarness.js.
    """

    HARNESS = ROOT / "security_tests" / "js_harness" / "compileAndRunRecoveryHarness.js"

    def test_recovery_mode_behavioral_harness(self):
        import shutil
        import subprocess

        node = shutil.which("node")
        if not node:
            self.skipTest("node is not available in this environment")

        result = subprocess.run(
            [node, str(self.HARNESS)],
            cwd=str(self.HARNESS.parent),
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn(
            "spoofed ?type=recovery query string alone does not enter recovery mode",
            output,
        )
        self.assertIn("submit() never calls updateUser", output)
        self.assertIn("genuine PASSWORD_RECOVERY event enters recovery mode", output)
        self.assertIn("submit() calls updateUser exactly once", output)
        self.assertNotIn("FAIL:", output)


if __name__ == "__main__":
    unittest.main()
