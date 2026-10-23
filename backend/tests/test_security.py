"""
Run from repo root:  python -m unittest discover -s backend/tests -v
(no network needed — Supabase auth is stubbed, candles are synthetic)
"""
import asyncio, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from app import auth, keys_vault
from app.main import app, _get_exchange_for_cycle
from app.llm_sandbox import validate_code, UnsafeCode, run_backtest_sandboxed

ADMIN = {"id": "u-admin", "email": "admin@example.com", "email_confirmed": True}
USER = {"id": "u-user", "email": "user@example.com", "email_confirmed": True}
# attacker who signed up with the admin's address but never confirmed it
SQUATTER = {"id": "u-squat", "email": "admin@example.com", "email_confirmed": False}
TOKENS = {"admin-token": ADMIN, "user-token": USER, "squat-token": SQUATTER}


async def fake_verify(token):
    if token not in TOKENS:
        raise auth.HTTPException(401, "invalid")
    return TOKENS[token]


def candles(n=400, seed=1):
    rng = np.random.default_rng(seed)
    close = 30000 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    high = close * (1 + rng.uniform(0, 0.01, n))
    low = close * (1 - rng.uniform(0, 0.01, n))
    open_ = np.r_[close[0], close[:-1]]
    ts = pd.date_range("2026-01-01", periods=n, freq="4h")
    return pd.DataFrame({"ts": ts, "open": open_, "high": high, "low": low, "close": close, "vol": rng.uniform(1, 100, n)})


GOOD_STRATEGY = '''
import numpy as np
import pandas as pd

def llm_signal(df):
    c = df["close"]
    fast = c.rolling(5).mean().iloc[-1]
    slow = c.rolling(20).mean().iloc[-1]
    if np.isnan(slow):
        return 0.0, []
    s = (fast - slow) / slow * 50
    return float(max(-1, min(1, s))), ["ma cross"]
'''


class ApiAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [
            mock.patch.object(auth, "_verify_token", fake_verify),
            mock.patch.object(keys_vault, "VAULT_PATH", Path(self.tmp.name) / "vault.json"),
            mock.patch.dict(os.environ, {"ADMIN_EMAILS": ADMIN["email"], "CRON_SECRET": "cron-s3cret",
                                         "VAULT_MASTER_KEY": "", "ALLOW_LIVE_TRADING": ""}),
        ]
        for p in self.patches: p.start()
        os.environ["VAULT_MASTER_KEY"] = __import__("cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode()
        self.c = TestClient(app)

    def tearDown(self):
        for p in self.patches: p.stop()
        self.tmp.cleanup()

    def h(self, tok):
        return {"Authorization": f"Bearer {tok}"}

    def test_every_endpoint_except_health_and_chart_requires_login(self):
        public = {"/api/health", "/api/chart", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
        checked = 0
        for r in app.routes:
            if not hasattr(r, "methods") or r.path in public:
                continue
            for m in r.methods - {"HEAD", "OPTIONS"}:
                resp = self.c.request(m, r.path, json={})
                self.assertEqual(resp.status_code, 401, f"{m} {r.path} -> {resp.status_code}")
                checked += 1
        self.assertGreaterEqual(checked, 20)

    def test_admin_endpoints_reject_normal_user(self):
        for m, path in [("GET", "/api/keys/status"), ("POST", "/api/keys/paper"), ("GET", "/api/trades"),
                        ("POST", "/api/bot/stop"), ("GET", "/api/bot/status"), ("POST", "/api/llm/generate"),
                        ("POST", "/api/evolve"), ("POST", "/api/telegram/test")]:
            resp = self.c.request(m, path, headers=self.h("user-token"), json={})
            self.assertEqual(resp.status_code, 403, f"{m} {path}")

    def test_admin_fails_closed_without_admin_emails(self):
        with mock.patch.dict(os.environ, {"ADMIN_EMAILS": ""}):
            self.assertEqual(self.c.get("/api/keys/status", headers=self.h("admin-token")).status_code, 403)

    def test_unconfirmed_admin_email_is_not_admin(self):
        self.assertEqual(self.c.get("/api/keys/status", headers=self.h("squat-token")).status_code, 403)
        self.assertEqual(self.c.get("/api/keys/status", headers=self.h("admin-token")).status_code, 200)

    def test_backtest_plan_limits_enforced_server_side(self):
        from app import main
        main._rate_hits.clear(); main._tier_cache.clear()
        with mock.patch.dict(os.environ, {"SUPABASE_SERVICE_KEY": ""}):  # no tier lookup -> free
            r = self.c.post("/api/backtest", headers=self.h("user-token"), json={"strategies": ["ict"], "from": "2026-10-13", "to": "2026-10-19"})
            self.assertEqual(r.status_code, 403)
            self.assertIn("ict", r.json()["detail"])
            self.assertEqual(asyncio.run(main.get_tier(USER)), "free")
            self.assertEqual(asyncio.run(main.get_tier(ADMIN)), "elite")
            self.assertEqual(asyncio.run(main.get_tier(SQUATTER)), "free")

    def test_backtest_day_limits_per_plan(self):
        from app import main
        main._rate_hits.clear(); main._tier_cache.clear()
        span = lambda **kw: main.backtest_span_days(main.BacktestReq(**kw))
        self.assertEqual(span(**{"from": "2026-10-13", "to": "2026-10-19"}), 7)  # end day inclusive
        self.assertEqual(span(**{"from": "2026-09-19", "to": "2026-10-19"}), 31)  # the old default range
        self.assertEqual(span(timeframe="1h", limit=168), 7)  # no dates: limit candles
        with mock.patch.dict(os.environ, {"SUPABASE_SERVICE_KEY": ""}):  # -> free = 7 days
            body = {"from": "2026-10-12", "to": "2026-10-19", "strategies": ["rsi_macd"]}  # 8 days
            r = self.c.post("/api/backtest", headers=self.h("user-token"), json=body)
            self.assertEqual(r.status_code, 403)
            self.assertIn("7 days", r.json()["detail"])
            for bad in [{"from": "2026-13-45", "to": "2026-10-19"}, {"to": "2026-10-19"},
                        {"from": "2026-10-19", "to": "2026-10-01"}]:
                self.assertEqual(self.c.post("/api/backtest", headers=self.h("user-token"), json=bad).status_code, 422, bad)
        self.assertIsNone(main.TIER_BACKTEST_DAYS["elite"])

    def test_supabase_key_check_detects_wrong_key_without_logging_it(self):
        import base64, io, json as _j, contextlib
        from app import main
        jwt = lambda role: "x." + base64.urlsafe_b64encode(_j.dumps({"role": role}).encode()).decode().rstrip("=") + ".sig"
        self.assertEqual(main._supabase_key_kind(jwt("service_role")), "service")
        self.assertEqual(main._supabase_key_kind(jwt("anon")), "public")
        self.assertEqual(main._supabase_key_kind("sb_secret_abc"), "service")
        self.assertEqual(main._supabase_key_kind("sb_publishable_abc"), "public")
        anon = jwt("anon")
        for env, expect in [({"SUPABASE_URL": "", "SUPABASE_SERVICE_KEY": ""}, "MISSING"),
                            ({"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_KEY": anon}, "WRONG KEY")]:
            out = io.StringIO()
            with mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out):
                asyncio.run(main.check_supabase_service_key())
            self.assertIn(expect, out.getvalue())
            self.assertNotIn(anon, out.getvalue())

    def test_cron_secret(self):
        self.assertEqual(self.c.post("/api/evolve", headers={"X-Cron-Secret": "wrong"}).status_code, 401)
        r = self.c.post("/api/evolve", headers={"X-Cron-Secret": "cron-s3cret"})
        self.assertEqual(r.status_code, 200)  # auto_optimizer.py missing -> ok:false, but authorized

    def test_new_keys_start_in_paper_and_live_needs_kill_switch(self):
        r = self.c.post("/api/keys/save", headers=self.h("admin-token"),
                        json={"exchange": "bybit", "apiKey": "APIKEY-XYZ", "secret": "SECRET-XYZ"})
        self.assertEqual(r.status_code, 200)
        st = self.c.get("/api/keys/status", headers=self.h("admin-token")).json()
        self.assertTrue(st["bybit"]["configured"])
        self.assertTrue(st["bybit"]["paper"])
        self.assertNotIn("XYZ", str(st))  # secrets never returned
        r = self.c.post("/api/keys/paper", headers=self.h("admin-token"), json={"exchange": "bybit", "paper": False})
        self.assertEqual(r.status_code, 400)
        with mock.patch.dict(os.environ, {"ALLOW_LIVE_TRADING": "true"}):
            r = self.c.post("/api/keys/paper", headers=self.h("admin-token"), json={"exchange": "bybit", "paper": False})
            self.assertEqual(r.status_code, 200)
            # re-saving keys keeps LIVE (doesn't silently flip mode)
            self.c.post("/api/keys/save", headers=self.h("admin-token"), json={"exchange": "bybit", "apiKey": "k2", "secret": "s2"})
            self.assertFalse(self.c.get("/api/keys/status", headers=self.h("admin-token")).json()["bybit"]["paper"])

    def test_bot_live_start_blocked_without_kill_switch(self):
        r = self.c.post("/api/bot/start", headers=self.h("admin-token"), json={"paper": False})
        self.assertEqual(r.status_code, 400)
        self.assertIsNone(_get_exchange_for_cycle(paper=False))

    def test_bot_live_start_refused_even_with_the_switch_on(self):
        # real orders run only as the daily trend's own service, never from the dashboard loop
        with mock.patch.dict(os.environ, {"ALLOW_LIVE_TRADING": "true"}):
            r = self.c.post("/api/bot/start", headers=self.h("admin-token"), json={"paper": False})
        self.assertEqual(r.status_code, 400)

    def test_chart_path_traversal_blocked(self):
        # traversal must be 400 even with auth; unauthenticated without traversal is 401
        for f in ["backtest_/../backend/vault.json", "backtest_..%2f..%2fx.json", "backtest_a.png/../../x.png", "x.png"]:
            self.assertEqual(self.c.get("/api/chart", params={"file": f}, headers=self.h("user-token")).status_code, 400, f)
        # unauthenticated cannot list charts at all (IDOR fix: require_user)
        self.assertEqual(self.c.get("/api/chart", params={"file": "backtest_BTCUSDT_1d_abc1234567.png"}).status_code, 401)

    def test_docs_hidden_by_default(self):
        self.assertEqual(self.c.get("/docs").status_code, 404)
        self.assertEqual(self.c.get("/openapi.json").status_code, 404)

    def test_backtest_rate_limited(self):
        from app import main
        main._rate_hits.clear()
        for _ in range(5):
            main.rate_limit("u1", "backtest", 5, 60)
        with self.assertRaises(auth.HTTPException) as cm:
            main.rate_limit("u1", "backtest", 5, 60)
        self.assertEqual(cm.exception.status_code, 429)
        main.rate_limit("u2", "backtest", 5, 60)  # other users unaffected

    def test_backtest_input_validation(self):
        for body in [{"symbol": "--out=/tmp/x"}, {"timeframe": "--x"}, {"from": "2026/01/01"}, {"strategies": ["a;b"]}]:
            r = self.c.post("/api/backtest", headers=self.h("user-token"), json=body)
            self.assertEqual(r.status_code, 422, body)


class SandboxTests(unittest.TestCase):
    def test_rejects_dangerous_code(self):
        bad = [
            "import os\ndef llm_signal(df): return 0, []",
            "def llm_signal(df): return open('/etc/passwd').read(), []",
            "def llm_signal(df): return __import__('os').system('id'), []",
            "import pandas as pd\ndef llm_signal(df): pd.read_csv('backend/.master.key'); return 0, []",
            "def llm_signal(df): return df.__class__.__mro__, []",
            "def llm_signal(df): return df.eval('1'), []",
            "def llm_signal(df): df.to_pickle('x'); return 0, []",
            "import numpy as np\ndef llm_signal(df): np.load('x'); return 0, []",
            "def llm_signal(df): df['close'].values.dump('x'); return 0, []",
            "import pandas as pd\ndef llm_signal(df): pd.ExcelWriter('x.xlsx'); return 0, []",
            "def llm_signal(df): return getattr(df, 'x'), []",
            "import subprocess\ndef llm_signal(df): return 0, []",
            "from os import path\ndef llm_signal(df): return 0, []",
            "print('side effect at import')\ndef llm_signal(df): return 0, []",
            "def other(df): return 0, []",
        ]
        for code in bad:
            with self.assertRaises(UnsafeCode, msg=code):
                validate_code(code)

    def test_accepts_normal_strategy(self):
        validate_code(GOOD_STRATEGY)

    def test_sandboxed_backtest_runs_and_trades(self):
        res = asyncio.run(run_backtest_sandboxed(GOOD_STRATEGY, candles(), ROOT))
        self.assertTrue(res.get("ok"), res)
        # before the fix, enabled=["llm_tmp"] always scored 0 -> never traded
        self.assertGreater(res["total"], 0, res)

    def test_child_has_no_secrets(self):
        with mock.patch.dict(os.environ, {"VAULT_MASTER_KEY": "SECRET", "TELEGRAM_BOT_TOKEN": "SECRET"}):
            from app.llm_sandbox import _child_env
            env = _child_env(str(ROOT))
        self.assertNotIn("SECRET", str(env))


class BacktestTests(unittest.TestCase):
    def test_run_backtest_with_breakeven_does_not_crash(self):
        import backtest as bt
        res = bt.run_backtest(candles(300), amount_usdt=20, leverage=5, enabled=["rsi_macd", "classical", "supertrend"])
        self.assertIn("stats", res)
        for t in res["trades"]:
            self.assertIn(t["reason"], {"SL", "TP", "reverse", "close"})


if __name__ == "__main__":
    unittest.main()


class LiveCloseApiTests(ApiAuthTests):
    """Manual close from the admin page: admin only, only an open position, written as a request file for the bot."""
    def setUp(self):
        super().setUp()
        import app.main as m
        self.ipc = Path(self.tmp.name) / "ipc"; (self.ipc / "commands").mkdir(parents=True); (self.ipc / "results").mkdir()
        self.p_ipc = mock.patch.object(m, "IPC_DIR", self.ipc); self.p_ipc.start()
        from datetime import datetime, timezone
        import json as _j
        (self.ipc / "live_status.json").write_text(_j.dumps({"updated": datetime.now(timezone.utc).isoformat(), "env": "demo",
            "positions": [{"symbol": "SOL/USDT", "entry": 100, "qty": 1, "sl": 84}]}), encoding="utf-8")
    def tearDown(self):
        self.p_ipc.stop(); super().tearDown()

    def test_admin_only(self):
        self.assertEqual(self.c.get("/api/live/status", headers=self.h("user-token")).status_code, 403)
        self.assertEqual(self.c.post("/api/live/close", headers=self.h("user-token"), json={"symbol": "SOL/USDT"}).status_code, 403)

    def test_close_writes_one_request_for_an_open_position(self):
        r = self.c.post("/api/live/close", headers=self.h("admin-token"), json={"symbol": "SOL/USDT"})
        self.assertEqual(r.status_code, 200)
        files = list((self.ipc / "commands").glob("close-*.json"))
        self.assertEqual(len(files), 1)
        self.assertEqual(self.c.get(f"/api/live/close/{r.json()['id']}", headers=self.h("admin-token")).json(), {"done": False, "pending": True})

    def test_refuses_unknown_coin_and_junk(self):
        self.assertEqual(self.c.post("/api/live/close", headers=self.h("admin-token"), json={"symbol": "ETH/USDT"}).status_code, 404)
        self.assertEqual(self.c.post("/api/live/close", headers=self.h("admin-token"), json={"symbol": "../../x"}).status_code, 400)
        self.assertEqual(self.c.get("/api/live/close/../../etc", headers=self.h("admin-token")).status_code in (400, 404), True)
