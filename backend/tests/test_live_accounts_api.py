"""The dashboard per real account (backend/app/main.py, docs/trend-daily-live-plan.md §2): a live strategy on its own
Binance sub-account has its own capital, limits, yes/no and kill switch. Every endpoint takes `acct` ("" = the main
account) and touches that account's ledger and activation only; an unknown account is refused, and a strategy can only
be switched on on the account it trades on."""
import json, os, sys, unittest
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "backend")); sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend.app import risk_manager as rm
from backend.app import live_accounts as la
from test_security import ApiAuthTests
from test_admin_live_strategies import trusted_evidence


class LiveAccountsApiTests(ApiAuthTests):
    def setUp(self):
        super().setUp()
        import app.main as m; self.m = m
        t = Path(self.tmp.name)
        (t / "live").mkdir(); (t / "demo").mkdir(); (t / "accounts" / "trend").mkdir(parents=True)
        (t / "accounts.json").write_text(la.dump({"trend": ["trend_daily"]}), encoding="utf-8")
        self.patches = [mock.patch.dict(os.environ, {"RAQM_RISK_DIR": str(t / "live"), "RAQM_RISK_DIR_DEMO": str(t / "demo"),
                                                     "ALLOW_LIVE_TRADING": "true", "READINESS_EXPECTED_COMMIT_SHA": "a" * 40}),
                        mock.patch.object(m, "BOT_DIR", t), mock.patch.object(m, "LIVE_ACTIVATION_PATH", t / "live" / "act.sqlite3"),
                        mock.patch.object(m, "ACCOUNTS_REGISTRY", t / "accounts.json"), mock.patch.object(m, "ACCOUNTS_RISK_ROOT", t / "accounts")]
        for p in self.patches: p.start()
        (t / "readiness_evidence.json").write_text(json.dumps(trusted_evidence(m.LIVE_STRATEGIES)), encoding="utf-8")
        m._rate_hits.clear()
        self.main, self.trend = t / "live" / "risk_state.json", t / "accounts" / "trend" / "risk_state.json"
        self.trend_act = t / "accounts" / "trend" / "live_activation.sqlite3"

    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        super().tearDown()

    def get(self, **q):
        return self.c.get("/api/live/strategies", headers=self.h("admin-token"), params=q)

    def post(self, path, body):
        return self.c.post(path, headers=self.h("admin-token"), json=body)

    def test_each_account_lists_its_own_strategies_and_the_accounts(self):
        main = self.get(env="live").json()
        self.assertNotIn("trend_daily", [r["id"] for r in main["strategies"]])
        self.assertIn("momentum_ls", [r["id"] for r in main["strategies"]])
        self.assertEqual([a["name"] for a in main["accounts"]], ["", "trend"])
        trend = self.get(env="live", acct="trend").json()
        self.assertEqual([r["id"] for r in trend["strategies"]], ["trend_daily"])
        self.assertEqual(trend["acct"], "trend")
        self.assertFalse(trend["kill_switch"]["tripped"])
        demo = self.get(env="demo").json()                      # Demo: one account for every bot, no picker
        self.assertEqual(demo["accounts"], []); self.assertIn("trend_daily", [r["id"] for r in demo["strategies"]])

    def test_capital_and_limits_go_to_that_accounts_ledger_only(self):
        r = self.post("/api/live/capital", {"env": "live", "acct": "trend", "capital_usdt": 500, "capital_margin_override_usdt": 26})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(rm.load_risk_state(self.trend)["limits"]["capital_usdt"], 500)
        self.assertIsNone(rm.load_risk_state(self.main)["limits"].get("capital_usdt"))
        r = self.post("/api/live/limits", {"env": "live", "acct": "trend", "risk_per_trade_pct": 2.5, "max_aggregate_risk_pct": 45})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(rm.load_risk_state(self.trend)["limits"]["risk_per_trade_pct"], 2.5)
        self.assertEqual(rm.load_risk_state(self.main)["limits"]["risk_per_trade_pct"], rm.DEFAULT_LIMITS["risk_per_trade_pct"])
        self.assertEqual(self.get(env="live", acct="trend").json()["capital"]["capital_usdt"], 500)

    def test_the_same_plan_as_another_account_asks_first(self):
        rm.update_limits(self.main, {"capital_usdt": 500, "capital_margin_override_usdt": 26})
        r = self.post("/api/live/capital", {"env": "live", "acct": "trend", "capital_usdt": 500, "capital_margin_override_usdt": 26})
        self.assertEqual(r.status_code, 409); self.assertIn("الحساب الحقيقي", r.json()["detail"])
        r = self.post("/api/live/capital", {"env": "live", "acct": "trend", "capital_usdt": 500, "capital_margin_override_usdt": 26, "confirm": True})
        self.assertEqual(r.status_code, 200)

    def test_the_kill_switch_of_one_account_leaves_the_other_alone(self):
        r = self.post("/api/admin/risk/kill-switch", {"action": "trip", "acct": "trend", "reason": "test trip", "confirm": True})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(rm.load_risk_state(self.trend)["kill_switch"]["tripped"])
        self.assertFalse(rm.load_risk_state(self.main)["kill_switch"]["tripped"])
        self.assertTrue(self.get(env="live", acct="trend").json()["kill_switch"]["tripped"])
        self.post("/api/admin/risk/kill-switch", {"action": "reset", "acct": "trend", "confirm": True})
        self.assertFalse(rm.load_risk_state(self.trend)["kill_switch"]["tripped"])
        st = self.c.get("/api/admin/risk", headers=self.h("admin-token"), params={"acct": "trend"}).json()
        self.assertEqual(st["acct"], "trend")

    def test_a_strategy_is_switched_on_only_on_its_own_account_under_its_name(self):
        r = self.post("/api/live/strategies", {"env": "live", "acct": "trend", "account": "trend", "strategies": ["trend_daily"]})
        self.assertEqual(r.status_code, 200, r.text)
        from app import live_activation
        self.assertEqual(live_activation.active_record(self.trend_act)["strategies"], ["trend_daily"])
        self.assertIsNone(live_activation.active_record(self.m.LIVE_ACTIVATION_PATH))          # the main account untouched
        self.assertTrue(self.get(env="live", acct="trend").json()["strategies"][0]["on"])
        for body in ({"env": "live", "acct": "trend", "account": "main", "strategies": ["trend_daily"]},   # the bot reads "trend"
                     {"env": "live", "acct": "trend", "account": "trend", "strategies": ["momentum_ls"]},  # not on this account
                     {"env": "live", "acct": "", "account": "main", "strategies": ["trend_daily"]}):        # it trades elsewhere
            self.assertEqual(self.post("/api/live/strategies", body).status_code, 422, body)

    def test_unknown_or_bad_accounts_are_refused(self):
        self.assertEqual(self.get(env="live", acct="other").status_code, 404)
        self.assertEqual(self.get(env="live", acct="Bad!").status_code, 400)
        self.assertEqual(self.post("/api/live/capital", {"env": "live", "acct": "other", "capital_usdt": 1}).status_code, 404)
        self.assertEqual(self.post("/api/live/limits", {"env": "live", "acct": "../x", "risk_per_trade_pct": 1}).status_code, 422)
        self.assertEqual(self.post("/api/admin/risk/kill-switch", {"action": "trip", "acct": "main", "confirm": True}).status_code, 404)
        self.assertFalse((Path(self.tmp.name) / "accounts" / "other").exists())       # nothing made for a name not registered

    def test_a_broken_registry_stops_the_account_endpoints(self):
        (Path(self.tmp.name) / "accounts.json").write_text("{", encoding="utf-8")
        self.assertEqual(self.get(env="live").status_code, 503)

    def test_admin_only(self):
        self.assertEqual(self.c.get("/api/live/strategies", headers=self.h("user-token"), params={"acct": "trend"}).status_code, 403)
        self.assertEqual(self.c.post("/api/admin/risk/kill-switch", headers=self.h("user-token"),
                                     json={"action": "reset", "acct": "trend", "confirm": True}).status_code, 403)


if __name__ == "__main__":
    unittest.main()
