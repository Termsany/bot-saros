"""Per-user live-trading scheduler — Phase 2 (2)(3)(4).

Iterates every currently live-enabled user (user_live_activation) who also
has configured keys for their exchange (user_keys_vault), and runs one
trend_daily live cycle per watched symbol for each of them, once per tick.

Three extra responsibilities beyond "call the cycle in a loop":

  (2) Per-user isolation + re-entrancy: one user's exception (bad keys, a
      flaky exchange call, a bug) is caught and recorded, never allowed to
      stop the next user from being processed. A module-level non-blocking
      lock makes a tick a no-op (not a queue, not a crash) if a previous tick
      is still running when it's called again. If there are zero live-enabled
      + keyed users, the tick returns immediately with ZERO exchange calls —
      exchange_factory is never even invoked.

  (3) Restart reconciliation: before any new entry is allowed for a user, any
      symbol with an open position in that user's local state file is
      verified against the exchange via bot._exchange_position_qty (the same
      authoritative read primitive the close path already uses). A mismatch
      (or an inconclusive read) marks state['recovery_required'][symbol] and
      is never auto-resolved — run_trend_daily_live_cycle already refuses new
      entries for a symbol with recovery_required set (see
      user_live_trading.py). Existing exits/close handling are untouched by
      this — they still run through the normal cycle.

  (4) Kill-switch / drawdown polling: on every tick, independent of whether a
      strategy signal fires, each user's own equity is re-checked against
      their own risk ledger's kill-switch/drawdown primitives
      (risk_manager.update_equity_and_check_kill_switch). A trip blocks that
      user's new entries (pre_trade_gate already refuses to reserve risk once
      the kill switch is tripped) but never blocks exits or protective-order
      management, which don't go through pre_trade_gate.

This module never reads ALLOW_LIVE_TRADING and never touches the admin/owner
vault (keys_vault.py) or the global admin risk ledger — only per-user state.
"""
from __future__ import annotations
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional

ROOT = Path(__file__).resolve().parent.parent.parent
for p in (str(ROOT), str(ROOT / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

import bot as botmod  # noqa: E402
from app import risk_manager as riskmgr  # noqa: E402
from app import user_keys_vault as ukv  # noqa: E402
from app import user_live_activation as ula  # noqa: E402
from app import user_live_trading as ult  # noqa: E402
from app.user_exchange_manager import get_user_exchange_instance  # noqa: E402

_TICK_LOCK = threading.Lock()


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def iterate_live_enabled_keyed_users(activation_path) -> list[dict]:
    """Every user with an audited live-enable record AND their own configured
    keys for that exchange, right now. Neither condition alone is enough —
    this mirrors the exact gate run_trend_daily_live_cycle already enforces."""
    out = []
    con = ula._connect(activation_path)
    try:
        rows = con.execute("SELECT * FROM user_live_activation WHERE enabled=1").fetchall()
    finally:
        con.close()
    for row in rows:
        rec = dict(row)
        if ukv.has_live_configured_keys(rec["user_id"], rec["exchange"]):
            out.append(rec)
    return out


def reconcile_user_positions(user_id: str, ex, bot_dir) -> dict:
    """For every symbol this user's local state thinks is open, verify it still
    exists on the exchange via the authoritative close-path primitive. A flat
    or inconclusive exchange read is a disagreement: mark recovery_required
    and leave it for a human to resolve — never auto-delete or guess."""
    state_path = ult.user_state_path(bot_dir, user_id)
    state = ult.load_user_state(state_path)
    findings = {}
    changed = False
    for symbol, pos in list(state.get("positions", {}).items()):
        if (state.get("recovery_required") or {}).get(symbol):
            continue  # already flagged, don't re-derive/clear it here
        try:
            qty = botmod._exchange_position_qty(ex, symbol, side=pos.get("side"), position_idx=pos.get("position_idx"))
        except Exception as e:
            qty = None
            findings[symbol] = f"exchange read failed: {e}"
        if qty is None:
            findings[symbol] = findings.get(symbol, "exchange position read was inconclusive")
        elif qty == 0:
            findings[symbol] = "local state has an open position but exchange is flat"
        else:
            continue  # exchange agrees a position exists — nothing to flag
        state.setdefault("recovery_required", {})[symbol] = {"reason": findings[symbol], "at": _now_iso()}
        changed = True
    if changed:
        ult.save_user_state(state_path, state)
    return findings


def _server_allows_live():
    """The server's own real-money switch and the operator's kill switch bind per-user trading too. A refusal stops
    new entries only: the tick still reconciles, polls each user's kill switch and runs exits."""
    import os
    if os.getenv("ALLOW_LIVE_TRADING", "").strip().lower() != "true":
        return False, "ALLOW_LIVE_TRADING is off"
    d = os.getenv("RAQM_RISK_DIR", "").strip()
    if d:
        try:
            if riskmgr.load_risk_state(Path(d) / "risk_state.json")["kill_switch"].get("tripped"):
                return False, "operator kill switch is tripped"
        except Exception as e:
            return False, f"operator risk ledger unreadable: {e}"
    return True, None


def poll_user_kill_switch(user_id: str, ex, bot_dir) -> tuple[bool, Optional[str]]:
    """Re-checks this user's own equity against their own risk ledger's
    kill-switch/drawdown limits, independent of any strategy signal. A trip
    blocks new entries (via pre_trade_gate) on every subsequent cycle this
    tick and until reset — it never touches exits."""
    risk_path = ult.user_risk_path(bot_dir, user_id)
    equity = botmod._fetch_equity_usdt(ex)
    if equity is None:
        return True, "equity unavailable for kill-switch check — fail closed"
    return riskmgr.update_equity_and_check_kill_switch(risk_path, equity, equity_observed_at=_now_iso())


def run_scheduler_tick(*, bot_dir, activation_path=None, watch_symbols: Iterable[str],
                        analysis_provider: Callable[[str], dict],
                        exchange_factory: Callable[[str, str], object] = get_user_exchange_instance) -> dict:
    """One scheduling tick across every live-enabled + keyed user.

    `analysis_provider(symbol) -> analysis dict` (deterministic in tests/real
    strategy code outside this module). `exchange_factory(user_id, exchange)`
    defaults to the per-user-keys-only ccxt factory; tests inject a fake.
    """
    activation_path = activation_path or (Path(bot_dir) / "user_live_activation.sqlite3")
    if not _TICK_LOCK.acquire(blocking=False):
        return {"skipped": "previous tick still running"}
    try:
        ok, why = _server_allows_live()
        entries_block = None if ok else why
        users = iterate_live_enabled_keyed_users(activation_path)
        if not users:
            return {"users_processed": 0, "results": {}, "errors": {}, "entries_blocked": entries_block}
        results: dict = {}
        errors: dict = {}
        for rec in users:
            user_id, exchange = rec["user_id"], rec["exchange"]
            try:
                ex = exchange_factory(user_id, exchange)
                if ex is None:
                    errors[user_id] = "keys missing or incomplete at build time"
                    continue
                reconcile_user_positions(user_id, ex, bot_dir)
                poll_user_kill_switch(user_id, ex, bot_dir)
                per_symbol = {}
                for symbol in watch_symbols:
                    analysis = analysis_provider(symbol)
                    per_symbol[symbol] = ult.run_trend_daily_live_cycle(
                        user_id=user_id, symbol=symbol, ex=ex, bot_dir=bot_dir,
                        analysis=analysis, activation_path=activation_path, entries_block=entries_block)
                results[user_id] = per_symbol
            except Exception as e:  # one user's failure must never stop the next user
                errors[user_id] = str(e)
                continue
        return {"users_processed": len(users), "results": results, "errors": errors, "entries_blocked": entries_block}
    finally:
        _TICK_LOCK.release()
