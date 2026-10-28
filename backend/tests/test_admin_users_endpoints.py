"""
Endpoint-level tests for the admin "Users & Plans & Bots" tab:
GET /api/admin/users and POST /api/admin/users/{user_id}/ban.

All Supabase GoTrue/profiles calls go through app.admin_users, which is
monkeypatched here to deterministic fakes — never real network calls.
"""
import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient
from app import auth

ADMIN = {"id": "u-admin", "email": "admin@example.com", "email_confirmed": True}
USER = {"id": "u-user", "email": "user@example.com", "email_confirmed": True}
TOKENS = {"admin-token": ADMIN, "user-token": USER}


async def fake_verify(token):
    if token not in TOKENS:
        raise auth.HTTPException(401, "invalid")
    return TOKENS[token]


def _fake_gotrue_result():
    return {"available": True, "error": None, "users": [
        {"id": "u1", "email": "alice@example.com", "created_at": "2026-01-01T00:00:00Z",
         "last_sign_in_at": "2026-03-01T00:00:00Z", "email_confirmed_at": "2026-01-01T00:00:00Z", "banned_until": None},
        {"id": "u2", "email": "bob@example.com", "created_at": "2026-02-01T00:00:00Z",
         "last_sign_in_at": None, "email_confirmed_at": None, "banned_until": "2099-01-01T00:00:00Z"},
    ]}


def _fake_tiers_result():
    return {"available": True, "error": None, "tiers": {"u1": "pro"}}


class AdminUsersEndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [
            mock.patch.object(auth, "_verify_token", fake_verify),
            mock.patch.dict(os.environ, {"ADMIN_EMAILS": ADMIN["email"], "ALLOW_LIVE_TRADING": ""}),
        ]
        for p in self.patches:
            p.start()
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        import app.db as dbmod
        self.db_path = Path(self.tmp.name) / "admin_users.db"
        self.eng = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", echo=False)
        self.session_maker = async_sessionmaker(self.eng, expire_on_commit=False)

        async def _create_all():
            async with self.eng.begin() as conn:
                await conn.run_sync(dbmod.Base.metadata.create_all)

        asyncio.run(_create_all())
        import app.main as mainmod
        self.db_patches = [mock.patch.object(mainmod, "async_session", self.session_maker)]
        for p in self.db_patches:
            p.start()
        mainmod.app.dependency_overrides = {}
        self._orig_botdir = mainmod.BOT_DIR
        self.botdir = Path(self.tmp.name) / "botdir"
        self.botdir.mkdir()
        mainmod.BOT_DIR = self.botdir
        import app.auth as authmod
        authmod._verify_token = fake_verify
        self.mainmod = mainmod
        self.client = TestClient(mainmod.app)

        async def seed():
            async with self.session_maker() as sess:
                sess.add(dbmod.UserSetting(user_id="u1", capital=500.0, strategy="trend_daily",
                                            started_at="2026-01-02", updated_at="2026-01-03"))
                await sess.commit()

        asyncio.run(seed())

        from app import admin_users
        self.fetch_users_patch = mock.patch.object(
            mainmod.admin_users, "fetch_gotrue_users", mock.AsyncMock(return_value=_fake_gotrue_result()))
        self.fetch_tiers_patch = mock.patch.object(
            mainmod.admin_users, "fetch_profile_tiers", mock.AsyncMock(return_value=_fake_tiers_result()))
        self.fetch_users_patch.start()
        self.fetch_tiers_patch.start()
        self.ban_mock = mock.AsyncMock(return_value={"ok": True})
        self.ban_patch = mock.patch.object(mainmod.admin_users, "set_user_ban", self.ban_mock)
        self.ban_patch.start()

    def tearDown(self):
        self.ban_patch.stop()
        self.fetch_tiers_patch.stop()
        self.fetch_users_patch.stop()
        self.mainmod.BOT_DIR = self._orig_botdir
        for p in self.db_patches:
            p.stop()
        for p in self.patches:
            p.stop()
        try:
            asyncio.run(self.eng.dispose())
        except Exception:
            pass
        self.tmp.cleanup()

    def _admin_headers(self):
        return {"Authorization": "Bearer admin-token"}

    def _user_headers(self):
        return {"Authorization": "Bearer user-token"}

    # ── GET /api/admin/users ─────────────────────────────────────────
    def test_users_requires_admin(self):
        r = self.client.get("/api/admin/users")
        self.assertEqual(r.status_code, 401)
        r2 = self.client.get("/api/admin/users", headers=self._user_headers())
        self.assertEqual(r2.status_code, 403)

    def test_users_merges_supabase_and_local_settings(self):
        r = self.client.get("/api/admin/users", headers=self._admin_headers())
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertTrue(j["available"])
        self.assertEqual(j["total"], 2)
        by_id = {u["id"]: u for u in j["users"]}
        self.assertEqual(by_id["u1"]["tier"], "pro")
        self.assertEqual(by_id["u1"]["capital"], 500.0)
        self.assertEqual(by_id["u1"]["strategy"], "trend_daily")
        self.assertFalse(by_id["u1"]["banned"])
        self.assertEqual(by_id["u2"]["tier"], "free")
        self.assertTrue(by_id["u2"]["banned"])
        self.assertEqual(j["plan_counts"], {"pro": 1, "free": 1})
        # never surface a secret
        self.assertNotIn("SUPABASE_SERVICE_KEY", str(j))
        self.assertNotIn("service_role", str(j))

    def test_users_degrades_gracefully_when_supabase_unreachable(self):
        import app.main as mainmod
        mainmod.admin_users.fetch_gotrue_users = mock.AsyncMock(
            return_value={"available": False, "error": "ConnectError", "users": []})
        r = self.client.get("/api/admin/users", headers=self._admin_headers())
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertFalse(j["available"])
        self.assertEqual(j["users"], [])
        self.assertEqual(j["error"], "ConnectError")

    # ── POST /api/admin/users/{id}/ban ───────────────────────────────
    def test_ban_requires_admin(self):
        r = self.client.post("/api/admin/users/u2/ban", json={"banned": True, "confirm": True})
        self.assertEqual(r.status_code, 401)

    def test_ban_requires_confirmation(self):
        r = self.client.post("/api/admin/users/u2/ban", headers=self._admin_headers(), json={"banned": True})
        self.assertEqual(r.status_code, 400)
        self.ban_mock.assert_not_called()

    def test_ban_calls_admin_users_and_audits(self):
        r = self.client.post("/api/admin/users/u2/ban", headers=self._admin_headers(),
                              json={"banned": True, "confirm": True})
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertTrue(j["ok"])
        self.assertEqual(j["user_id"], "u2")
        self.ban_mock.assert_awaited_once_with("u2", True)
        audit = self.client.get("/api/admin/audit", headers=self._admin_headers()).json()["items"]
        self.assertEqual(audit[0]["action"], "user_ban")
        self.assertEqual(audit[0]["result"], "ok")

    def test_unban_calls_admin_users_with_false(self):
        r = self.client.post("/api/admin/users/u2/ban", headers=self._admin_headers(),
                              json={"banned": False, "confirm": True})
        self.assertEqual(r.status_code, 200)
        self.ban_mock.assert_awaited_once_with("u2", False)

    def test_ban_failure_returns_502_and_audits_failure(self):
        self.mainmod.admin_users.set_user_ban = mock.AsyncMock(return_value={"ok": False, "error": "http 403"})
        r = self.client.post("/api/admin/users/u2/ban", headers=self._admin_headers(),
                              json={"banned": True, "confirm": True})
        self.assertEqual(r.status_code, 502)
        audit = self.client.get("/api/admin/audit", headers=self._admin_headers()).json()["items"]
        self.assertEqual(audit[0]["action"], "user_ban")
        self.assertEqual(audit[0]["result"], "failed")

    # ── PATCH /api/admin/users/{id}/settings ─────────────────────────
    def test_settings_patch_requires_admin(self):
        r = self.client.patch("/api/admin/users/u1/settings", json={"capital": 1000, "confirm": True})
        self.assertEqual(r.status_code, 401)
        r2 = self.client.patch("/api/admin/users/u1/settings", headers=self._user_headers(),
                                json={"capital": 1000, "confirm": True})
        self.assertEqual(r2.status_code, 403)

    def test_settings_patch_requires_confirmation(self):
        r = self.client.patch("/api/admin/users/u1/settings", headers=self._admin_headers(),
                               json={"capital": 1000})
        self.assertEqual(r.status_code, 400)
        audit = self.client.get("/api/admin/audit", headers=self._admin_headers()).json()["items"]
        self.assertEqual(audit, [])

    def test_settings_patch_requires_at_least_one_field(self):
        r = self.client.patch("/api/admin/users/u1/settings", headers=self._admin_headers(),
                               json={"confirm": True})
        self.assertEqual(r.status_code, 400)

    def test_settings_patch_rejects_unknown_strategy(self):
        r = self.client.patch("/api/admin/users/u1/settings", headers=self._admin_headers(),
                               json={"strategy": "not_a_real_strategy", "confirm": True})
        self.assertEqual(r.status_code, 400)

    def test_settings_patch_updates_existing_row_and_audits(self):
        r = self.client.patch("/api/admin/users/u1/settings", headers=self._admin_headers(),
                               json={"capital": 1234.5, "strategy": "momentum_ls", "confirm": True})
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertTrue(j["ok"])
        self.assertEqual(j["capital"], 1234.5)
        self.assertEqual(j["strategy"], "momentum_ls")
        audit = self.client.get("/api/admin/audit", headers=self._admin_headers()).json()["items"]
        self.assertEqual(audit[0]["action"], "user_settings_update")
        self.assertEqual(audit[0]["result"], "ok")
        # confirm it actually persisted, not just echoed
        r2 = self.client.get("/api/admin/users", headers=self._admin_headers())
        by_id = {u["id"]: u for u in r2.json()["users"]}
        self.assertEqual(by_id["u1"]["capital"], 1234.5)
        self.assertEqual(by_id["u1"]["strategy"], "momentum_ls")

    def test_settings_patch_creates_row_for_user_with_no_prior_settings(self):
        r = self.client.patch("/api/admin/users/u2/settings", headers=self._admin_headers(),
                               json={"capital": 50.0, "confirm": True})
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertEqual(j["capital"], 50.0)
        self.assertIsNone(j["strategy"])

    def test_settings_patch_partial_update_keeps_other_field(self):
        self.client.patch("/api/admin/users/u1/settings", headers=self._admin_headers(),
                           json={"capital": 777.0, "confirm": True})
        r = self.client.patch("/api/admin/users/u1/settings", headers=self._admin_headers(),
                               json={"strategy": "ratio_trend", "confirm": True})
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertEqual(j["capital"], 777.0)
        self.assertEqual(j["strategy"], "ratio_trend")

    # ── GET /api/admin/finance ────────────────────────────────────────
    def test_finance_requires_admin(self):
        r = self.client.get("/api/admin/finance")
        self.assertEqual(r.status_code, 401)
        r2 = self.client.get("/api/admin/finance", headers=self._user_headers())
        self.assertEqual(r2.status_code, 403)

    def test_finance_computes_mrr_from_plan_counts(self):
        # fixture tiers: u1 -> pro, u2 -> free (default) => plan_counts {pro:1, free:1}
        r = self.client.get("/api/admin/finance", headers=self._admin_headers())
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertTrue(j["available"])
        self.assertEqual(j["plan_counts"], {"pro": 1, "free": 1})
        self.assertEqual(j["finance"]["mrr_usd"], 59)
        self.assertEqual(j["finance"]["per_tier"]["pro"]["revenue_usd"], 59)
        self.assertEqual(j["finance"]["paying_users"], 1)
        self.assertEqual(j["finance"]["free_users"], 1)

    def test_finance_degrades_gracefully_when_supabase_unreachable(self):
        self.mainmod.admin_users.fetch_gotrue_users = mock.AsyncMock(
            return_value={"available": False, "error": "ConnectError", "users": []})
        r = self.client.get("/api/admin/finance", headers=self._admin_headers())
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertFalse(j["available"])
        self.assertEqual(j["plan_counts"], {})
        self.assertEqual(j["finance"]["mrr_usd"], 0)


if __name__ == "__main__":
    unittest.main()
