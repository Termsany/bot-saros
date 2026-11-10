"""POST /api/live/limits (2026-11-03): the dashboard's risk tab only showed the limits — the real account's stayed at
the defaults (0.25% per trade, 1% aggregate) that refuse a momentum_ls basket, with no way to change them from the site.
Each account's own ledger, admin only, bounded, audited; /api/live/strategies returns all five; and the browser's
PATCH preflight is allowed (the admin page's PATCH buttons failed it)."""
import json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "backend")); sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend.app import risk_manager as rm
from test_security import ApiAuthTests

LIMITS = {"risk_per_trade_pct": 4.5, "max_aggregate_risk_pct": 45, "max_correlated_risk_pct": 25,
          "max_daily_loss_pct": 20, "max_drawdown_pct": 45}


class LiveLimitsApiTests(ApiAuthTests):
    def setUp(self):
        super().setUp()
        import app.main as m; self.m = m
        t = Path(self.tmp.name)
        (t / "live").mkdir(); (t / "demo").mkdir()
        self.env = mock.patch.dict(os.environ, {"RAQM_RISK_DIR": str(t / "live"), "RAQM_RISK_DIR_DEMO": str(t / "demo")}); self.env.start()
        self.p_dir = mock.patch.object(m, "BOT_DIR", t); self.p_dir.start()          # the audit log
        # /api/live/strategies reads the activation record: never the repo's own folder
        self.p_act = mock.patch.object(m, "LIVE_ACTIVATION_PATH", t / "act.sqlite3"); self.p_act.start()
        m._rate_hits.clear()
        self.live, self.demo = t / "live" / "risk_state.json", t / "demo" / "risk_state.json"

    def tearDown(self):
        self.p_act.stop(); self.p_dir.stop(); self.env.stop(); super().tearDown()

    def post(self, body, tok="admin-token"):
        return self.c.post("/api/live/limits", headers=self.h(tok), json=body)

    def test_sets_the_real_accounts_limits_and_leaves_demo_alone(self):
        r = self.post({"env": "live", **LIMITS})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["limits"], {k: float(v) for k, v in LIMITS.items()})
        self.assertEqual(rm.load_risk_state(self.live)["limits"]["risk_per_trade_pct"], 4.5)
        self.assertEqual(rm.load_risk_state(self.demo)["limits"]["risk_per_trade_pct"], rm.DEFAULT_LIMITS["risk_per_trade_pct"])

    def test_env_defaults_to_live_and_demo_goes_to_the_demo_ledger(self):
        self.assertEqual(self.post({"risk_per_trade_pct": 0.5}).status_code, 200)       # under the default 1% aggregate
        self.assertEqual(rm.load_risk_state(self.live)["limits"]["risk_per_trade_pct"], 0.5)
        self.assertEqual(self.post({"env": "demo", "max_aggregate_risk_pct": 40}).status_code, 200)
        self.assertEqual(rm.load_risk_state(self.demo)["limits"]["max_aggregate_risk_pct"], 40.0)

    def test_only_the_given_limits_change_and_the_capital_plan_stays(self):
        rm.update_limits(self.live, {"capital_usdt": 500, "capital_margin_override_usdt": 26})
        self.post({"max_drawdown_pct": 45})
        lim = rm.load_risk_state(self.live)["limits"]
        self.assertEqual((lim["capital_usdt"], lim["capital_margin_override_usdt"], lim["max_drawdown_pct"]), (500, 26, 45.0))
        self.assertEqual(lim["risk_per_trade_pct"], rm.DEFAULT_LIMITS["risk_per_trade_pct"])

    def test_bounds_and_unknown_fields_are_refused(self):
        for body in ({"risk_per_trade_pct": 0}, {"risk_per_trade_pct": -1}, {"max_drawdown_pct": 101},
                     {"env": "paper", "risk_per_trade_pct": 1}, {"leverage": 20}, {"capital_usdt": 1e9}):
            self.assertEqual(self.post(body).status_code, 422, body)
        self.assertEqual(self.post({}).status_code, 400)

    def test_per_trade_above_the_aggregate_is_refused(self):
        r = self.post({"risk_per_trade_pct": 5, "max_aggregate_risk_pct": 4})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(rm.load_risk_state(self.live)["limits"]["risk_per_trade_pct"], rm.DEFAULT_LIMITS["risk_per_trade_pct"])

    def test_admin_only(self):
        self.assertEqual(self.post(LIMITS, tok="user-token").status_code, 403)
        self.assertEqual(self.post(LIMITS, tok="squat-token").status_code, 403)
        self.assertEqual(self.c.post("/api/live/limits", json=LIMITS).status_code, 401)
        self.assertEqual(rm.load_risk_state(self.live)["limits"]["risk_per_trade_pct"], rm.DEFAULT_LIMITS["risk_per_trade_pct"])

    def test_every_change_is_in_the_audit_log(self):
        from app import admin_control
        self.assertEqual(self.post({"env": "live", "risk_per_trade_pct": 4.5, "max_aggregate_risk_pct": 45}).status_code, 200)
        rows =[r for r in admin_control.list_audit(Path(self.tmp.name)) if r["action"] == "risk_limits"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["actor"], "admin@example.com"); self.assertIn("4.5", json.dumps(rows[0]["details"]))

    def test_live_strategies_returns_all_five_limits(self):
        self.post({"env": "live", **LIMITS})
        cap = self.c.get("/api/live/strategies?env=live", headers=self.h("admin-token")).json()["capital"]
        self.assertEqual({k: cap[k] for k in LIMITS}, {k: float(v) for k, v in LIMITS.items()})

    def test_each_account_sees_only_its_own_bot(self):
        # one status folder per strategy for both bots: the real-money view showed the Demo bots as its own (2026-11-03)
        from datetime import datetime, timezone
        ipc = Path(self.tmp.name) / "ipc"
        now = datetime.now(timezone.utc).isoformat()
        for s, env in (("trend_daily", "demo"), ("momentum_ls", "live")):
            (ipc / s).mkdir(parents=True)
            (ipc / s / "live_status.json").write_text(json.dumps({"env": env, "updated": now, "positions": [{"symbol": "X/USDT"}] * 3,
                                                                  "entry_block": "", "review": {}}), encoding="utf-8")
        with mock.patch.object(self.m, "IPC_DIR", ipc):
            live = {r["id"]: r for r in self.c.get("/api/live/strategies?env=live", headers=self.h("admin-token")).json()["strategies"]}
            demo = {r["id"]: r for r in self.c.get("/api/live/strategies?env=demo", headers=self.h("admin-token")).json()["strategies"]}
        self.assertEqual((live["momentum_ls"]["running"], live["momentum_ls"]["positions"]), (True, 3))
        self.assertEqual((live["trend_daily"]["running"], live["trend_daily"]["positions"]), (False, 0))
        self.assertEqual((demo["trend_daily"]["running"], demo["trend_daily"]["positions"]), (True, 3))
        self.assertEqual((demo["momentum_ls"]["running"], demo["momentum_ls"]["positions"]), (False, 0))

    def test_browser_preflight_allows_patch(self):
        origin = self.m.ALLOWED_ORIGINS[0]
        r = self.c.options("/api/admin/users/u-user/settings", headers={
            "Origin": origin, "Access-Control-Request-Method": "PATCH", "Access-Control-Request-Headers": "authorization,content-type"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("PATCH", r.headers.get("access-control-allow-methods", ""))


if __name__ == "__main__":
    unittest.main()
