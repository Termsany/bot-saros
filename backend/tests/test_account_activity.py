"""Account activity page (security plan item 10, owner 2026-11-08): each sign-in session once, each sensitive change,
only the account's own rows, an admin's new session on Telegram, and nothing in it ever stops a request."""
import base64, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient
from app import account_activity as act, auth, security_alerts

USER_A = {"id": "u-aaa", "email": "a@example.com", "email_confirmed": True}
USER_B = {"id": "u-bbb", "email": "b@example.com", "email_confirmed": True}
ADMIN = {"id": "u-adm", "email": "admin@example.com", "email_confirmed": True}
CHROME_WIN = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


def jwt(claims):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{enc({'alg': 'none'})}.{enc(claims)}.sig"


class AccountActivityTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = Path(self.td.name) / "activity.sqlite3"
        self.p = mock.patch.object(act, "DEFAULT_PATH", self.db); self.p.start()
        act._SEEN.clear()

    def tearDown(self):
        self.p.stop(); act._SEEN.clear(); self.td.cleanup()

    def test_device_names_are_short(self):
        self.assertEqual(act.device(CHROME_WIN), "Chrome · Windows")
        self.assertEqual(act.device("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) AppleWebKit Version/17.0 Mobile Safari/604.1"), "Safari · iPhone/iPad")
        self.assertEqual(act.device("curl/8.4"), "برنامج")
        self.assertEqual(act.device(""), "متصفح")

    def test_a_session_is_recorded_once(self):
        self.assertTrue(act.session_seen(USER_A, "s1", ip="1.2.3.4", ua=CHROME_WIN))
        self.assertFalse(act.session_seen(USER_A, "s1", ip="1.2.3.4", ua=CHROME_WIN))
        act._SEEN.clear()                                   # an API restart: the database still knows it
        self.assertFalse(act.session_seen(USER_A, "s1", ip="1.2.3.4", ua=CHROME_WIN))
        self.assertTrue(act.session_seen(USER_A, "s2", ip="5.6.7.8", ua=CHROME_WIN))
        self.assertFalse(act.session_seen(USER_A, None))
        rows = act.list_for(USER_A)
        self.assertEqual([(r["kind"], r["ip"], r["device"]) for r in rows],
                         [("session", "5.6.7.8", "Chrome · Windows"), ("session", "1.2.3.4", "Chrome · Windows")])

    def test_each_account_sees_only_its_own(self):
        act.record("account", "حفظ مفتاح API", uid=USER_A["id"], email=USER_A["email"], details={"exchange": "binance"})
        act.record("account", "حفظ مفتاح API", uid=USER_B["id"], email=USER_B["email"])
        act.record("admin", "Kill switch trip (ok)", email=ADMIN["email"])          # admin actions carry the email only
        self.assertEqual([r["details"] for r in act.list_for(USER_A)], [{"exchange": "binance"}])
        self.assertEqual(len(act.list_for(USER_B)), 1)
        self.assertEqual([r["what"] for r in act.list_for(ADMIN)], ["Kill switch trip (ok)"])

    def test_old_rows_are_pruned(self):
        with mock.patch.object(act, "KEEP_ROWS", 5):
            for i in range(8):
                act.record("account", f"x{i}", uid=USER_A["id"])
            self.assertEqual([r["what"] for r in act.list_for(USER_A)], ["x7", "x6", "x5", "x4", "x3"])

    def test_a_broken_database_never_raises(self):
        with mock.patch.object(act, "DEFAULT_PATH", Path(self.td.name)):        # a folder, not a file
            self.assertFalse(act.record("account", "x", uid="u"))
            self.assertEqual(act.list_for(USER_A), [])

    def test_alerts_also_go_to_the_activity_page(self):
        with mock.patch.object(security_alerts, "_send", return_value=True):
            security_alerts.user_real_money(USER_A, "وافق على فلوس حقيقية", {"capital": 300})
            security_alerts.admin_action(ADMIN["email"], "kill_switch_trip", "ok", {"acct": "main"})
            security_alerts.admin_action(ADMIN["email"], "not_sensitive", "ok")
        self.assertEqual([(r["kind"], r["what"]) for r in act.list_for(USER_A)], [("real_money", "وافق على فلوس حقيقية")])
        self.assertEqual([r["what"] for r in act.list_for(ADMIN)], ["Kill switch trip (ok)"])


class SessionNotingTests(unittest.TestCase):
    """Through the API: require_user notes a new session, an admin's goes to Telegram, /api/user/activity is per user."""
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.tokens = {jwt({"sub": "a", "session_id": "sa"}): USER_A, jwt({"sub": "b", "session_id": "sb"}): USER_B,
                       jwt({"sub": "adm", "session_id": "sx", "aal": "aal2"}): {**ADMIN, "aal": "aal2"}}

        async def fake_verify(token):
            if token not in self.tokens: raise auth.HTTPException(401, "invalid")
            return self.tokens[token]
        self.patches = [mock.patch.object(act, "DEFAULT_PATH", Path(self.td.name) / "a.sqlite3"),
                        mock.patch.object(auth, "_verify_token", fake_verify),
                        mock.patch.dict(os.environ, {"ADMIN_EMAILS": ADMIN["email"]}),
                        mock.patch.object(security_alerts, "_send", return_value=True)]
        for p in self.patches: p.start()
        act._SEEN.clear()
        import app.main as mainmod
        mainmod.app.dependency_overrides = {}
        self.client = TestClient(mainmod.app)
        self.tok = {u["id"]: t for t, u in self.tokens.items()}

    def tearDown(self):
        for p in self.patches: p.stop()
        act._SEEN.clear(); self.td.cleanup()

    def get(self, uid):
        return self.client.get("/api/user/activity", headers={"Authorization": f"Bearer {self.tok[uid]}", "User-Agent": CHROME_WIN})

    def test_the_activity_endpoint(self):
        with mock.patch.object(security_alerts, "admin_session") as alert:
            r = self.get("u-aaa"); self.assertEqual(r.status_code, 200)
            self.get("u-aaa"); self.get("u-bbb")
            alert.assert_not_called()                       # not an admin
            self.get("u-adm"); self.get("u-adm")
            alert.assert_called_once()
            self.assertEqual(alert.call_args[0][2], "Chrome · Windows")
        items = self.get("u-aaa").json()["items"]
        self.assertEqual([(i["kind"], i["device"]) for i in items], [("session", "Chrome · Windows")])
        self.assertEqual(len(self.get("u-bbb").json()["items"]), 1)
        self.assertEqual(self.client.get("/api/user/activity").status_code, 401)

    def test_a_failure_to_note_never_stops_the_request(self):
        with mock.patch.object(act, "session_seen", side_effect=RuntimeError("disk full")):
            self.assertEqual(self.get("u-aaa").status_code, 200)


if __name__ == "__main__":
    unittest.main()
