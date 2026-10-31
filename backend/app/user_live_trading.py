"""
Per-user LIVE execution — Phase B.

Runs ONE strategy (trend_daily, single-leg) live for ONE user at a time, using
that user's own keys/consent record, with a per-user state file and a
per-user risk-ledger partition (a separate SQLite file per user_id, reusing
risk_manager.py's transactional ledger unmodified). It does NOT touch
bot.py's module-level globals (CONFIG / STATE_PATH / RISK_PATH) or the
existing admin dashboard's bot_loop() in main.py, so the single global paper
loop for other users/strategies is completely unaffected by this module.

Execution-safety protections are reused from the already-tested, global-state
-free primitives rather than re-implemented:
  - contract-size verification: bot._contract_meta / execution_safety.linear_contracts_from_margin
  - fill verification: execution_safety.normalize_filled_contracts
  - protective order placement + verification: oco.place_oco_orders / cancel_oco_orders
  - authoritative close + fail-closed accounting: bot._exchange_position_qty /
    bot._authoritative_close_fill + execution_safety.futures_net_pnl (the close
    order itself is routed through this module's own _close_user_market_order
    with an explicit quantity, instead of bot.place_order, because place_order
    reads bot.CONFIG — a shared global this module must never touch)
  - CRM risk reservation: risk_manager.pre_trade_gate / register_open_risk / release_open_risk

The live order path only ever fires for a user who is (a) recorded as
live-enabled with an audited consent (user_live_activation.is_user_live_enabled)
and (b) still has their own configured keys for that exchange
(user_keys_vault.has_live_configured_keys) at the moment of the cycle.

Follow-up scope: only trend_daily is wired end to end here. wave_flats,
momentum_ls, listing_short, ratio_trend, and the LLM-authored strategies are
NOT yet wired to per-user live execution — see remaining_scope in the PR/task
summary.
"""
from __future__ import annotations
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
for p in (str(ROOT), str(ROOT / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

import bot as botmod  # noqa: E402  (module-level globals of bot.py are NEVER mutated by this file)
from app import risk_manager as riskmgr  # noqa: E402
from app import oco as oco_mod  # noqa: E402
from app import user_keys_vault as ukv  # noqa: E402
from app import user_live_activation as ula  # noqa: E402
from app.execution_safety import (  # noqa: E402
    linear_contracts_from_margin,
    normalize_filled_contracts,
    futures_net_pnl,
)

STRATEGY = "trend_daily"
STOP_SHARE = 0.8  # same stop model as strategies_trend.py / bot.py's trend_daily (no shared mutable global)

# Sane absolute bounds for percent-of-equity sizing — a user with $3 of equity must
# never try to place a sub-exchange-minimum order, and a user with $5M of equity must
# never have a single cycle size a position larger than this ceiling by formula alone.
MIN_MARGIN_USDT_FLOOR = 10.0
MAX_MARGIN_USDT_CEILING = 5000.0


def percent_equity_margin_usdt(equity_usdt, risk_per_trade_pct, *,
                                floor_usdt: float = MIN_MARGIN_USDT_FLOOR,
                                ceiling_usdt: float = MAX_MARGIN_USDT_CEILING) -> float:
    """Position margin sized as a percent of the user's own live equity (the same
    consented risk_per_trade_pct already recorded in their user_live_activation
    record), clamped to a sane absolute floor/ceiling. Fails closed to the floor
    (never to zero/negative) on bad inputs so callers still get a usable size — the
    exchange-minimum-notional check downstream is what actually blocks an entry."""
    try:
        equity_usdt = float(equity_usdt)
        risk_per_trade_pct = float(risk_per_trade_pct)
    except (TypeError, ValueError):
        return floor_usdt
    if equity_usdt <= 0 or risk_per_trade_pct <= 0:
        return floor_usdt
    raw = equity_usdt * (risk_per_trade_pct / 100.0)
    return max(floor_usdt, min(ceiling_usdt, raw))


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def user_live_dir(bot_dir) -> Path:
    d = Path(bot_dir) / "user_live"
    d.mkdir(parents=True, exist_ok=True)
    return d


def user_state_path(bot_dir, user_id: str) -> Path:
    return user_live_dir(bot_dir) / f"state_{user_id}.json"


def user_risk_path(bot_dir, user_id: str) -> Path:
    """Base path; risk_manager appends .sqlite3 — one ledger file per user_id,
    so one user's reservations can never be seen or consumed by another user's gate."""
    return user_live_dir(bot_dir) / f"risk_{user_id}"


def default_user_state():
    return {"positions": {}, "history": [], "trend_seen": {}, "last_trade": {}}


def load_user_state(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        return default_user_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_user_state()
    state = default_user_state()
    state.update(data)
    return state


def save_user_state(path: Path, state: dict):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _ensure_user_risk_limits(risk_path, *, leverage, risk_per_trade_pct, max_aggregate_risk_pct):
    """Initialize this user's risk ledger with their own (consented, bounded) limits
    the first time it's touched. Existing reservations/kill-switch state are preserved."""
    riskmgr.update_limits(risk_path, {
        "leverage": int(leverage),
        "risk_per_trade_pct": float(risk_per_trade_pct),
        "max_aggregate_risk_pct": float(max_aggregate_risk_pct),
    })
    return riskmgr.load_risk_state(risk_path)


def _ensure_futures_setup_for_user(ex, symbol, leverage, margin_type="ISOLATED"):
    """Per-user equivalent of bot.ensure_futures_setup with an explicit leverage
    param instead of reading bot.CONFIG — avoids any shared-global mutation."""
    def _already(e):
        m = str(e).lower()
        return any(k in m for k in ("no need to change", "-4046", "-4059", "not modified", "110026", "110043", "110025", "already"))
    for what, call in ((f"set_leverage({leverage},{symbol})", lambda: ex.set_leverage(leverage, symbol)),
                       (f"set_margin_mode({margin_type},{symbol})", lambda: ex.set_margin_mode(margin_type, symbol)),
                       (f"set_position_mode(one-way,{symbol})", lambda: ex.set_position_mode(False))):
        try:
            call()
        except Exception as e:
            if not _already(e):
                raise RuntimeError(f"{what} failed: {e}") from e


def _close_user_market_order(ex, symbol, side, qty, client_order_id=None):
    """Closes an exact, already-known quantity (reduceOnly) — no re-sizing, no bot.CONFIG."""
    cid = client_order_id or f"raqm-u-{uuid.uuid4().hex[:12]}"[:36]
    params = {"reduceOnly": True, "clientOrderId": cid}
    close_side = "sell" if side == "long" else "buy"
    order = ex.create_order(symbol, "market", close_side, qty, None, params)
    fq = normalize_filled_contracts(order)
    ap = float(order.get("average") or order.get("price") or 0)
    return {"id": str(order.get("id", "")), "qty": fq, "price": ap, "raw": order}


def _close_user_position(ex, symbol, pos, price):
    """Per-user equivalent of bot.close_live_position: authoritative exchange
    quantity before closing, authoritative flat read-back after, and protective
    orders cancelled — all via the same global-state-free primitives bot.py
    uses, with the closing order routed through _close_user_market_order
    (explicit qty, no bot.CONFIG) instead of bot.place_order."""
    side = pos.get("side", "long")
    exchange_qty = botmod._exchange_position_qty(ex, symbol, side=side, position_idx=pos.get("position_idx"))
    if exchange_qty is None:
        return {"price": None, "qty": 0.0, "contract_size": None, "accounting_verified": False,
                "recovery_required": True, "error": f"cannot confirm current exchange position for {symbol}"}
    if exchange_qty == 0:
        evidence = botmod._authoritative_close_fill(ex, symbol, pos)
        if evidence is None:
            return {"price": None, "qty": 0.0, "contract_size": None, "accounting_verified": False,
                    "recovery_required": True, "error": f"exchange is flat but authoritative close fill is missing for {symbol}"}
        return {"price": evidence["price"], "qty": evidence["qty"], "contract_size": pos.get("contract_size"),
                "accounting_verified": True, "recovery_required": False, "error": None}
    try:
        res = _close_user_market_order(ex, symbol, side, exchange_qty)
    except Exception as e:
        return {"price": None, "qty": 0.0, "contract_size": None, "accounting_verified": False,
                "recovery_required": True, "error": str(e)}
    if res["qty"] <= 0 or res["qty"] + 1e-9 < exchange_qty:
        return {"price": None, "qty": 0.0, "contract_size": None, "accounting_verified": False,
                "recovery_required": True, "error": "close fill is partial or unverified; recovery required"}
    remaining = botmod._exchange_position_qty(ex, symbol, side=side, position_idx=pos.get("position_idx"))
    if remaining is None or remaining != 0:
        return {"price": None, "qty": 0.0, "contract_size": None, "accounting_verified": False,
                "recovery_required": True, "error": f"close accepted but flat state is unconfirmed for {symbol}; remaining={remaining}"}
    ids = pos.get("oco_ids") or {}
    if ids.get("pos_id") or ids.get("sl") or ids.get("tp"):
        try:
            oco_mod.cancel_oco_orders(ex, symbol, pos_id=ids.get("pos_id"), sl_id=ids.get("sl"), tp_id=ids.get("tp"))
        except Exception:
            pass
    return {"price": res["price"], "qty": res["qty"], "contract_size": pos.get("contract_size"),
            "accounting_verified": True, "recovery_required": False, "error": None}


def _place_user_market_order(ex, symbol, side, margin_usdt, leverage, price, client_order_id=None):
    """Per-user equivalent of bot.place_order's live branch: same contract-size
    verification (bot._contract_meta / linear_contracts_from_margin) and fill
    verification (normalize_filled_contracts), but leverage is an explicit
    per-user parameter instead of bot.CONFIG — never touches bot.py's globals."""
    meta = botmod._contract_meta(ex, symbol)
    notional = margin_usdt * leverage
    qty = linear_contracts_from_margin(margin_usdt, leverage, price, meta["contract_size"])
    try:
        qty = float(ex.amount_to_precision(symbol, qty))
    except Exception:
        qty = round(qty, 6)
    cid = client_order_id or f"raqm-u-{uuid.uuid4().hex[:12]}"[:36]
    if not side.startswith("close"):
        _ensure_futures_setup_for_user(ex, symbol, leverage)
    params = {"reduceOnly": side.startswith("close"), "clientOrderId": cid}
    ccxt_side = "buy" if side in ("long", "close_short") else "sell"
    order = ex.create_order(symbol, "market", ccxt_side, qty, None, params)
    fq = normalize_filled_contracts(order)
    ap = float(order.get("average", price) or order.get("price", price) or price)
    return {"id": str(order.get("id", "")), "qty": fq, "price": ap, "notional": notional,
            "leverage": leverage, "contract_size": meta["contract_size"], "contract_size_verified": True,
            "clientOrderId": cid}


def run_trend_daily_live_cycle(*, user_id: str, symbol: str, ex, bot_dir, analysis: dict,
                                activation_path=None, margin_usdt: "float | None" = None, entries_block: "str | None" = None):
    """One live cycle of the single-leg trend_daily strategy for exactly one user.

    `analysis` is the same shape bot.analyze()/strategies_trend produces:
    {"price": float, "trend": {"on": bool, "ts": int, "size": float}, ...}.
    `entries_block` (the server's live switch off, the operator's kill switch) refuses new entries only: an open
    position still exits on its signal. Returns a dict describing what happened (fired/action/reason).
    """
    activation_path = activation_path or (Path(bot_dir) / "user_live_activation.sqlite3")
    rec = ula.get_user_live_record(activation_path, user_id=user_id)
    if not rec or not rec["enabled"]:
        return {"fired": False, "reason": "not enabled"}
    exchange_name = rec["exchange"]
    if not ukv.has_live_configured_keys(user_id, exchange_name):
        return {"fired": False, "reason": f"keys missing or incomplete for {exchange_name}"}

    leverage = int(rec["leverage"])
    risk_per_trade_pct = float(rec["risk_per_trade_pct"])
    max_aggregate_risk_pct = float(rec["max_aggregate_risk_pct"])
    risk_path = user_risk_path(bot_dir, user_id)
    _ensure_user_risk_limits(risk_path, leverage=leverage, risk_per_trade_pct=risk_per_trade_pct,
                             max_aggregate_risk_pct=max_aggregate_risk_pct)
    state_path = user_state_path(bot_dir, user_id)
    state = load_user_state(state_path)

    sig = analysis.get("trend")
    price = analysis.get("price")
    if not sig:
        return {"fired": False, "reason": "no trend signal"}

    if symbol in state["positions"]:
        if sig.get("on"):
            return {"fired": False, "reason": "trend still on, holding"}
        return _exit_position(user_id, symbol, ex, bot_dir, state, state_path, risk_path, price)

    # Restart reconciliation: a disagreement between exchange and local state for this
    # symbol is never auto-resolved — it blocks new entries until a human clears it.
    if (state.get("recovery_required") or {}).get(symbol):
        return {"fired": False, "reason": f"recovery_required for {symbol} — blocked pending reconciliation"}

    if entries_block:
        return {"fired": False, "reason": f"no new entries — {entries_block}"}

    if not sig.get("on"):
        return {"fired": False, "reason": "no entry signal"}
    seen = state.setdefault("trend_seen", {})
    if seen.get(symbol) == sig.get("ts"):
        return {"fired": False, "reason": "already acted on this signal"}

    equity, equity_at = botmod._equity_now(ex)
    if equity is None:
        return {"fired": False, "reason": "equity unavailable — fail closed, no entry"}
    if margin_usdt is None:
        margin_usdt = percent_equity_margin_usdt(equity, risk_per_trade_pct)
    try:
        min_cost = float(((ex.market(symbol).get("limits") or {}).get("cost") or {}).get("min") or 5)
    except Exception:
        min_cost = 5.0
    if margin_usdt * leverage < min_cost * 1.05:
        seen[symbol] = sig.get("ts"); save_user_state(state_path, state)
        return {"fired": False, "reason": f"order size {margin_usdt * leverage} below exchange minimum {min_cost}"}
    try:
        bal = ex.fetch_balance()
        free = float((bal.get("USDT") or {}).get("free") or (bal.get("free") or {}).get("USDT") or 0)
    except Exception as e:
        return {"fired": False, "reason": f"balance check failed: {e}"}
    if free < margin_usdt * 1.02:
        return {"fired": False, "reason": f"balance {free} insufficient for margin {margin_usdt}"}

    sl_estimate = price * (1 - STOP_SHARE / leverage)
    risk_usdt = botmod._estimate_trade_risk_usdt(margin_usdt, leverage, price, sl_estimate)
    allowed, reason = riskmgr.pre_trade_gate(
        risk_path, strategy=STRATEGY, symbol=symbol, side="long",
        risk_usdt=risk_usdt, notional_usdt=margin_usdt * leverage, equity_usdt=equity,
        equity_observed_at=equity_at)
    if not allowed:
        return {"fired": False, "reason": f"risk gate: {reason}"}

    seen[symbol] = sig.get("ts"); save_user_state(state_path, state)
    cid = "raqm-u-" + uuid.uuid5(uuid.NAMESPACE_URL, f"{user_id}|trend_daily|{symbol}|long").hex[:27]
    try:
        res = _place_user_market_order(ex, symbol, "long", margin_usdt, leverage, price, client_order_id=cid)
    except Exception as e:
        riskmgr.mark_reservation_recovery(risk_path, strategy=STRATEGY, symbol=symbol, reason=f"entry outcome unknown: {e}")
        return {"fired": True, "action": "entry_failed_recovery_required", "error": str(e)}

    sl = res["price"] * (1 - STOP_SHARE / leverage)
    pos = {"side": "long", "entry": res["price"], "qty": res["qty"], "contract_size": res["contract_size"],
           "contract_size_verified": res["contract_size_verified"], "leverage": leverage,
           "time": _now_iso(), "sl": sl, "clientOrderId": cid, "strategy": STRATEGY}
    try:
        oco = oco_mod.place_oco_orders(ex, symbol, "long", res["qty"], sl, None, paper=False, pos_id=cid)
    except Exception as e:
        oco = {"sl_error": str(e), "protection_missing": True}

    if oco.get("protection_missing"):
        close_res = _close_user_position(ex, symbol, pos, price)
        if close_res.get("accounting_verified", True) is False and close_res.get("qty", 0) == 0 and close_res.get("recovery_required"):
            state.setdefault("recovery_required", {})[symbol] = {"reason": f"no stop and close failed: {close_res.get('error')}", "at": _now_iso()}
            pos["unprotected"] = True
            state["positions"][symbol] = pos
            save_user_state(state_path, state)
            return {"fired": True, "action": "enter", "protection_missing": True, "close_failed": True}
        pnl = futures_net_pnl(pos["entry"], close_res["price"], close_res["qty"], res["contract_size"], "long",
                               fee_rate=0.0004, funding_pnl=0.0)
        state["history"].append({"symbol": symbol, "side": "long", "entry": pos["entry"], "exit": close_res["price"],
                                  "qty": close_res["qty"], "pnl": pnl, "reason": "protective stop rejected — closed at once",
                                  "time": _now_iso()})
        riskmgr.rollback_reservation(risk_path, strategy=STRATEGY, symbol=symbol)
        save_user_state(state_path, state)
        return {"fired": True, "action": "enter", "protection_missing": True, "closed_immediately": True, "pnl": pnl}

    riskmgr.register_open_risk(risk_path, strategy=STRATEGY, symbol=symbol, side="long",
                                risk_usdt=risk_usdt or 0, notional_usdt=margin_usdt * leverage)
    state["positions"][symbol] = pos
    save_user_state(state_path, state)
    return {"fired": True, "action": "enter", "entry": pos["entry"], "qty": pos["qty"]}


def _exit_position(user_id, symbol, ex, bot_dir, state, state_path, risk_path, price):
    pos = state["positions"][symbol]
    close_res = _close_user_position(ex, symbol, pos, price)
    if close_res.get("recovery_required"):
        state.setdefault("recovery_required", {})[symbol] = {"reason": close_res.get("error"), "at": _now_iso()}
        save_user_state(state_path, state)
        return {"fired": False, "reason": f"close unresolved: {close_res.get('error')}"}
    cs = pos.get("contract_size") if pos.get("contract_size_verified") else None
    if cs is None:
        state.setdefault("recovery_required", {})[symbol] = {"reason": "missing contract_size for live PnL", "at": _now_iso()}
        save_user_state(state_path, state)
        return {"fired": False, "reason": "missing verified contract_size — needs review"}
    pnl = futures_net_pnl(pos["entry"], close_res["price"], close_res["qty"], cs, pos.get("side", "long"),
                           fee_rate=0.0004, funding_pnl=0.0)
    state["history"].append({"symbol": symbol, "side": pos.get("side", "long"), "entry": pos["entry"],
                              "exit": close_res["price"], "qty": close_res["qty"], "pnl": pnl,
                              "reason": "trend turned off", "time": _now_iso()})
    state["positions"].pop(symbol, None)
    state["last_trade"][symbol] = _now_iso()
    save_user_state(state_path, state)
    try:
        riskmgr.release_open_risk(risk_path, strategy=STRATEGY, symbol=symbol)
    except Exception:
        pass
    return {"fired": True, "action": "exit", "exit": close_res["price"], "pnl": pnl}
