"""
Plan prices set by the admin, and invitations (gift / trial / paid) — app/plans_invites.py and its endpoints.
Supabase and Resend are faked; no network.
"""
import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient
from app import auth
from app import plans_invites as pi

ADMIN = {"id": "u-admin", "email": "admin@example.com", "email_confirmed": True}
SARA = {"id": "u-sara", "email": "sara@example.com", "email_confirmed": True}
OMAR = {"id": "u-omar", "email": "omar@example.com", "email_confirmed": True}
UNCONFIRMED = {"id": "u-new", "email": "new@example.com", "email_confirmed": False}
TOKENS = {"admin": ADMIN, "sara": SARA, "omar": OMAR, "new": UNCONFIRMED}


async def fake_verify(token):
    if token not in TOKENS:
        raise auth.HTTPException(401, "invalid")
    return TOKENS[token]


def H(who):
    return {"Authorization": f"Bearer {who}"}


class HelperTests(unittest.TestCase):
    def test_prices_default_and_override(self):
        self.assertEqual(pi.effective_prices({}), {"free": 0, "starter": 29, "pro": 59, "elite": 99})
        self.assertEqual(pi.effective_prices({"pro": 49, "free": 5, "bogus": 1})["pro"], 49)
        self.assertEqual(pi.effective_prices({"free": 5})["free"], 0)

    def test_validate_prices(self):
        self.assertEqual(pi.validate_prices({"pro": 49, "elite": 120.0}), {"pro": 49, "elite": 120})
        for bad in ({}, {"free": 0}, {"pro": 0}, {"pro": 10.5}, {"pro": True}, {"pro": "49"}, {"pro": 20_000}):
            with self.assertRaises(ValueError):
                pi.validate_prices(bad)

    def test_grant_tier_and_states(self):
        now = datetime(2026, 11, 1, tzinfo=timezone.utc)
        live = {"tier": "pro", "expires_at": (now + timedelta(days=1)).isoformat()}
        over = {"tier": "pro", "expires_at": (now - timedelta(seconds=1)).isoformat()}
        self.assertEqual(pi.active_grant_tier(live, now), "pro")
        self.assertIsNone(pi.active_grant_tier(over, now))
        self.assertIsNone(pi.active_grant_tier(None, now))
        self.assertEqual(pi.invite_state({"status": "pending", "link_expires_at": over["expires_at"]}, now), "expired")
        self.assertEqual(pi.invite_state({"status": "revoked", "link_expires_at": live["expires_at"]}, now), "revoked")

    def test_second_gift_adds_days_and_keeps_higher_plan(self):
        now = datetime(2026, 11, 1, tzinfo=timezone.utc)
        cur = {"tier": "elite", "expires_at": (now + timedelta(days=10)).isoformat()}
        tier, end = pi.grant_end(cur, "pro", 30, now)
        self.assertEqual(tier, "elite")
        self.assertEqual(end, now + timedelta(days=40))
        tier, end = pi.grant_end({"tier": "elite", "expires_at": (now - timedelta(days=1)).isoformat()}, "pro", 30, now)
        self.assertEqual((tier, end), ("pro", now + timedelta(days=30)))

    def test_email_helpers(self):
        self.assertTrue(pi.valid_email(" Sara@Example.com "))
        for bad in ("", "sara", "sara@", "@x.com", "a@b", "a b@c.com", "a@@b.com"):
            self.assertFalse(pi.valid_email(bad), bad)
        self.assertEqual(pi.mask_email("Sara@Example.com"), "s***@example.com")
        subject, body = pi.invite_email("pro", "trial", 14, 59, "https://x/invite/abc<")
        self.assertIn("Pro", subject)
        self.assertIn("&lt;", body)
        self.assertNotIn("abc<", body)


class SendEmailTests(unittest.TestCase):
    def test_resend_refusal_keeps_its_reason_not_the_key(self):
        import httpx

        def handler(request):
            self.assertEqual(request.headers["Authorization"], "Bearer re_secret")
            return httpx.Response(403, json={"statusCode": 403, "name": "validation_error", "message": "The da3m.io domain is not verified."})
        with mock.patch.dict(os.environ, {"RESEND_API_KEY": "re_secret", "INVITE_FROM_EMAIL": "RAQM <raqm@da3m.io>"}):
            out = asyncio.run(pi.send_email("a@b.com", "s", "<p>x</p>", transport=httpx.MockTransport(handler)))
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "resend http 403: The da3m.io domain is not verified.")
        self.assertNotIn("re_secret", out["error"])

    def test_resend_ok(self):
        import httpx
        with mock.patch.dict(os.environ, {"RESEND_API_KEY": "k", "INVITE_FROM_EMAIL": "RAQM <raqm@da3m.io>"}):
            out = asyncio.run(pi.send_email("a@b.com", "s", "<p>x</p>", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"id": "1"}))))
        self.assertEqual(out, {"ok": True, "error": None})


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [
            mock.patch.object(auth, "_verify_token", fake_verify),
            mock.patch.dict(os.environ, {"ADMIN_EMAILS": ADMIN["email"], "ALLOW_LIVE_TRADING": "", "RESEND_API_KEY": "",
                                         "INVITE_FROM_EMAIL": "", "SUPABASE_URL": "", "SUPABASE_SERVICE_KEY": ""}),
        ]
        for p in self.patches: p.start()
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        import app.db as dbmod
        self.eng = create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmp.name) / 'plans.db'}", echo=False)
        self.session_maker = async_sessionmaker(self.eng, expire_on_commit=False)

        async def _create_all():
            async with self.eng.begin() as conn:
                await conn.run_sync(dbmod.Base.metadata.create_all)
        asyncio.run(_create_all())
        import app.main as mainmod
        self.mainmod = mainmod
        self.db_patch = mock.patch.object(mainmod, "async_session", self.session_maker)
        self.db_patch.start()
        mainmod._rate_hits.clear()
        mainmod._tier_cache.clear()
        self._orig_botdir = mainmod.BOT_DIR
        mainmod.BOT_DIR = Path(self.tmp.name) / "botdir"
        mainmod.BOT_DIR.mkdir()
        import app.auth as authmod
        authmod._verify_token = fake_verify
        self.paid = {"u-sara": "free", "u-omar": "free"}
        self.paid_patch = mock.patch.object(mainmod, "_paid_tier", mock.AsyncMock(side_effect=lambda u: self.paid.get(u["id"], "free")))
        self.paid_patch.start()
        self.gotrue_patch = mock.patch.object(mainmod.admin_users, "fetch_gotrue_users", mock.AsyncMock(return_value={
            "available": True, "error": None, "users": [{"id": "u-sara", "email": "sara@example.com"}, {"id": "u-omar", "email": "omar@example.com"}]}))
        self.tiers_patch = mock.patch.object(mainmod.admin_users, "fetch_profile_tiers", mock.AsyncMock(return_value={
            "available": True, "error": None, "tiers": {}}))
        self.gotrue_patch.start(); self.tiers_patch.start()
        self.client = TestClient(mainmod.app)

    def tearDown(self):
        for p in (self.tiers_patch, self.gotrue_patch, self.paid_patch, self.db_patch, *self.patches): p.stop()
        self.mainmod.BOT_DIR = self._orig_botdir
        try: asyncio.run(self.eng.dispose())
        except Exception: pass
        self.tmp.cleanup()

    def invite(self, **kw):
        body = {"email": "sara@example.com", "tier": "pro", "kind": "gift", "days": 30, "send_email": False, "confirm": True, **kw}
        return self.client.post("/api/admin/invites", json=body, headers=H("admin"))

    # prices
    def test_prices_public_admin_and_finance(self):
        self.assertEqual(self.client.get("/api/plans").json()["prices"]["pro"], 59)
        self.assertEqual(self.client.post("/api/admin/plans", json={"prices": {"pro": 49}, "confirm": True}, headers=H("sara")).status_code, 403)
        self.assertEqual(self.client.post("/api/admin/plans", json={"prices": {"pro": 49}}, headers=H("admin")).status_code, 400)
        self.assertEqual(self.client.post("/api/admin/plans", json={"prices": {"free": 9}, "confirm": True}, headers=H("admin")).status_code, 400)
        r = self.client.post("/api/admin/plans", json={"prices": {"pro": 49}, "confirm": True}, headers=H("admin"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get("/api/plans").json()["prices"], {"free": 0, "starter": 29, "pro": 49, "elite": 99})
        admin = self.client.get("/api/admin/plans", headers=H("admin")).json()
        self.assertEqual(admin["defaults"]["pro"], 59)
        self.assertEqual(admin["changed"]["pro"]["updated_by"], "admin@example.com")
        self.tiers_patch.stop()
        self.tiers_patch = mock.patch.object(self.mainmod.admin_users, "fetch_profile_tiers", mock.AsyncMock(return_value={
            "available": True, "error": None, "tiers": {"u-sara": "pro"}}))
        self.tiers_patch.start()
        fin = self.client.get("/api/admin/finance", headers=H("admin")).json()["finance"]
        self.assertEqual(fin["mrr_usd"], 49)

    # gift
    def test_gift_flow(self):
        r = self.invite()
        self.assertEqual(r.status_code, 200, r.text)
        inv = r.json()["invite"]
        self.assertEqual(inv["state"], "pending")
        self.assertTrue(inv["link"].endswith("/invite/" + inv["id"]))
        self.assertEqual(self.invite().status_code, 409)              # one pending invitation per email
        pub = self.client.get(f"/api/invites/{inv['id']}").json()
        self.assertEqual(pub["email_hint"], "s***@example.com")
        self.assertNotIn("email", pub)
        self.assertEqual(self.client.post(f"/api/invites/{inv['id']}/accept", headers=H("omar")).status_code, 403)
        self.assertEqual(self.client.post(f"/api/invites/{inv['id']}/checkout", headers=H("sara")).status_code, 400)
        self.assertEqual(self.client.get("/api/user/tier", headers=H("sara")).json()["tier"], "free")
        r = self.client.post(f"/api/invites/{inv['id']}/accept", headers=H("sara"))
        self.assertEqual(r.status_code, 200, r.text)
        me = self.client.get("/api/user/tier", headers=H("sara")).json()
        self.assertEqual(me["tier"], "pro")
        self.assertEqual(me["gift"]["tier"], "pro")
        self.assertEqual(self.client.post(f"/api/invites/{inv['id']}/accept", headers=H("sara")).status_code, 409)
        listed = self.client.get("/api/admin/invites", headers=H("admin")).json()
        self.assertEqual(listed["invites"][0]["state"], "accepted")
        self.assertTrue(listed["grants"][0]["active"])
        users = self.client.get("/api/admin/users", headers=H("admin")).json()["users"]
        self.assertEqual({u["id"]: u["gift_tier"] for u in users}, {"u-sara": "pro", "u-omar": None})
        # the admin ends it: back to the paid plan
        self.assertEqual(self.client.post("/api/admin/grants/u-sara/end", json={"confirm": True}, headers=H("admin")).status_code, 200)
        self.assertEqual(self.client.get("/api/user/tier", headers=H("sara")).json(), {"tier": "free", "gift": None})

    def test_gift_never_lowers_a_paid_plan(self):
        self.paid["u-sara"] = "elite"
        inv = self.invite(tier="starter").json()["invite"]
        self.client.post(f"/api/invites/{inv['id']}/accept", headers=H("sara"))
        self.assertEqual(self.client.get("/api/user/tier", headers=H("sara")).json()["tier"], "elite")

    def test_expired_gift_counts_for_nothing(self):
        inv = self.invite(days=1).json()["invite"]
        self.client.post(f"/api/invites/{inv['id']}/accept", headers=H("sara"))
        later = pi.now() + timedelta(days=2)
        with mock.patch.object(pi, "now", return_value=later):
            self.mainmod._tier_cache.clear()
            self.assertEqual(self.client.get("/api/user/tier", headers=H("sara")).json()["tier"], "free")

    def test_unconfirmed_email_and_revoked_or_expired_link(self):
        inv = self.invite(email="new@example.com").json()["invite"]
        self.assertEqual(self.client.post(f"/api/invites/{inv['id']}/accept", headers=H("new")).status_code, 403)
        self.assertEqual(self.client.post(f"/api/admin/invites/{inv['id']}/revoke", json={"confirm": True}, headers=H("admin")).status_code, 200)
        self.assertEqual(self.client.get(f"/api/invites/{inv['id']}").json()["state"], "revoked")
        inv2 = self.invite(email="omar@example.com").json()["invite"]
        with mock.patch.object(pi, "now", return_value=pi.now() + timedelta(days=pi.LINK_DAYS + 1)):
            self.assertEqual(self.client.get(f"/api/invites/{inv2['id']}").json()["state"], "expired")
            self.assertEqual(self.client.post(f"/api/invites/{inv2['id']}/accept", headers=H("omar")).status_code, 409)
        self.assertEqual(self.client.get("/api/invites/not-a-real-invite-id-xx").status_code, 404)
        self.assertEqual(self.client.get("/api/invites/x").status_code, 404)

    # trial / paid
    def test_trial_checkout_terms(self):
        self.client.post("/api/admin/plans", json={"prices": {"elite": 120}, "confirm": True}, headers=H("admin"))
        inv = self.invite(tier="elite", kind="trial", days=14).json()["invite"]
        self.assertIn("120", inv["offer"])
        self.assertEqual(self.client.post(f"/api/invites/{inv['id']}/accept", headers=H("sara")).status_code, 400)
        r = self.client.post(f"/api/invites/{inv['id']}/checkout", headers=H("sara"))
        self.assertEqual(r.json(), {"tier": "elite", "kind": "trial", "trial_days": 14, "price_usd": 120})
        self.paid["u-sara"] = "elite"                                       # Stripe made the subscription
        self.assertEqual(self.client.get("/api/admin/invites", headers=H("admin")).json()["invites"][0]["state"], "pending")
        self.tiers_patch.stop()
        self.tiers_patch = mock.patch.object(self.mainmod.admin_users, "fetch_profile_tiers", mock.AsyncMock(return_value={
            "available": True, "error": None, "tiers": {"u-sara": "elite"}}))
        self.tiers_patch.start()
        self.assertEqual(self.client.get("/api/admin/invites", headers=H("admin")).json()["invites"][0]["state"], "subscribed")
        self.assertEqual(self.client.post(f"/api/invites/{inv['id']}/checkout", headers=H("sara")).status_code, 409)

    def test_paid_needs_no_days_and_gift_needs_days(self):
        self.assertEqual(self.invite(kind="paid", days=None).status_code, 200)
        self.assertEqual(self.invite(email="omar@example.com", kind="gift", days=None).status_code, 400)
        self.assertEqual(self.invite(email="omar@example.com", tier="free").status_code, 400)
        self.assertEqual(self.invite(email="not-an-email").status_code, 400)
        self.assertEqual(self.invite(email="omar@example.com", confirm=False).status_code, 400)

    # email
    def test_email_sent_through_resend_when_configured(self):
        sent = []

        async def fake_send(to, subject, body, **kw):
            sent.append((to, subject))
            return {"ok": True, "error": None}
        with mock.patch.object(pi, "send_email", fake_send):
            r = self.invite(send_email=True)
        self.assertTrue(r.json()["emailed"])
        self.assertEqual(sent[0][0], "sara@example.com")
        self.assertIsNotNone(r.json()["invite"]["emailed_at"])

    def test_email_not_configured_still_creates_the_link(self):
        r = self.invite(send_email=True)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["emailed"])
        self.assertIn("not configured", r.json()["email_error"])


if __name__ == "__main__":
    unittest.main()
