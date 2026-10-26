import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import sys

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app import admin_control
import app.main as main
from app.testnet_readiness import build_admin_readiness

ADMIN = {"id": "admin", "email": "admin@example.com"}


class LifecycleAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old_root = main.BOT_DIR
        self.old_task = main.bot_task
        main.BOT_DIR = self.root
        main.bot_task = None

    async def asyncTearDown(self):
        if main.bot_task and not main.bot_task.done():
            main.bot_task.cancel()
            try:
                await main.bot_task
            except asyncio.CancelledError:
                pass
        main.bot_task = self.old_task
        main.BOT_DIR = self.old_root
        self.tmp.cleanup()

    async def test_start_waits_for_real_heartbeat_before_running(self):
        async def fake_loop(cfg, task_id=None):
            await asyncio.sleep(0.05)
            admin_control.mark_runtime(self.root, "trend_daily", status="running", heartbeat=admin_control.now(), task_id="task-1")
            await asyncio.Event().wait()

        with mock.patch.object(main, "bot_loop", fake_loop):
            result = await main.admin_strategy_lifecycle(
                "trend_daily", main.LifecycleReq(action="start", confirm=True), ADMIN
            )
        self.assertEqual(result["runtime"]["status"], "running")
        self.assertEqual(result["runtime"]["task_id"], "task-1")
        self.assertTrue(result["running"])

    async def test_stop_and_pause_block_entries_but_protection_runs(self):
        admin_control.set_strategy_lifecycle(self.root, "trend_daily", "pause", "admin")
        calls = []

        def protect():
            calls.append("protect")

        def enter():
            calls.append("enter")

        result = main.execute_strategy_cycle(self.root, "trend_daily", protect, enter)
        self.assertFalse(result["entries_enabled"])
        self.assertEqual(calls, ["protect"])

    async def test_runtime_persists_across_restart(self):
        admin_control.mark_runtime(self.root, "trend_daily", status="running", heartbeat="2026-10-26T00:00:00+00:00", task_id="persisted")
        self.assertEqual(admin_control.get_runtime(self.root, "trend_daily")["task_id"], "persisted")
        self.assertEqual(admin_control.get_runtime(self.root, "trend_daily")["status"], "running")


class ReadinessAcceptanceTests(unittest.TestCase):
    def test_incomplete_evidence_never_live_ready_and_aggregates_are_distinct(self):
        result = build_admin_readiness(
            strategies=["trend_daily", "ratio_trend"],
            evidence={"trend_daily": {"adapter_implemented": True, "recovery_tests": True, "security_approved": True, "testnet_validated": True}},
            live_locked=True,
        )
        self.assertFalse(result["paper_ready"])
        self.assertFalse(result["testnet_ready"])
        self.assertFalse(result["live_ready"])
        self.assertFalse(result["strategies"]["ratio_trend"]["live_ready"])
        self.assertFalse(result["strategies"]["ratio_trend"]["security_approved"])

    def test_truthful_per_strategy_statuses_do_not_infer_from_names(self):
        result = build_admin_readiness(strategies=["trend_daily"], evidence={}, live_locked=True)
        item = result["strategies"]["trend_daily"]
        self.assertFalse(item["adapter_implemented"])
        self.assertFalse(item["recovery_tests"])
        self.assertFalse(item["security_approved"])
        self.assertFalse(item["testnet_validated"])
        self.assertIn("missing", " ".join(item["reasons"]).lower())


if __name__ == "__main__":
    unittest.main()
