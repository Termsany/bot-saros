"""A user's monthly statement (owner, 2026-11-08): their own bots' closed trades in one month, per bot and in total,
Demo and real money apart, only their own folders; and the bot writes what it needs into closed.json."""
import json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient
from app import auth, user_bots, user_statement as us

UID_A = "11111111-1111-4111-8111-111111111111"
UID_B = "22222222-2222-4222-8222-222222222222"
USERS = {"a-token": {"id": UID_A, "email": "a@example.com", "email_confirmed": True},
         "b-token": {"id": UID_B, "email": "b@example.com", "email_confirmed": True}}


def row(time, pnl, **kw):
    return {"symbol": "SOL/USDT", "side": "long", "opened": time, "time": time, "entry": 100, "exit": 110, "qty": 1, "pnl": pnl, **kw}


class StatementTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.ipc = Path(self.td.name)

    def tearDown(self):
        self.td.cleanup()

    def write(self, uid, strategy, env, rows, legacy=False):
        d = (self.ipc / uid / strategy) if legacy else user_bots.ipc_instance(uid, strategy, self.ipc)
        d.mkdir(parents=True, exist_ok=True)
        (d / "closed.json").write_text(json.dumps({"env": env, "closed": rows}), encoding="utf-8")

    def test_one_month_per_bot_and_in_total(self):
        self.write(UID_A, "momentum_ls", "live", [row("2026-11-09T00:20:00+00:00", 3.5, funding_pnl=-0.1),
                                                  row("2026-11-16T00:20:00+00:00", -2.0, funding_pnl=0.05),
                                                  row("2026-10-31T23:59:00+00:00", 9.0),
                                                  row("2026-11-20T00:00:00+00:00", None)])
        self.write(UID_A, "rsi2_pullback", "live", [row("2026-11-12T00:00:00+00:00", 1.25)], legacy=True)
        closed = us.closed_by_strategy(UID_A, self.ipc)
        self.assertEqual(us.months(closed), ["2026-11", "2026-10"])
        s = us.build(closed, "2026-11")
        m = s["strategies"]["momentum_ls"]
        self.assertEqual((m["trades"], m["wins"], m["losses"], m["unknown"]), (3, 1, 1, 1))
        self.assertEqual((m["net_usdt"], m["funding_usdt"], m["best_usdt"], m["worst_usdt"]), (1.5, -0.05, 3.5, -2.0))
        self.assertEqual(s["total"]["net_usdt"], 2.75); self.assertEqual(s["total"]["trades"], 4)
        self.assertEqual([t["time"][:10] for t in s["trades"]], ["2026-11-20", "2026-11-16", "2026-11-12", "2026-11-09"])
        self.assertEqual(us.build(closed, "2026-10")["total"]["net_usdt"], 9.0)
        with self.assertRaises(ValueError): us.build(closed, "2026-13")
        with self.assertRaises(ValueError): us.build(closed, "../x")

    def test_demo_and_real_money_apart(self):
        self.write(UID_A, "momentum_ls", "live", [row("2026-11-09T00:00:00+00:00", 3.0)])
        self.write(UID_A, "trend_daily", "demo", [row("2026-11-09T00:00:00+00:00", 50.0)])
        closed = us.closed_by_strategy(UID_A, self.ipc)
        self.assertEqual(us.build(closed, "2026-11", "live")["total"]["net_usdt"], 3.0)
        self.assertEqual(list(us.build(closed, "2026-11", "demo")["strategies"]), ["trend_daily"])

    def test_the_bot_writes_what_the_statement_needs(self):
        import bot as botmod
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            botmod._CLOSED_WRITTEN["n"] = None
            botmod._write_closed(Path(d), {"history": [{"type": "live", **row("2026-11-09T00:00:00+00:00", 1.0, funding_pnl=-0.2)}]})
            got = json.loads((Path(d) / "closed.json").read_text(encoding="utf-8"))["closed"][0]
        for k in ("entry", "exit", "qty", "funding_pnl", "pnl", "time"):
            self.assertIn(k, got)


class StatementEndpointTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.ipc = Path(self.td.name)

        async def fake_verify(token):
            if token not in USERS: raise auth.HTTPException(401, "invalid")
            return USERS[token]
        self.patches = [mock.patch.object(auth, "_verify_token", fake_verify),
                        mock.patch.object(user_bots, "IPC_ROOT", self.ipc)]
        for p in self.patches: p.start()
        import app.main as mainmod
        mainmod.app.dependency_overrides = {}
        self.client = TestClient(mainmod.app)
        d = user_bots.ipc_instance(UID_A, "momentum_ls", self.ipc); d.mkdir(parents=True)
        (d / "closed.json").write_text(json.dumps({"env": "live", "closed": [row("2026-11-09T00:20:00+00:00", 4.0)]}), encoding="utf-8")

    def tearDown(self):
        for p in self.patches: p.stop()
        self.td.cleanup()

    def get(self, tok, q=""):
        return self.client.get(f"/api/user/statement{q}", headers={"Authorization": f"Bearer {tok}"})

    def test_each_user_gets_only_their_own(self):
        a = self.get("a-token").json()
        self.assertEqual((a["month"], a["months"], a["total"]["net_usdt"]), ("2026-11", ["2026-11"], 4.0))
        b = self.get("b-token").json()
        self.assertEqual((b["months"], b["total"]["trades"]), ([], 0))
        self.assertEqual(self.get("a-token", "?env=demo").json()["total"]["trades"], 0)
        self.assertEqual(self.get("a-token", "?month=bad").status_code, 400)
        self.assertEqual(self.get("a-token", "?env=x").status_code, 400)
        self.assertEqual(self.client.get("/api/user/statement").status_code, 401)


if __name__ == "__main__":
    unittest.main()
