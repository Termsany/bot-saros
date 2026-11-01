"""P2.3 (docs/phase2-design.md): a user's own bots from the site — what they ask for, their bots' status, closing."""
import json, os, sys, tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "backend")); sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_security as ts
from test_security import ApiAuthTests

U1, U2 = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
ASK = {"env": "demo", "enabled": True, "strategies": ["trend_daily"], "leverage": 2, "risk_per_trade_pct": 1.0,
       "max_aggregate_risk_pct": 3.0, "capital_usdt": 1000, "capital_margin_override_usdt": 20}


class UserBotsApiTests(ApiAuthTests):
    def setUp(self):
        super().setUp()
        import app.main as m
        from app import user_bots as ub
        self.m, self.ub = m, ub
        d = Path(self.tmp.name)
        self.desired, self.ipc = d / "desired", d / "ipc"; self.desired.mkdir(); self.ipc.mkdir()
        self.tokens = mock.patch.dict(ts.TOKENS, {
            "u1-token": {"id": U1, "email": "u1@example.com", "email_confirmed": True},
            "u2-token": {"id": U2, "email": "u2@example.com", "email_confirmed": True},
            "new-token": {"id": U2, "email": "u2@example.com", "email_confirmed": False}})
        from app import user_keys_vault as ukv
        self.paths = [mock.patch.object(ub, "DESIRED", self.desired), mock.patch.object(ub, "IPC_ROOT", self.ipc),
                      mock.patch.object(ukv, "VAULT_PATH", d / "user_vault.json"),      # never the repo's own file
                      mock.patch.object(m, "USER_LIVE_ACTIVATION_PATH", d / "consent.sqlite3"), self.tokens]
        for p in self.paths: p.start()
    def tearDown(self):
        for p in self.paths: p.stop()
        super().tearDown()

    def ask(self, tok="u1-token", **kw):
        return self.c.post("/api/user/bots", headers=self.h(tok), json={**ASK, **kw})

    def test_a_user_saves_what_they_want_for_themselves_only(self):
        self.assertEqual(self.ask().status_code, 200)
        saved = json.loads((self.desired / f"{U1}.json").read_text(encoding="utf-8"))
        self.assertEqual((saved["user_id"], saved["strategies"], saved["env"]), (U1, ["trend_daily"], "demo"))
        self.assertEqual(self.c.post("/api/user/bots", headers=self.h("u1-token"), json={**ASK, "user_id": U2}).status_code, 200)
        self.assertFalse((self.desired / f"{U2}.json").exists())                  # a user id in the body is ignored
        self.assertIsNone(self.c.get("/api/user/bots", headers=self.h("u2-token")).json()["desired"])

    def test_what_the_rules_refuse_is_refused_here_too(self):
        for kw in ({"env": "live"}, {"strategies": ["ict"]}, {"strategies": ["trend_daily", "vol_breakout", "rsi2_pullback"]},
                   {"leverage": 9}, {"risk_per_trade_pct": 2.0}, {"capital_margin_override_usdt": 5000}):
            self.assertEqual(self.ask(**kw).status_code, 400, kw)
        self.assertEqual(self.ask(tok="new-token").status_code, 403)               # email not confirmed
        self.assertEqual(self.c.post("/api/user/bots", json=ASK).status_code, 401)

    def test_the_page_shows_the_provisioners_answer_and_the_bots(self):
        self.ask()
        (self.ipc / U1 / "trend_daily").mkdir(parents=True)
        (self.ipc / U1 / "provision.json").write_text(json.dumps({"state": "waiting_approval"}), encoding="utf-8")
        (self.ipc / U1 / "trend_daily" / "live_status.json").write_text(json.dumps(
            {"updated": datetime.now(timezone.utc).isoformat(), "env": "demo", "positions": [{"symbol": "SOL/USDT"}]}), encoding="utf-8")
        r = self.c.get("/api/user/bots", headers=self.h("u1-token")).json()
        self.assertEqual(r["provision"]["state"], "waiting_approval")
        self.assertTrue(r["bots"]["trend_daily"]["running"]); self.assertEqual(r["rules"]["envs"], ["demo"])
        self.assertEqual(self.c.get("/api/user/bots", headers=self.h("u2-token")).json()["bots"], {})

    def test_close_only_an_open_position_of_a_running_bot_of_ones_own(self):
        self.assertEqual(self.c.post("/api/user/bots/close", headers=self.h("u1-token"), json={"strategy": "trend_daily", "symbol": "SOL/USDT"}).status_code, 409)
        d = self.ipc / U1 / "trend_daily"; (d / "commands").mkdir(parents=True)
        (d / "live_status.json").write_text(json.dumps({"updated": datetime.now(timezone.utc).isoformat(), "positions": [{"symbol": "SOL/USDT"}]}), encoding="utf-8")
        self.assertEqual(self.c.post("/api/user/bots/close", headers=self.h("u1-token"), json={"strategy": "trend_daily", "symbol": "ETH/USDT"}).status_code, 404)
        r = self.c.post("/api/user/bots/close", headers=self.h("u1-token"), json={"strategy": "trend_daily", "symbol": "SOL/USDT"})
        self.assertEqual(r.status_code, 200)
        cmd = json.loads((d / "commands" / f"close-{r.json()['id']}.json").read_text(encoding="utf-8"))
        self.assertEqual((cmd["symbol"], cmd["by"]), ("SOL/USDT", "u1@example.com"))
        self.assertEqual(self.c.post("/api/user/bots/close", headers=self.h("u2-token"), json={"strategy": "trend_daily", "symbol": "SOL/USDT"}).status_code, 409)
        self.assertEqual(self.c.get(f"/api/user/bots/close/trend_daily/{r.json()['id']}", headers=self.h("u1-token")).json(), {"done": False, "pending": True})

    def test_demo_consent_while_the_real_money_switch_is_off_real_money_still_refused(self):
        from app.user_keys_vault import save_user_keys
        from app.user_live_activation import CONSENT_TEXT, get_user_live_record
        save_user_keys(U1, "binance", "k", "s")
        body = {"exchange": "binance", "confirm": CONSENT_TEXT}
        self.assertEqual(self.c.post("/api/user/live/enable", headers=self.h("u1-token"), json={**body, "environment": "live"}).status_code, 403)
        self.assertEqual(self.c.post("/api/user/live/enable", headers=self.h("u1-token"), json=body).status_code, 403)   # default: real money
        self.assertEqual(self.c.post("/api/user/live/enable", headers=self.h("u1-token"), json={**body, "environment": "demo"}).status_code, 200)
        self.assertEqual(get_user_live_record(self.m.USER_LIVE_ACTIVATION_PATH, user_id=U1)["environment"], "demo")
        self.assertEqual(self.c.get("/api/user/live/status", headers=self.h("u1-token")).json()["environment"], "demo")

    def test_the_admin_sees_every_user_who_asked(self):
        self.ask(); (self.ipc / U1).mkdir()
        (self.ipc / U1 / "provision.json").write_text(json.dumps({"state": "running"}), encoding="utf-8")
        self.assertEqual(self.c.get("/api/admin/user-bots", headers=self.h("u1-token")).status_code, 403)
        r = self.c.get("/api/admin/user-bots", headers=self.h("admin-token")).json()
        self.assertEqual([(u["user_id"], u["provision"]["state"]) for u in r["users"]], [(U1, "running")])


if __name__ == "__main__":
    unittest.main()
