"""Security plan item 4: the owner's phone hears of every sensitive change (owner, 2026-11-07)."""
import asyncio, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import admin_control, security_alerts


class SecurityAlertTests(unittest.TestCase):
    def run_sent(self, fn):
        """Run fn inside an event loop with send_telegram recorded; returns the texts sent."""
        sent = []
        async def fake(text, *a, **k): sent.append(text); return True
        async def go():
            with mock.patch("app.telegram_bot.send_telegram", fake):
                fn()
                await asyncio.sleep(0)                      # the background send runs
                await asyncio.gather(*list(security_alerts._TASKS))
        asyncio.run(go())
        return sent

    def test_sensitive_admin_actions_alert_and_routine_ones_dont(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            root = Path(d)
            sent = self.run_sent(lambda: (
                admin_control.audit(root, "owner@example.com", "users_live_on", "ok", {}),
                admin_control.audit(root, "owner@example.com", "kill_switch_reset", "ok", {"acct": ""}),
                admin_control.audit(root, "owner@example.com", "strategy_update", "ok", {"strategy": "trend_daily"})))
            self.assertEqual(len(sent), 2)
            self.assertIn("فتح الفلوس الحقيقية للمستخدمين", sent[0]); self.assertIn("owner@example.com", sent[0])
            self.assertIn("Kill switch reset", sent[1])
            self.assertEqual(len(admin_control.list_audit(root)), 3)            # the audit log itself is unchanged

    def test_no_event_loop_no_send_and_no_error(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            admin_control.audit(Path(d), "owner@example.com", "users_live_on", "ok", {})   # a script: nothing raised
        self.assertFalse(security_alerts.admin_action("a", "users_live_on", "ok"))

    def test_a_failing_sender_never_breaks_the_action(self):
        async def go():
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d,                  mock.patch("app.telegram_bot.send_telegram", side_effect=RuntimeError("down")):
                admin_control.audit(Path(d), "a", "risk_limits", "ok", {"x": 1})          # returns normally
                await asyncio.gather(*list(security_alerts._TASKS), return_exceptions=True)
                return admin_control.list_audit(Path(d))[0]["action"]
        self.assertEqual(asyncio.run(go()), "risk_limits")
        with mock.patch("asyncio.get_running_loop", return_value=mock.Mock(create_task=mock.Mock(side_effect=RuntimeError("x")))):
            self.assertFalse(security_alerts.admin_action("a", "risk_limits", "ok"))   # even scheduling failing is swallowed

    def test_long_details_are_cut_and_a_users_real_money_change_says_who(self):
        sent = self.run_sent(lambda: security_alerts.user_real_money({"id": "abcdef0123", "email": None}, "وافق على فلوس حقيقية",
                                                                     {"note": "x" * 1000}))
        self.assertTrue(sent[0].startswith("💰 مستخدم · وافق على فلوس حقيقية\nabcdef01"))
        self.assertLess(len(sent[0]), 400)


if __name__ == "__main__":
    unittest.main()
