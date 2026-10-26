"""Central Risk Manager (shared across every Bot Saros strategy/process).

Single source of truth for pre-trade risk checks and the kill switch. Every live
strategy process (bot.py --strategy X --live) reads/writes the same JSON ledger
file so risk is evaluated across ALL strategies together, not per-process.

Concurrency note: this uses a best-effort file lock (atomic rename + short retry),
not a true distributed lock. It is adequate for a handful of poll-interval-driven
processes (seconds between cycles), not for high-frequency concurrent writers. If
more than a few live strategy processes run simultaneously with sub-second write
collisions, upgrade to a real lock (e.g. a tiny SQLite ledger with transactions)
before trusting this for capital protection.

Public API:
    load_risk_state(path) -> dict
    save_risk_state(path, state)
    pre_trade_gate(path, *, strategy, symbol, side, risk_usdt, notional_usdt,
                   equity_usdt, correlation_group=None) -> (allowed: bool, reason: str|None)
    register_open_risk(path, *, strategy, symbol, side, risk_usdt, notional_usdt,
                        correlation_group=None) -> None
    release_open_risk(path, *, strategy, symbol) -> None
    update_equity_and_check_kill_switch(path, equity_usdt) -> (tripped: bool, reason: str|None)
    trip_kill_switch(path, reason) -> None
    reset_kill_switch(path, *, operator) -> None
"""
import contextlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_LIMITS = {
    "risk_per_trade_pct": 0.25,       # max % of equity risked (to stop) on a single new trade
    "max_aggregate_risk_pct": 1.0,    # max % of equity in open-position stop-risk, summed across ALL strategies
    "max_correlated_risk_pct": 1.0,   # max % of equity in same-direction risk within one correlation group
    "max_daily_loss_pct": 1.0,        # daily realized+unrealized loss that trips the kill switch for the day
    "max_drawdown_pct": 5.0,          # drop from the equity high-water-mark that trips the kill switch (manual reset)
    "leverage": 1,
    "margin_mode": "isolated",
}

_LOCK_SUFFIX = ".lock"
_LOCK_TIMEOUT_S = 5.0
_LOCK_RETRY_S = 0.05


@contextlib.contextmanager
def _file_lock(path: Path):
    """Best-effort cross-process mutex: an exclusive-create lock file, retried with
    a timeout, removed in a finally. See module docstring for concurrency limits."""
    lock_path = path.with_suffix(path.suffix + _LOCK_SUFFIX)
    deadline = time.time() + _LOCK_TIMEOUT_S
    fd = None
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            break
        except FileExistsError:
            if time.time() > deadline:
                # Stale lock (a crashed process never released it) or genuine contention;
                # fail closed by raising so the caller treats this as inconclusive, not permissive.
                raise TimeoutError(f"risk ledger lock timeout: {lock_path}")
            time.sleep(_LOCK_RETRY_S)
    try:
        yield
    finally:
        try:
            if fd is not None:
                os.close(fd)
        finally:
            try:
                os.remove(lock_path)
            except OSError:
                pass


def _default_state(limits=None):
    return {
        "limits": dict(limits or DEFAULT_LIMITS),
        "kill_switch": {"tripped": False, "reason": None, "at": None, "by": None},
        "equity_high_water_mark": None,
        "daily": {"date": None, "realized_pnl": 0.0, "start_equity": None},
        "open_risk": {},   # f"{strategy}:{symbol}" -> {strategy, symbol, side, risk_usdt, notional_usdt, correlation_group, at}
    }


def load_risk_state(path) -> dict:
    path = Path(path)
    if not path.exists():
        return _default_state()
    try:
        with _file_lock(path):
            data = json.loads(path.read_text(encoding="utf-8"))
    except (TimeoutError, json.JSONDecodeError, OSError):
        # Fail closed to a state that still carries limits but keeps the kill switch
        # unknown rather than silently permissive; callers must treat read failure as
        # non-authoritative and avoid trading on it.
        raise
    base = _default_state(data.get("limits"))
    base.update({k: v for k, v in data.items() if k != "limits"})
    base["limits"] = {**DEFAULT_LIMITS, **(data.get("limits") or {})}
    return base


def save_risk_state(path, state: dict) -> None:
    path = Path(path)
    with _file_lock(path):
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        tmp.replace(path)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _today():
    return datetime.now(timezone.utc).date().isoformat()


def _open_risk_rows(state):
    return list((state.get("open_risk") or {}).values())


def aggregate_open_risk_pct(state, equity_usdt):
    if not equity_usdt or equity_usdt <= 0:
        return None
    total = sum(float(r.get("risk_usdt", 0) or 0) for r in _open_risk_rows(state))
    return total / float(equity_usdt) * 100.0


def correlated_risk_pct(state, equity_usdt, correlation_group, side):
    """Sum open risk sharing BOTH the correlation group and the same directional side
    (same-side exposure compounds; opposite-side exposure in the same group partially
    hedges and is intentionally excluded from this figure)."""
    if not equity_usdt or equity_usdt <= 0 or not correlation_group:
        return None
    total = sum(
        float(r.get("risk_usdt", 0) or 0)
        for r in _open_risk_rows(state)
        if r.get("correlation_group") == correlation_group and r.get("side") == side
    )
    return total / float(equity_usdt) * 100.0


def _conflicting_position(state, symbol, side):
    for r in _open_risk_rows(state):
        if r.get("symbol") == symbol and r.get("side") and r.get("side") != side:
            return r
    return None


def update_equity_and_check_kill_switch(path, equity_usdt):
    """Update the high-water-mark and daily baseline, then evaluate drawdown and daily-loss
    limits. Trips the kill switch (persisted) on breach; does not auto-reset on recovery —
    a human must call reset_kill_switch(). Returns (tripped, reason)."""
    path = Path(path)
    state = load_risk_state(path)
    limits = state["limits"]
    ks = state["kill_switch"]
    if ks.get("tripped"):
        return True, ks.get("reason")
    if equity_usdt is None or equity_usdt <= 0:
        return False, None
    hwm = state.get("equity_high_water_mark")
    if hwm is None or equity_usdt > hwm:
        state["equity_high_water_mark"] = equity_usdt
        hwm = equity_usdt
    today = _today()
    daily = state.setdefault("daily", {"date": None, "realized_pnl": 0.0, "start_equity": None})
    if daily.get("date") != today:
        daily["date"] = today
        daily["start_equity"] = equity_usdt
        daily["realized_pnl"] = 0.0
    reason = None
    if hwm and hwm > 0:
        drawdown_pct = (hwm - equity_usdt) / hwm * 100.0
        if drawdown_pct >= float(limits.get("max_drawdown_pct", DEFAULT_LIMITS["max_drawdown_pct"])):
            reason = f"portfolio drawdown {drawdown_pct:.2f}% >= limit {limits['max_drawdown_pct']}% (HWM {hwm:.2f} -> {equity_usdt:.2f})"
    if reason is None and daily.get("start_equity"):
        day_loss_pct = (daily["start_equity"] - equity_usdt) / daily["start_equity"] * 100.0
        if day_loss_pct >= float(limits.get("max_daily_loss_pct", DEFAULT_LIMITS["max_daily_loss_pct"])):
            reason = f"daily loss {day_loss_pct:.2f}% >= limit {limits['max_daily_loss_pct']}% (start {daily['start_equity']:.2f} -> {equity_usdt:.2f})"
    if reason:
        state["kill_switch"] = {"tripped": True, "reason": reason, "at": _now(), "by": "risk_manager"}
    save_risk_state(path, state)
    return (reason is not None), reason


def trip_kill_switch(path, reason, *, by="manual"):
    path = Path(path)
    state = load_risk_state(path)
    state["kill_switch"] = {"tripped": True, "reason": str(reason), "at": _now(), "by": by}
    save_risk_state(path, state)


def reset_kill_switch(path, *, operator):
    """Explicit human action only; never called automatically by trading code."""
    path = Path(path)
    state = load_risk_state(path)
    state["kill_switch"] = {"tripped": False, "reason": None, "at": _now(), "by": f"reset:{operator}"}
    save_risk_state(path, state)


def pre_trade_gate(path, *, strategy, symbol, side, risk_usdt, notional_usdt,
                    equity_usdt, correlation_group=None, allow_strategy_conflicts=False):
    """Mandatory check before ANY live order is submitted, by ANY strategy. Fails closed:
    missing/invalid equity, an unreadable ledger, or any lock timeout blocks the trade
    rather than permitting it. Returns (allowed, reason)."""
    path = Path(path)
    try:
        state = load_risk_state(path)
    except Exception as exc:
        return False, f"risk ledger unavailable: {exc}"
    ks = state.get("kill_switch") or {}
    if ks.get("tripped"):
        return False, f"kill switch is tripped: {ks.get('reason')}"
    if equity_usdt is None or equity_usdt <= 0:
        return False, "equity unavailable; refusing to size risk against an unknown account value"
    if risk_usdt is None or risk_usdt < 0:
        return False, "invalid risk amount"
    limits = state["limits"]
    per_trade_pct = float(risk_usdt) / float(equity_usdt) * 100.0
    cap = float(limits.get("risk_per_trade_pct", DEFAULT_LIMITS["risk_per_trade_pct"]))
    if per_trade_pct > cap + 1e-9:
        return False, f"per-trade risk {per_trade_pct:.3f}% exceeds limit {cap}%"
    existing_agg = aggregate_open_risk_pct(state, equity_usdt) or 0.0
    agg_cap = float(limits.get("max_aggregate_risk_pct", DEFAULT_LIMITS["max_aggregate_risk_pct"]))
    if existing_agg + per_trade_pct > agg_cap + 1e-9:
        return False, f"aggregate open risk {existing_agg:.3f}% + new {per_trade_pct:.3f}% would exceed limit {agg_cap}%"
    if correlation_group:
        existing_corr = correlated_risk_pct(state, equity_usdt, correlation_group, side) or 0.0
        corr_cap = float(limits.get("max_correlated_risk_pct", DEFAULT_LIMITS["max_correlated_risk_pct"]))
        if existing_corr + per_trade_pct > corr_cap + 1e-9:
            return False, (f"correlated risk in group '{correlation_group}' {existing_corr:.3f}% + new "
                            f"{per_trade_pct:.3f}% would exceed limit {corr_cap}%")
    if not allow_strategy_conflicts:
        conflict = _conflicting_position(state, symbol, side)
        if conflict:
            return False, (f"strategy conflict: {conflict.get('strategy')} already holds {symbol} "
                            f"{conflict.get('side')}, refusing opposite-side {side} from {strategy}")
    return True, None


def register_open_risk(path, *, strategy, symbol, side, risk_usdt, notional_usdt, correlation_group=None):
    path = Path(path)
    state = load_risk_state(path)
    key = f"{strategy}:{symbol}"
    state.setdefault("open_risk", {})[key] = {
        "strategy": strategy, "symbol": symbol, "side": side,
        "risk_usdt": float(risk_usdt or 0), "notional_usdt": float(notional_usdt or 0),
        "correlation_group": correlation_group, "at": _now(),
    }
    save_risk_state(path, state)


def release_open_risk(path, *, strategy, symbol):
    path = Path(path)
    state = load_risk_state(path)
    state.setdefault("open_risk", {}).pop(f"{strategy}:{symbol}", None)
    save_risk_state(path, state)


def record_realized_pnl(path, pnl_usdt):
    """Accumulate today's realized PnL for the daily-loss check (independent of the
    drawdown/equity check, which reads actual exchange equity when available)."""
    path = Path(path)
    state = load_risk_state(path)
    today = _today()
    daily = state.setdefault("daily", {"date": None, "realized_pnl": 0.0, "start_equity": None})
    if daily.get("date") != today:
        daily["date"] = today
        daily["realized_pnl"] = 0.0
    daily["realized_pnl"] = float(daily.get("realized_pnl", 0) or 0) + float(pnl_usdt or 0)
    save_risk_state(path, state)
