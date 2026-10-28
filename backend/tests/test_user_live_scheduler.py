"""Per-user live-trading scheduler — Phase 2 (2)(3)(4) regression tests (TDD).

All exchange interaction is a deterministic in-memory fake — nothing in this
file or the module it tests ever makes a real/testnet network call.
"""
import sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app import user_live_trading as ult
from app import user_live_activation as ula
from app import user_keys_vault as ukv
from app import risk_manager as riskmgr
from app import user_live_scheduler as sched
from backend.tests.test_user_live_trading import FakeBinance  # type: ignore

SIG_ON = {"price": 100.0, "trend": {"on": True, "ts": 1, "size": 1.0}, "in_universe": True, "rank": 1, "total": 0}
SIG_OFF = {"price": 110.0, "trend": {"on": False, "ts": 2, "size": 1.0}, "in_universe": True, "rank": 1, "total": 0}


class SchedulerTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.bot_dir = Path(self.tmp.name)
        self.activation_path = self.bot_dir / "user_live_activation.sqlite3"
        self.vault_patch = mock.patch.object(ukv, "VAULT_PATH", self.bot_dir / "user_vault.json")
        self.vault_patch.start()
        import os
        self._old_master = os.environ.get("VAULT_MASTER_KEY")
        from cryptography.fernet import Fernet
        os.environ["VAULT_MASTER_KEY"] = Fernet.generate_key().decode()

    def tearDown(self):
        self.vault_patch.stop()
        import os
        if self._old_master is None: os.environ.pop("VAULT_MASTER_KEY", None)
        else: os.environ["VAULT_MASTER_KEY"] = self._old_master
        self.tmp.cleanup()

    def _enable(self, user_id, exchange="binance", **kw):
        ukv.save_user_keys(user_id, exchange, "AKEY", "ASECRET", "")
        ula.enable_user_live(self.activation_path, user_id=user_id, exchange=exchange,
                              confirm=ula.CONSENT_TEXT, actor=user_id, **kw)


class ZeroUsersNoCallsTests(SchedulerTestBase):
    def test_tick_is_a_total_noop_with_no_live_enabled_users(self):
        factory = mock.Mock()
        result = sched.run_scheduler_tick(bot_dir=self.bot_dir, activation_path=self.activation_path,
                                           watch_symbols=["SOL/USDT:USDT"],
                                           analysis_provider=lambda s: SIG_ON, exchange_factory=factory)
        self.assertEqual(result["users_processed"], 0)
        factory.assert_not_called()


class PerUserIsolationTests(SchedulerTestBase):
    def test_one_users_exchange_factory_exception_does_not_stop_the_next_user(self):
        self._enable("u1"); self._enable("u2")
        exB = FakeBinance(balance=50_000.0)

        def factory(user_id, exchange):
            if user_id == "u1":
                raise RuntimeError("exchange init blew up for u1")
            return exB

        result = sched.run_scheduler_tick(bot_dir=self.bot_dir, activation_path=self.activation_path,
                                           watch_symbols=["SOL/USDT:USDT"],
                                           analysis_provider=lambda s: SIG_ON, exchange_factory=factory)
        self.assertEqual(result["users_processed"], 2)
        self.assertIn("u1", result["errors"])
        self.assertNotIn("u1", result["results"])
        self.assertIn("u2", result["results"])
        self.assertTrue(result["results"]["u2"]["SOL/USDT:USDT"]["fired"])

    def test_missing_keys_at_build_time_is_isolated_as_an_error_not_a_crash(self):
        self._enable("u1")

        def factory(user_id, exchange):
            return None  # simulates keys deleted between the gate check and the build

        result = sched.run_scheduler_tick(bot_dir=self.bot_dir, activation_path=self.activation_path,
                                           watch_symbols=["SOL/USDT:USDT"],
                                           analysis_provider=lambda s: SIG_ON, exchange_factory=factory)
        self.assertIn("u1", result["errors"])


class ReentrancyTests(SchedulerTestBase):
    def test_a_tick_called_while_one_is_already_running_is_skipped_not_queued(self):
        self._enable("u1")
        self.assertTrue(sched._TICK_LOCK.acquire(blocking=False))
        try:
            result = sched.run_scheduler_tick(bot_dir=self.bot_dir, activation_path=self.activation_path,
                                               watch_symbols=["SOL/USDT:USDT"],
                                               analysis_provider=lambda s: SIG_ON,
                                               exchange_factory=lambda u, e: FakeBinance())
            self.assertEqual(result, {"skipped": "previous tick still running"})
        finally:
            sched._TICK_LOCK.release()


class ReconciliationTests(SchedulerTestBase):
    def test_exchange_flat_but_local_open_marks_recovery_required(self):
        self._enable("u1")
        state_path = ult.user_state_path(self.bot_dir, "u1")
        state = ult.load_user_state(state_path)
        state["positions"]["SOL/USDT:USDT"] = {"side": "long", "entry": 100.0, "qty": 2.0, "contract_size": 1.0,
                                                 "contract_size_verified": True, "leverage": 2}
        ult.save_user_state(state_path, state)
        ex = FakeBinance()  # fresh fake — exchange genuinely has no position for this symbol
        findings = sched.reconcile_user_positions("u1", ex, self.bot_dir)
        self.assertIn("SOL/USDT:USDT", findings)
        state2 = ult.load_user_state(state_path)
        self.assertIn("SOL/USDT:USDT", state2["recovery_required"])

    def test_recovery_required_blocks_new_entries_even_after_local_position_clears(self):
        self._enable("u1")
        state_path = ult.user_state_path(self.bot_dir, "u1")
        state = ult.load_user_state(state_path)
        state["recovery_required"] = {"SOL/USDT:USDT": {"reason": "mismatch", "at": "now"}}
        ult.save_user_state(state_path, state)  # symbol NOT in positions -> would otherwise be a fresh entry
        ex = FakeBinance(balance=50_000.0)
        result = ult.run_trend_daily_live_cycle(user_id="u1", symbol="SOL/USDT:USDT", ex=ex, bot_dir=self.bot_dir,
                                                  analysis=SIG_ON, activation_path=self.activation_path)
        self.assertFalse(result["fired"])
        self.assertIn("recovery_required", result["reason"])
        self.assertEqual(ex.orders, [])

    def test_matching_exchange_position_does_not_flag_anything(self):
        self._enable("u1")
        state_path = ult.user_state_path(self.bot_dir, "u1")
        state = ult.load_user_state(state_path)
        state["positions"]["SOL/USDT:USDT"] = {"side": "long", "entry": 100.0, "qty": 2.0, "contract_size": 1.0,
                                                 "contract_size_verified": True, "leverage": 2}
        ult.save_user_state(state_path, state)
        ex = FakeBinance()
        ex.positions["SOL/USDT"] = 2.0  # exchange agrees a position is open
        findings = sched.reconcile_user_positions("u1", ex, self.bot_dir)
        self.assertEqual(findings, {})
        state2 = ult.load_user_state(state_path)
        self.assertNotIn("SOL/USDT:USDT", state2.get("recovery_required", {}))


class KillSwitchPollingTests(SchedulerTestBase):
    def test_drawdown_trip_blocks_new_entries_but_not_exits(self):
        self._enable("u1", risk_per_trade_pct=1.0, max_aggregate_risk_pct=1.0)
        ex_rich = FakeBinance(balance=50_000.0)
        entry = ult.run_trend_daily_live_cycle(user_id="u1", symbol="SOL/USDT:USDT", ex=ex_rich, bot_dir=self.bot_dir,
                                                 analysis=SIG_ON, activation_path=self.activation_path, margin_usdt=100.0)
        self.assertTrue(entry["fired"])
        # Establishes the high-water mark at 50,000 with no drawdown yet.
        tripped0, _ = sched.poll_user_kill_switch("u1", ex_rich, self.bot_dir)
        self.assertFalse(tripped0)
        # Equity craters -> drawdown polling (independent of any strategy signal) trips the switch.
        ex_poor = FakeBinance(balance=30_000.0)
        tripped1, reason1 = sched.poll_user_kill_switch("u1", ex_poor, self.bot_dir)
        self.assertTrue(tripped1)
        self.assertIn("drawdown", reason1)
        # New entry on a different symbol is blocked by the now-tripped kill switch.
        blocked = ult.run_trend_daily_live_cycle(user_id="u1", symbol="DOGE/USDT:USDT", ex=ex_poor, bot_dir=self.bot_dir,
                                                   analysis=SIG_ON, activation_path=self.activation_path, margin_usdt=100.0)
        self.assertFalse(blocked["fired"])
        self.assertIn("kill switch", blocked["reason"])
        # Exiting the ALREADY-open position still works — exits never go through pre_trade_gate.
        # (uses ex_rich: the exchange instance that actually tracks the open position's fills)
        exit_result = ult.run_trend_daily_live_cycle(user_id="u1", symbol="SOL/USDT:USDT", ex=ex_rich, bot_dir=self.bot_dir,
                                                       analysis=SIG_OFF, activation_path=self.activation_path, margin_usdt=100.0)
        self.assertTrue(exit_result["fired"])
        self.assertEqual(exit_result["action"], "exit")

    def test_equity_unavailable_fails_closed_and_trips(self):
        self._enable("u1")
        ex = FakeBinance(); ex.fetch_balance = lambda: (_ for _ in ()).throw(Exception("boom"))
        tripped, reason = sched.poll_user_kill_switch("u1", ex, self.bot_dir)
        self.assertTrue(tripped)
        self.assertIn("equity unavailable", reason)


class IntegrationTickTests(SchedulerTestBase):
    def test_full_tick_processes_two_users_independently(self):
        self._enable("u1"); self._enable("u2")
        ex1, ex2 = FakeBinance(balance=50_000.0), FakeBinance(balance=50_000.0)

        def factory(user_id, exchange):
            return {"u1": ex1, "u2": ex2}[user_id]

        result = sched.run_scheduler_tick(bot_dir=self.bot_dir, activation_path=self.activation_path,
                                           watch_symbols=["SOL/USDT:USDT"],
                                           analysis_provider=lambda s: SIG_ON, exchange_factory=factory)
        self.assertEqual(result["users_processed"], 2)
        self.assertTrue(result["results"]["u1"]["SOL/USDT:USDT"]["fired"])
        self.assertTrue(result["results"]["u2"]["SOL/USDT:USDT"]["fired"])
        s1 = ult.load_user_state(ult.user_state_path(self.bot_dir, "u1"))
        s2 = ult.load_user_state(ult.user_state_path(self.bot_dir, "u2"))
        self.assertIn("SOL/USDT:USDT", s1["positions"]); self.assertIn("SOL/USDT:USDT", s2["positions"])


if __name__ == "__main__":
    unittest.main()
