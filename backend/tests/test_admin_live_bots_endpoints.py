"""
Endpoint-level regression tests for the live VPS bots data wired into
/api/admin/overview, /api/admin/strategies, /api/admin/paper/portfolio.

All VPS HTTP calls are faked via httpx.MockTransport (monkeypatched into
live_bots_feed.fetch_all's AsyncClient creation is avoided — instead we
patch live_bots_feed.base_url + inject a MockTransport through the real
fetch_all call path) so these tests never touch the real network.
"""
import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import httpx

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient
from app import auth, live_bots_feed

ADMIN = {"id": "u-admin", "email": "admin@example.com", "email_confirmed": True}
USER = {"id": "u-user", "email": "user@example.com", "email_confirmed": True}
TOKENS = {"admin-token": ADMIN, "user-token": USER}


async def fake_verify(token):
    if token not in TOKENS:
        raise auth.HTTPException(401, "invalid")
    return TOKENS[token]


def _fresh_payload():
    now = datetime.now(timezone.utc).isoformat()
    return {
        "updated": now, "mode": "paper",
        "stats": {"closed": 1, "wins": 1, "losses": 0, "realized": 5.0, "unrealized": 1.0, "open": 1},
        "positions": [{"symbol": "BTC/USDT", "side": "long", "entry": 100, "price": 101, "qty": 1,
                       "margin": 10, "sl": 95, "tp": 110, "pnl": 1.0, "pnl_pct": 1.0, "opened": now}],
        "history": [{"symbol": "ETH/USDT", "side": "short", "entry": 10, "exit": 9, "qty": 1, "pnl": 1.0}],
    }


def _mock_transport_all_ok():
    def handler(request):
        return httpx.Response(200, json=_fresh_payload())
    return httpx.MockTransport(handler)


_real_fetch_all = live_bots_feed.fetch_all


async def _fake_fetch_all(*args, **kwargs):
    transport = _mock_transport_all_ok()
    return await _real_fetch_all(transport=transport, base="https://bot.da3m.io")


class AdminLiveBotsEndpointTests(unittest.TestCase):
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
        self.db_path = Path(self.tmp.name) / "admin_live_bots.db"
        self.eng = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", echo=False)
        self.session_maker = async_sessionmaker(self.eng, expire_on_commit=False)
        async def _create_all():
            async with self.eng.begin() as conn:
                await conn.run_sync(dbmod.Base.metadata.create_all)
        asyncio.run(_create_all())
        import app.main as mainmod
        self.db_patches = [
            mock.patch.object(mainmod, "async_session", self.session_maker),
        ]
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
        self.fetch_patch = mock.patch.object(live_bots_feed, "fetch_all", _fake_fetch_all)
        self.fetch_patch.start()

    def tearDown(self):
        self.fetch_patch.stop()
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

    def test_overview_requires_admin(self):
        r = self.client.get("/api/admin/overview")
        self.assertEqual(r.status_code, 401)
        r2 = self.client.get("/api/admin/overview", headers=self._user_headers())
        self.assertEqual(r2.status_code, 403)

    def test_overview_includes_real_live_bots_summary_without_breaking_existing_fields(self):
        r = self.client.get("/api/admin/overview", headers=self._admin_headers())
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertIn("paper", j)  # existing dashboard field untouched
        self.assertIn("live_bots", j)
        self.assertFalse(j["live_bots"]["lifecycle_control_available"])
        self.assertEqual(j["live_bots"]["summary"]["strategies_total"], 8)
        self.assertEqual(j["live_bots"]["summary"]["running"], 7)
        self.assertEqual(j["live_bots"]["summary"]["no_service"], 1)

    def test_strategies_requires_admin(self):
        r = self.client.get("/api/admin/strategies")
        self.assertEqual(r.status_code, 401)

    def test_strategies_endpoint_reports_real_per_strategy_status(self):
        r = self.client.get("/api/admin/strategies", headers=self._admin_headers())
        self.assertEqual(r.status_code, 200)
        j = r.json()
        by_id = {x["id"]: x for x in j}
        self.assertEqual(by_id["trend_daily"]["live"]["status"], "running")
        self.assertEqual(by_id["default"]["live"]["status"], "no_service")
        self.assertNotIn("wave_flats", by_id)   # dropped 2026-10-29
        self.assertFalse(by_id["trend_daily"]["live"]["lifecycle_control_available"])

    def test_paper_portfolio_requires_admin(self):
        r = self.client.get("/api/admin/paper/portfolio")
        self.assertEqual(r.status_code, 401)

    def test_paper_portfolio_merges_dashboard_bot_and_live_bots_distinctly(self):
        r = self.client.get("/api/admin/paper/portfolio", headers=self._admin_headers())
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertIn("dashboard_bot", j)
        self.assertIn("live_bots", j)
        self.assertIn("label", j["dashboard_bot"])
        self.assertIn("label", j["live_bots"])
        self.assertFalse(j["live_bots"]["lifecycle_control_available"])
        self.assertEqual(j["live_bots"]["strategies"]["trend_daily"]["status"], "running")
        self.assertEqual(len(j["live_bots"]["strategies"]["trend_daily"]["positions"]), 1)
        self.assertEqual(j["live_bots"]["strategies"]["default"]["status"], "no_service")
        # back-compat: legacy top-level keys still present and unchanged in meaning
        self.assertIn("positions", j)
        self.assertIn("history", j)


if __name__ == "__main__":
    unittest.main()
