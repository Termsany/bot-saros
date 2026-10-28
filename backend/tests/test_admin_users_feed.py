"""
Unit tests for app.admin_users — the Supabase GoTrue + profiles + local
user_settings merge layer behind the admin "Users & Plans & Bots" tab.

All HTTP calls go through httpx.MockTransport. No real network call to
Supabase is ever made in this file.
"""
import sys
import unittest
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app import admin_users


def _env(monkeypatch=None):
    return {"SUPABASE_URL": "https://example.supabase.co", "SUPABASE_SERVICE_KEY": "sb_secret_test_key_not_real"}


class FetchGotrueUsersTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_config_reports_unavailable_without_network_call(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"SUPABASE_URL": "", "SUPABASE_SERVICE_KEY": ""}, clear=False):
            result = await admin_users.fetch_gotrue_users()
        self.assertFalse(result["available"])
        self.assertEqual(result["users"], [])
        self.assertIn("not configured", result["error"])

    async def test_success_returns_users_list(self):
        import os
        from unittest import mock

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/auth/v1/admin/users")
            return httpx.Response(200, json={"users": [
                {"id": "u1", "email": "a@example.com", "created_at": "2026-01-01T00:00:00Z",
                 "email_confirmed_at": "2026-01-01T00:00:00Z", "banned_until": None},
                {"id": "u2", "email": "b@example.com", "created_at": "2026-02-01T00:00:00Z",
                 "email_confirmed_at": None, "banned_until": "2099-01-01T00:00:00Z"},
            ]})

        with mock.patch.dict(os.environ, _env(), clear=False):
            result = await admin_users.fetch_gotrue_users(transport=httpx.MockTransport(handler))
        self.assertTrue(result["available"])
        self.assertEqual(len(result["users"]), 2)

    async def test_non_200_reports_unavailable_never_raises(self):
        import os
        from unittest import mock

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"msg": "invalid key"})

        with mock.patch.dict(os.environ, _env(), clear=False):
            result = await admin_users.fetch_gotrue_users(transport=httpx.MockTransport(handler))
        self.assertFalse(result["available"])
        self.assertEqual(result["users"], [])
        self.assertIn("401", result["error"])
        # the error message must never contain the service key
        self.assertNotIn("sb_secret_test_key_not_real", result["error"])

    async def test_network_error_reports_unavailable_never_raises(self):
        import os
        from unittest import mock

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        with mock.patch.dict(os.environ, _env(), clear=False):
            result = await admin_users.fetch_gotrue_users(transport=httpx.MockTransport(handler))
        self.assertFalse(result["available"])
        self.assertEqual(result["users"], [])


class FetchProfileTiersTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_maps_id_to_tier(self):
        import os
        from unittest import mock

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/rest/v1/profiles")
            return httpx.Response(200, json=[{"id": "u1", "tier": "pro"}, {"id": "u2", "tier": "free"}])

        with mock.patch.dict(os.environ, _env(), clear=False):
            result = await admin_users.fetch_profile_tiers(transport=httpx.MockTransport(handler))
        self.assertTrue(result["available"])
        self.assertEqual(result["tiers"], {"u1": "pro", "u2": "free"})

    async def test_failure_reports_unavailable(self):
        import os
        from unittest import mock

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={})

        with mock.patch.dict(os.environ, _env(), clear=False):
            result = await admin_users.fetch_profile_tiers(transport=httpx.MockTransport(handler))
        self.assertFalse(result["available"])
        self.assertEqual(result["tiers"], {})


class SetUserBanTests(unittest.IsolatedAsyncioTestCase):
    async def test_ban_sends_indefinite_duration(self):
        import os, json
        from unittest import mock
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["path"] = request.url.path
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"id": "u1"})

        with mock.patch.dict(os.environ, _env(), clear=False):
            result = await admin_users.set_user_ban("u1", True, transport=httpx.MockTransport(handler))
        self.assertTrue(result["ok"])
        self.assertEqual(seen["path"], "/auth/v1/admin/users/u1")
        self.assertEqual(seen["body"]["ban_duration"], admin_users.INDEFINITE_BAN)

    async def test_unban_sends_none(self):
        import os, json
        from unittest import mock
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"id": "u1"})

        with mock.patch.dict(os.environ, _env(), clear=False):
            result = await admin_users.set_user_ban("u1", False, transport=httpx.MockTransport(handler))
        self.assertTrue(result["ok"])
        self.assertEqual(seen["body"]["ban_duration"], "none")

    async def test_failure_reports_ok_false_never_raises(self):
        import os
        from unittest import mock

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"msg": "nope"})

        with mock.patch.dict(os.environ, _env(), clear=False):
            result = await admin_users.set_user_ban("u1", True, transport=httpx.MockTransport(handler))
        self.assertFalse(result["ok"])
        self.assertIn("403", result["error"])


class MergeUsersTests(unittest.TestCase):
    def test_merges_tier_and_local_settings_and_counts_plans(self):
        gotrue = {"available": True, "error": None, "users": [
            {"id": "u1", "email": "a@example.com", "created_at": "2026-01-01T00:00:00Z",
             "last_sign_in_at": "2026-03-01T00:00:00Z", "email_confirmed_at": "2026-01-01T00:00:00Z", "banned_until": None},
            {"id": "u2", "email": "b@example.com", "created_at": "2026-02-01T00:00:00Z",
             "last_sign_in_at": None, "email_confirmed_at": None, "banned_until": "2099-01-01T00:00:00Z"},
        ]}
        tiers = {"available": True, "error": None, "tiers": {"u1": "pro"}}
        local = {"u1": {"capital": 500.0, "strategy": "trend_daily", "started_at": "2026-01-02", "updated_at": "2026-01-03"}}
        merged = admin_users.merge_users(gotrue, tiers, local)
        self.assertTrue(merged["available"])
        self.assertEqual(merged["total"], 2)
        by_id = {u["id"]: u for u in merged["users"]}
        self.assertEqual(by_id["u1"]["tier"], "pro")
        self.assertEqual(by_id["u1"]["capital"], 500.0)
        self.assertFalse(by_id["u1"]["banned"])
        # u2 has no profiles row -> defaults to free, no local settings -> None fields, and is banned
        self.assertEqual(by_id["u2"]["tier"], "free")
        self.assertIsNone(by_id["u2"]["capital"])
        self.assertTrue(by_id["u2"]["banned"])
        self.assertEqual(merged["plan_counts"], {"pro": 1, "free": 1})

    def test_gotrue_unavailable_propagates_and_never_fabricates_users(self):
        gotrue = {"available": False, "error": "ConnectError", "users": []}
        tiers = {"available": True, "error": None, "tiers": {}}
        merged = admin_users.merge_users(gotrue, tiers, {})
        self.assertFalse(merged["available"])
        self.assertEqual(merged["users"], [])
        self.assertEqual(merged["total"], 0)
        self.assertEqual(merged["error"], "ConnectError")

    def test_merged_output_never_contains_a_secret_like_field(self):
        gotrue = {"available": True, "error": None, "users": [
            {"id": "u1", "email": "a@example.com", "created_at": "2026-01-01T00:00:00Z",
             "last_sign_in_at": None, "email_confirmed_at": None, "banned_until": None,
             "encrypted_password": "should-never-surface"},
        ]}
        merged = admin_users.merge_users(gotrue, {"available": True, "error": None, "tiers": {}}, {})
        dumped = str(merged)
        self.assertNotIn("should-never-surface", dumped)
        self.assertNotIn("encrypted_password", str(merged["users"][0]))


if __name__ == "__main__":
    unittest.main()
