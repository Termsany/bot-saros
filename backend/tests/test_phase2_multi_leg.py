import tempfile
import threading
import unittest
from pathlib import Path

from backend.app import risk_manager
from backend.app.multi_leg_execution import MultiLegExecutionEngine


class Phase2ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.risk = Path(self.td.name) / "risk.json"
        self.journal = Path(self.td.name) / "state.json"
        self.blocked = []
        self.engine = MultiLegExecutionEngine(self.journal, risk_manager=risk_manager,
                                              risk_path=self.risk, block=self.blocked.append)

    def tearDown(self):
        self.td.cleanup()

    def legs(self):
        return [
            {"symbol": "AAA/USDT", "side": "long", "risk_usdt": 1, "notional_usdt": 100, "order": 0},
            {"symbol": "BBB/USDT", "side": "short", "risk_usdt": 1, "notional_usdt": 100, "order": 1},
        ]

    def test_basket_is_deterministic_and_journaled(self):
        called = []
        result = self.engine.execute(equity_observed_at=risk_manager._now(), strategy="momentum_ls", intent="entry", legs=self.legs(), equity_usdt=1000,
            execute_leg=lambda leg: (called.append(leg["symbol"]) or {"qty": 1, "price": 10}),
            compensate_leg=lambda leg, fill: {"confirmed": True}, verify_protection=lambda leg, fill: True)
        self.assertTrue(result["ok"])
        self.assertEqual(called, ["AAA/USDT", "BBB/USDT"])
        self.assertEqual(self.engine.pending(), [])

    def test_failed_second_leg_compensates_first(self):
        calls = []
        def execute(leg):
            calls.append(("entry", leg["symbol"]))
            if leg["symbol"] == "BBB/USDT": raise RuntimeError("rejected")
            return {"qty": 1, "price": 10}
        result = self.engine.execute(equity_observed_at=risk_manager._now(), strategy="ratio_trend", intent="entry", legs=self.legs(), equity_usdt=1000,
            execute_leg=execute, compensate_leg=lambda leg, fill: calls.append(("close", leg["symbol"])) or {"confirmed": True},
            verify_protection=lambda leg, fill: True)
        self.assertEqual(result["status"], "compensated")
        self.assertIn(("close", "AAA/USDT"), calls)
        self.assertFalse(self.engine.pending())

    def test_ambiguous_compensation_persists_residual_and_blocks(self):
        def execute(leg):
            if leg["symbol"] == "BBB/USDT": raise RuntimeError("second failed")
            return {"qty": 1, "price": 10}
        result = self.engine.execute(equity_observed_at=risk_manager._now(), strategy="listing_short", intent="entry", legs=self.legs(), equity_usdt=1000,
            execute_leg=execute, compensate_leg=lambda leg, fill: (_ for _ in ()).throw(RuntimeError("timeout")),
            verify_protection=lambda leg, fill: True)
        self.assertEqual(result["status"], "recovery_required")
        self.assertTrue(result["residual"])
        self.assertTrue(self.blocked)
        self.assertTrue(self.engine.pending())

    def test_protection_failure_compensates_filled_legs(self):
        closed = []
        result = self.engine.execute(equity_observed_at=risk_manager._now(), strategy="listing_short", intent="entry", legs=self.legs(), equity_usdt=1000,
            execute_leg=lambda leg: {"qty": 1, "price": 10},
            compensate_leg=lambda leg, fill: closed.append(leg["symbol"]) or {"confirmed": True},
            verify_protection=lambda leg, fill: leg["symbol"] != "BBB/USDT")
        self.assertEqual(result["status"], "compensated")
        self.assertEqual(closed, ["BBB/USDT", "AAA/USDT"])

    def test_restart_recovery_lists_durable_intent(self):
        result = self.engine.execute(equity_observed_at=risk_manager._now(), strategy="momentum_ls", intent="entry", legs=self.legs(), equity_usdt=1000,
            execute_leg=lambda leg: (_ for _ in ()).throw(RuntimeError("ambiguous")),
            compensate_leg=lambda leg, fill: {"confirmed": True}, verify_protection=lambda leg, fill: True)
        self.assertEqual(result["status"], "compensated")
        # A protection failure after a fill creates a pending recovery intent.
        result = self.engine.execute(equity_observed_at=risk_manager._now(), strategy="ratio_trend", intent="entry", legs=self.legs(), equity_usdt=1000,
            execute_leg=lambda leg: {"qty": 1, "price": 10}, compensate_leg=lambda leg, fill: (_ for _ in ()).throw(RuntimeError("unknown")),
            verify_protection=lambda leg, fill: False)
        restarted = MultiLegExecutionEngine(self.journal, risk_manager=risk_manager, risk_path=self.risk)
        self.assertTrue(restarted.pending())

    def test_kill_switch_blocks_basket_before_orders(self):
        risk_manager.trip_kill_switch(self.risk, "operator")
        called = []
        result = self.engine.execute(equity_observed_at=risk_manager._now(), strategy="momentum_ls", intent="entry", legs=self.legs(), equity_usdt=1000,
            execute_leg=lambda leg: called.append(leg) or {"qty": 1}, compensate_leg=lambda l, f: {"confirmed": True},
            verify_protection=lambda l, f: True)
        self.assertEqual(result["status"], "risk_blocked")
        self.assertFalse(called)

    def test_concurrent_basket_reservations_are_atomic(self):
        answers = []
        def worker():
            answers.append(risk_manager.pre_trade_gate_basket(self.risk, strategy="s", legs=self.legs(), equity_usdt=1000, equity_observed_at=risk_manager._now()))
        ts = [threading.Thread(target=worker) for _ in range(2)]
        for t in ts: t.start()
        for t in ts: t.join()
        self.assertEqual(sum(ok for ok, _ in answers), 1)

    def test_completed_cycle_gets_new_identity_for_later_legitimate_cycle(self):
        calls = []
        kwargs = dict(strategy="momentum_ls", intent="same-intent", legs=self.legs(), equity_usdt=1000,
                      equity_observed_at=risk_manager._now(),
                      execute_leg=lambda leg: calls.append(leg["client_order_id"]) or {"qty": 1, "price": 10},
                      compensate_leg=lambda leg, fill: {"confirmed": True}, verify_protection=lambda leg, fill: True)
        first = self.engine.execute(**kwargs)
        second = self.engine.execute(**kwargs)
        self.assertNotEqual(first["execution_id"], second["execution_id"])
        self.assertEqual(len(calls), 2)

    def test_explicit_cycle_token_reuses_inflight_identity(self):
        kwargs = dict(strategy="momentum_ls", intent="retryable", cycle_token="cycle-1", legs=self.legs(), equity_usdt=1000,
                      equity_observed_at=risk_manager._now(),
                      execute_leg=lambda leg: (_ for _ in ()).throw(RuntimeError("ambiguous")) if leg["symbol"] == "BBB/USDT" else {"qty": 1, "price": 10},
                      compensate_leg=lambda leg, fill: (_ for _ in ()).throw(RuntimeError("unknown")), verify_protection=lambda leg, fill: True)
        first = self.engine.execute(**kwargs)
        second = self.engine.execute(**kwargs)
        self.assertEqual(first["execution_id"], second["execution_id"])

    def test_retry_reuses_deterministic_execution_and_does_not_duplicate_orders(self):
        self.test_explicit_cycle_token_reuses_inflight_identity()
    def test_partial_fill_is_not_counted_as_complete(self):
        closed = []
        legs = self.legs(); legs[0]["requested_qty"] = 2
        result = self.engine.execute(equity_observed_at=risk_manager._now(), strategy="partial", intent="entry", legs=legs, equity_usdt=1000,
            execute_leg=lambda leg: {"qty": 1, "price": 10},
            compensate_leg=lambda leg, fill: closed.append(leg["symbol"]) or {"confirmed": True},
            verify_protection=lambda leg, fill: True)
        self.assertEqual(result["status"], "compensated")
        self.assertFalse(self.engine.pending())

    def test_authoritative_position_evidence_rejects_positive_but_partial_leg(self):
        legs = self.legs(); legs[0]["requested_qty"] = 2
        result = self.engine.execute(equity_observed_at=risk_manager._now(), strategy="authoritative", intent="entry", legs=legs, equity_usdt=1000,
            execute_leg=lambda leg: {"qty": 2, "authoritative_qty": 1, "authoritative_fill_qty": 2, "price": 10},
            compensate_leg=lambda leg, fill: {"confirmed": True}, verify_protection=lambda leg, fill: True)
        self.assertEqual(result["status"], "compensated")
        self.assertFalse(self.engine.pending())

    def test_caller_persistence_failure_remains_pending(self):
        result = self.engine.execute(equity_observed_at=risk_manager._now(), strategy="persist", intent="entry", legs=self.legs(), equity_usdt=1000,
            execute_leg=lambda leg: {"qty": 1, "price": 10},
            compensate_leg=lambda leg, fill: {"confirmed": True}, verify_protection=lambda leg, fill: True,
            persist_fills=lambda fills: False)
        self.assertEqual(result["status"], "post_fill_recovery")
        self.assertTrue(self.engine.pending())

    def test_reconcile_invokes_exchange_lookup_and_resolution(self):
        self.engine.execute(equity_observed_at=risk_manager._now(), strategy="restart", intent="entry", legs=self.legs(), equity_usdt=1000,
            execute_leg=lambda leg: {"qty": 1, "price": 10},
            compensate_leg=lambda leg, fill: (_ for _ in ()).throw(RuntimeError("ambiguous")),
            verify_protection=lambda leg, fill: False)
        looked_up = []
        rows = self.engine.reconcile(
            position_lookup=lambda payload: looked_up.append(payload["legs"]) or {"AAA/USDT": 0, "BBB/USDT": 0},
            resolve=lambda item: {"status": "compensated"})
        self.assertTrue(rows)
        self.assertTrue(looked_up)
        self.assertFalse(self.engine.pending())


if __name__ == "__main__":
    unittest.main()
