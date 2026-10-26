"""Central Risk Manager: pre-trade gate, aggregate/correlated exposure, kill switch.

Behavioral tests against the real module functions (no source inspection) — per-trade
cap, aggregate cap across strategies, correlated-exposure cap, strategy-conflict
rejection, missing-equity fail-closed, daily-loss and drawdown kill-switch tripping,
manual-only reset, and persistence across process restarts (a fresh load from disk)."""
import tempfile
import unittest
from pathlib import Path

from backend.app import risk_manager as rm


class RiskManagerTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.path = Path(self.td.name) / "risk_state.json"

    def tearDown(self):
        self.td.cleanup()

    def test_per_trade_risk_cap_blocks_oversized_trade(self):
        allowed, reason = rm.pre_trade_gate(self.path, strategy="trend_daily", symbol="BTC/USDT",
            side="long", risk_usdt=50, notional_usdt=1000, equity_usdt=1000)   # 5% > default 0.25%
        self.assertFalse(allowed); self.assertIn("per-trade risk", reason)

    def test_per_trade_risk_within_cap_is_allowed(self):
        allowed, reason = rm.pre_trade_gate(self.path, strategy="trend_daily", symbol="BTC/USDT",
            side="long", risk_usdt=2.0, notional_usdt=1000, equity_usdt=1000)   # 0.2% < 0.25%
        self.assertTrue(allowed, reason)

    def test_missing_equity_fails_closed(self):
        allowed, reason = rm.pre_trade_gate(self.path, strategy="trend_daily", symbol="BTC/USDT",
            side="long", risk_usdt=1.0, notional_usdt=100, equity_usdt=None)
        self.assertFalse(allowed); self.assertIn("equity", reason)

    def test_missing_stop_price_risk_is_rejected(self):
        risk = rm._default_state  # sanity import check
        self.assertTrue(callable(risk))
        allowed, reason = rm.pre_trade_gate(self.path, strategy="trend_daily", symbol="BTC/USDT",
            side="long", risk_usdt=None, notional_usdt=100, equity_usdt=1000)
        self.assertFalse(allowed); self.assertIn("invalid risk amount", reason)

    def test_aggregate_risk_cap_across_strategies(self):
        # trend_daily uses up the whole 1% aggregate cap ...
        rm.register_open_risk(self.path, strategy="trend_daily", symbol="BTC/USDT", side="long",
            risk_usdt=10.0, notional_usdt=1000, correlation_group="majors")   # 1.0% of 1000 equity
        # ... so a second strategy's new trade must be rejected even though ITS own per-trade size is fine.
        allowed, reason = rm.pre_trade_gate(self.path, strategy="rsi2_pullback", symbol="LINK/USDT",
            side="long", risk_usdt=1.0, notional_usdt=100, equity_usdt=1000, correlation_group="alts")
        self.assertFalse(allowed); self.assertIn("aggregate open risk", reason)

    def test_correlated_risk_cap_within_group(self):
        # Correlated cap (0.5%) stricter than the aggregate cap (5%) for this test, so the
        # rejection reason is unambiguously the correlation check, not the aggregate one.
        rm.save_risk_state(self.path, rm._default_state({
            "risk_per_trade_pct": 100.0, "max_aggregate_risk_pct": 5.0, "max_correlated_risk_pct": 0.5,
            "max_daily_loss_pct": 100.0, "max_drawdown_pct": 100.0,
        }))
        rm.register_open_risk(self.path, strategy="trend_daily", symbol="BTC/USDT", side="long",
            risk_usdt=4.0, notional_usdt=900, correlation_group="majors")   # 0.4% of 1000 equity
        # Same group ("majors"), same side ("long") — should be blocked by the correlated cap
        # even though aggregate (5%) alone still has plenty of room.
        allowed, reason = rm.pre_trade_gate(self.path, strategy="momentum_ls", symbol="ETH/USDT",
            side="long", risk_usdt=2.0, notional_usdt=200, equity_usdt=1000, correlation_group="majors")
        self.assertFalse(allowed); self.assertIn("correlated risk", reason)

    def test_opposite_side_same_group_does_not_trip_correlated_cap(self):
        rm.register_open_risk(self.path, strategy="trend_daily", symbol="BTC/USDT", side="long",
            risk_usdt=9.0, notional_usdt=900, correlation_group="majors")
        allowed, reason = rm.pre_trade_gate(self.path, strategy="momentum_ls", symbol="ETH/USDT",
            side="short", risk_usdt=0.5, notional_usdt=50, equity_usdt=1000, correlation_group="majors")
        self.assertTrue(allowed, reason)

    def test_strategy_conflict_opposite_side_same_symbol_is_blocked(self):
        rm.register_open_risk(self.path, strategy="trend_daily", symbol="SOL/USDT", side="long",
            risk_usdt=1.0, notional_usdt=100, correlation_group="alts")
        allowed, reason = rm.pre_trade_gate(self.path, strategy="rsi2_pullback", symbol="SOL/USDT",
            side="short", risk_usdt=0.5, notional_usdt=50, equity_usdt=1000, correlation_group="alts")
        self.assertFalse(allowed); self.assertIn("strategy conflict", reason)

    def test_strategy_conflict_can_be_explicitly_allowed(self):
        rm.register_open_risk(self.path, strategy="trend_daily", symbol="SOL/USDT", side="long",
            risk_usdt=1.0, notional_usdt=100, correlation_group="alts")
        allowed, reason = rm.pre_trade_gate(self.path, strategy="rsi2_pullback", symbol="SOL/USDT",
            side="short", risk_usdt=0.5, notional_usdt=50, equity_usdt=1000, correlation_group="alts",
            allow_strategy_conflicts=True)
        self.assertTrue(allowed, reason)

    def test_release_frees_aggregate_room(self):
        rm.register_open_risk(self.path, strategy="trend_daily", symbol="BTC/USDT", side="long",
            risk_usdt=10.0, notional_usdt=1000, correlation_group="majors")
        allowed, _ = rm.pre_trade_gate(self.path, strategy="rsi2_pullback", symbol="LINK/USDT",
            side="long", risk_usdt=1.0, notional_usdt=100, equity_usdt=1000, correlation_group="alts")
        self.assertFalse(allowed)
        rm.release_open_risk(self.path, strategy="trend_daily", symbol="BTC/USDT")
        allowed, reason = rm.pre_trade_gate(self.path, strategy="rsi2_pullback", symbol="LINK/USDT",
            side="long", risk_usdt=1.0, notional_usdt=100, equity_usdt=1000, correlation_group="alts")
        self.assertTrue(allowed, reason)

    def test_drawdown_trips_kill_switch_and_blocks_new_trades(self):
        tripped, reason = rm.update_equity_and_check_kill_switch(self.path, 1000.0)
        self.assertFalse(tripped)
        # 5% default drawdown limit; drop equity 6% from the high-water-mark.
        tripped, reason = rm.update_equity_and_check_kill_switch(self.path, 940.0)
        self.assertTrue(tripped); self.assertIn("drawdown", reason)
        allowed, gate_reason = rm.pre_trade_gate(self.path, strategy="trend_daily", symbol="BTC/USDT",
            side="long", risk_usdt=0.1, notional_usdt=10, equity_usdt=940.0)
        self.assertFalse(allowed); self.assertIn("kill switch", gate_reason)

    def test_daily_loss_trips_kill_switch(self):
        rm.update_equity_and_check_kill_switch(self.path, 1000.0)   # sets today's start_equity
        tripped, reason = rm.update_equity_and_check_kill_switch(self.path, 985.0)   # -1.5% > 1% default
        self.assertTrue(tripped); self.assertIn("daily loss", reason)

    def test_kill_switch_does_not_auto_reset_on_recovery(self):
        rm.update_equity_and_check_kill_switch(self.path, 1000.0)
        rm.update_equity_and_check_kill_switch(self.path, 940.0)   # trips drawdown
        tripped, _ = rm.update_equity_and_check_kill_switch(self.path, 1000.0)   # equity recovers
        self.assertTrue(tripped)   # still tripped — only a human can clear it

    def test_manual_reset_clears_kill_switch(self):
        rm.trip_kill_switch(self.path, "manual test trip")
        state = rm.load_risk_state(self.path)
        self.assertTrue(state["kill_switch"]["tripped"])
        rm.reset_kill_switch(self.path, operator="ops-alice")
        state = rm.load_risk_state(self.path)
        self.assertFalse(state["kill_switch"]["tripped"])
        self.assertIn("ops-alice", state["kill_switch"]["by"])

    def test_tripped_kill_switch_blocks_even_a_tiny_safe_trade(self):
        rm.trip_kill_switch(self.path, "operator pulled the switch")
        allowed, reason = rm.pre_trade_gate(self.path, strategy="trend_daily", symbol="BTC/USDT",
            side="long", risk_usdt=0.01, notional_usdt=1, equity_usdt=1_000_000)
        self.assertFalse(allowed); self.assertIn("kill switch", reason)

    def test_state_persists_across_a_fresh_load_restart_simulation(self):
        rm.register_open_risk(self.path, strategy="trend_daily", symbol="BTC/USDT", side="long",
            risk_usdt=5.0, notional_usdt=500, correlation_group="majors")
        rm.trip_kill_switch(self.path, "pre-restart trip")
        # Simulate a process restart: nothing but a fresh load from disk.
        reloaded = rm.load_risk_state(self.path)
        self.assertTrue(reloaded["kill_switch"]["tripped"])
        self.assertIn("trend_daily:BTC/USDT", reloaded["open_risk"])

    def test_unreadable_ledger_fails_closed_not_permissive(self):
        self.path.write_text("{not valid json", encoding="utf-8")
        allowed, reason = rm.pre_trade_gate(self.path, strategy="trend_daily", symbol="BTC/USDT",
            side="long", risk_usdt=0.1, notional_usdt=10, equity_usdt=1000)
        self.assertFalse(allowed); self.assertIn("unavailable", reason)


if __name__ == "__main__":
    unittest.main()
