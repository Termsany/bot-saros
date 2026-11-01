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

    def test_strategy_policy_recommends_three_but_charges_slots_by_strategy(self):
        self.assertEqual(self.ub.strategy_policy(["trend_daily", "vol_breakout", "rsi2_pullback"]),
                         {"accepted": True, "recommended": 3, "slots": 3, "reason": "ok"})
        self.assertEqual(self.ub.strategy_policy(["trend_daily", "vol_breakout"])["recommended"], 3)
        self.assertEqual(self.ub.strategy_policy(["momentum_ls"])["slots"], 10)
        self.assertFalse(self.ub.strategy_policy(["momentum_ls"], available_slots=9)["accepted"])

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

    # P2.7 review
    def test_a_status_file_that_is_a_link_is_not_read(self):
        other = self.ipc / "owner_status.json"
        other.write_text(json.dumps({"updated": datetime.now(timezone.utc).isoformat(), "positions": [{"symbol": "BTC/USDT"}]}), encoding="utf-8")
        (self.ipc / U1 / "trend_daily").mkdir(parents=True)
        try:
            (self.ipc / U1 / "trend_daily" / "live_status.json").symlink_to(other)
        except OSError:
            self.skipTest("symlinks not available here")
        self.assertEqual(self.c.get("/api/user/bots", headers=self.h("u1-token")).json()["bots"], {})

    def test_custom_ipc_root_is_used_and_non_dict_status_is_ignored(self):
        custom = Path(self.tmp.name) / "custom-ipc"
        (custom / U1 / "trend_daily").mkdir(parents=True)
        (custom / U1 / "trend_daily" / "live_status.json").write_text(json.dumps([]), encoding="utf-8")
        self.assertEqual(self.ub.status(U1, ipc=custom)["bots"], {})
        (custom / f"{U1}--trend_daily").mkdir(parents=True)
        (custom / f"{U1}--trend_daily" / "live_status.json").write_text(json.dumps({
            "updated": datetime.now(timezone.utc).isoformat(), "positions": []}), encoding="utf-8")
        result = self.ub.status(U1, ipc=custom)
        self.assertTrue(result["bots"]["trend_daily"]["running"])

    def test_a_demo_consent_leaves_the_keys_marked_as_they_were(self):
        from app.user_keys_vault import save_user_keys, user_key_status
        from app.user_live_activation import CONSENT_TEXT
        save_user_keys(U1, "binance", "k", "s")
        before = user_key_status(U1)["binance"]["paper"]
        self.c.post("/api/user/live/enable", headers=self.h("u1-token"), json={"exchange": "binance", "confirm": CONSENT_TEXT, "environment": "demo"})
        self.assertEqual(user_key_status(U1)["binance"]["paper"], before)

    @unittest.skipUnless(os.name == "posix", "file modes")
    def test_a_users_close_request_is_readable_by_their_bot(self):
        d = self.ipc / U1 / "trend_daily"; (d / "commands").mkdir(parents=True)
        (d / "live_status.json").write_text(json.dumps({"updated": datetime.now(timezone.utc).isoformat(), "positions": [{"symbol": "SOL/USDT"}]}), encoding="utf-8")
        rid = self.c.post("/api/user/bots/close", headers=self.h("u1-token"), json={"strategy": "trend_daily", "symbol": "SOL/USDT"}).json()["id"]
        self.assertTrue(os.stat(d / "commands" / f"close-{rid}.json").st_mode & 0o004)



if __name__ == "__main__":
    unittest.main()
