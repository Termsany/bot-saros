"""Offline/read-only Testnet readiness checks; never submits an order."""
from __future__ import annotations
import math
import os

ALL_STRATEGIES = (
    "trend_daily", "wave_flats", "listing_short", "momentum_ls", "ratio_trend",
    "vol_breakout", "rsi2_pullback", "trend_breakout", "default",
)


def check_testnet_readiness(exchange, *, strategies, risk_state_loader, environment=None):
    """Return structured readiness evidence without touching order endpoints."""
    checks = {}
    env = environment or os.getenv("BINANCE_ENV", "")
    checks["testnet_environment"] = env == "testnet"
    checks["live_locked"] = os.getenv("ALLOW_LIVE_TRADING", "").strip().lower() != "true"
    selected = list(strategies or [])
    checks["strategies_declared"] = bool(selected) and all(s in ALL_STRATEGIES for s in selected)
    required_methods = ("fetch_balance", "fetch_positions", "fetch_order", "fetch_open_orders", "create_order", "cancel_order")
    checks["exchange_capabilities"] = all(callable(getattr(exchange, name, None)) for name in required_methods)
    try:
        markets = exchange.load_markets()
        contracts = [m for m in markets.values() if m.get("contract")]
        checks["linear_contract_metadata"] = bool(contracts) and all(
            m.get("linear") is True and not m.get("inverse") and math.isfinite(float(m.get("contractSize"))) and float(m.get("contractSize")) > 0
            for m in contracts
        )
    except Exception:
        checks["linear_contract_metadata"] = False
    try:
        state = risk_state_loader()
        checks["risk_ledger_readable"] = isinstance(state, dict) and not (state.get("kill_switch") or {}).get("tripped")
    except Exception:
        checks["risk_ledger_readable"] = False
    return {"ready": all(checks.values()), "checks": checks, "orders_submitted": 0}
