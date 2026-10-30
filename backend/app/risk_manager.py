"""Transactional Central Risk Manager shared by every strategy process.

SQLite is authoritative.  Pre-trade checks and reservations happen inside one
BEGIN IMMEDIATE transaction, preventing concurrent strategies from consuming
the same aggregate risk capacity. Reservations are promoted to open after an
entry, removed on known failure, and retained as recovery on ambiguity.
"""
import json
import math
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_LIMITS = {
    "risk_per_trade_pct": 0.25,
    "max_aggregate_risk_pct": 1.0,
    "max_correlated_risk_pct": 1.0,
    "max_daily_loss_pct": 1.0,
    "max_drawdown_pct": 5.0,
    "leverage": 1,
    "margin_mode": "isolated",
    # the owner's capital plan (dashboard): None = not set (no count limit, the bots' own sizes)
    "capital_usdt": None,
    "capital_reserve_pct": 40.0,      # never put to work: losses and margin safety
    "capital_margin_pct": 1.0,        # margin per trade, % of capital ...
    "capital_min_margin_usdt": 30.0,  # ... never below this (BTC/ETH orders must meet Binance's minimum at x2)
    "capital_margin_override_usdt": None,   # the owner's own margin per trade (dashboard), instead of the rule
}


PLAN_LEVERAGE = 2          # every strategy runs at x2 (unit RAQM_ARGS)
PLAN_STOP_LOSS = 0.40      # the strategies' protective stop: 40% of the price, i.e. 80% of a trade's margin at x2


def _finite(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def capital_plan(limits, equity_usdt=None):
    """What the owner's capital allows, every strategy together: margin per trade and the most trades open at once.
    The capital counts at most what the account really holds (equity), for the size of a trade and for the count, so
    a typo can't trade more than the money there. Margin: the owner's own (manual) or max(min margin, capital ×
    margin %); max open = capital × (1 − reserve %) ÷ margin. Also what one stop and every stop at once would cost.
    None = no plan set; a value that isn't a finite number raises ValueError (the callers refuse the entry)."""
    capital = _finite(limits.get("capital_usdt") or 0)
    if capital is None:
        raise ValueError("capital is not a number")
    if capital <= 0:
        return None
    equity = _finite(equity_usdt)
    effective = min(capital, equity) if equity and equity > 0 else capital
    reserve = _finite(limits.get("capital_reserve_pct") if limits.get("capital_reserve_pct") is not None else 40.0)
    pct = _finite(limits.get("capital_margin_pct") or 1.0); floor = _finite(limits.get("capital_min_margin_usdt") or 30.0)
    manual = _finite(limits.get("capital_margin_override_usdt") or 0)
    if None in (reserve, pct, floor, manual):
        raise ValueError("capital plan setting is not a number")
    margin = manual if manual > 0 else max(floor, effective * pct / 100.0)
    usable = effective * (1.0 - reserve / 100.0)
    max_open = max(0, int(usable // margin))
    loss = margin * PLAN_LEVERAGE * PLAN_STOP_LOSS
    return {"capital": capital, "effective_capital": round(effective, 2), "margin": round(margin, 2), "manual": manual > 0,
            "max_open": max_open, "notional": round(margin * PLAN_LEVERAGE, 2),
            "loss_per_trade": round(loss, 2), "loss_per_trade_pct": round(loss / effective * 100, 2),
            "worst_case_pct": round(loss * max_open / effective * 100, 1), "level": risk_level(loss / effective * 100)}


def risk_level(loss_pct):
    """How much one stop costs, as a share of the capital: low < 1% ≤ medium < 2% ≤ high < 5% ≤ very high."""
    return "low" if loss_pct < 1 else "medium" if loss_pct < 2 else "high" if loss_pct < 5 else "very_high"


def plan_vs_limits(limits, plan):
    """Which limit stops entries first with this plan: the count, the per-trade risk limit or the aggregate one."""
    if not plan:
        return None
    per_trade = plan["loss_per_trade_pct"]
    rpt = float(limits.get("risk_per_trade_pct") or 0); agg = float(limits.get("max_aggregate_risk_pct") or 0)
    by_aggregate = int(agg // per_trade) if per_trade > 0 else plan["max_open"]
    if per_trade > rpt:
        binding, allowed = "risk_per_trade", 0
    elif by_aggregate < plan["max_open"]:
        binding, allowed = "aggregate_risk", by_aggregate
    else:
        binding, allowed = "capital", plan["max_open"]
    return {"binding": binding, "allowed": allowed, "risk_per_trade_pct": rpt, "max_aggregate_risk_pct": agg}


def _over_capital_plan(state, equity_usdt, adding):
    plan = capital_plan(state["limits"], equity_usdt)
    if not plan:
        return None
    n = len(state.get("open_risk") or {})
    if n + adding > plan["max_open"]:
        return (f"max open trades for capital ${plan['effective_capital']:.0f} reached: {n} open + {adding} new > {plan['max_open']} "
                f"(raise the capital on the dashboard to allow more)")
    return None
_DB_SUFFIX = ".sqlite3"


def _db_path(path):
    p = Path(path)
    return p.with_suffix(_DB_SUFFIX) if p.suffix else Path(str(p) + _DB_SUFFIX)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _today():
    return datetime.now(timezone.utc).date().isoformat()


def _default_state(limits=None):
    return {
        "limits": {**DEFAULT_LIMITS, **(limits or {})},
        "kill_switch": {"tripped": False, "reason": None, "at": None, "by": None},
        "equity_high_water_mark": None,
        "equity_observed_at": None,
        "equity_last": None,
        "daily": {"date": None, "realized_pnl": 0.0, "start_equity": None},
        "open_risk": {},
    }


def ledger_dir(default):
    """Where the risk ledger and the live activation record live. RAQM_RISK_DIR makes the dashboard API and the
    real-money bot use the same files: each used its own folder, so a kill switch or a revoke from the dashboard
    never reached the bot (and the bot's read-only code folder could not hold a ledger at all)."""
    return Path(os.getenv("RAQM_RISK_DIR", "").strip() or default)


def _connect(path):
    db = _db_path(path)
    db.parent.mkdir(parents=True, exist_ok=True)
    new = not db.exists()
    con = sqlite3.connect(str(db), timeout=5.0, isolation_level=None)
    if new:   # shared by the API and the bot (one group): SQLite gives its -wal/-shm files the database's mode
        try: os.chmod(db, 0o660)
        except OSError: pass
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=5000")
    try:
        con.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError as exc:
        if "locked" not in str(exc).lower():
            raise

    con.execute("CREATE TABLE IF NOT EXISTS risk_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    con.execute("""CREATE TABLE IF NOT EXISTS open_risk (
        key TEXT PRIMARY KEY, strategy TEXT NOT NULL, symbol TEXT NOT NULL,
        side TEXT NOT NULL, risk_usdt REAL NOT NULL, notional_usdt REAL NOT NULL,
        correlation_group TEXT, status TEXT NOT NULL, at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""")
    return con


def _legacy_json(path):
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        raise


def _ensure_legacy_migrated(con, path):
    if con.execute("SELECT 1 FROM risk_meta WHERE key='limits'").fetchone():
        return
    legacy = _legacy_json(path)
    state = _default_state()
    if legacy is not None:
        if not isinstance(legacy, dict):
            raise ValueError("risk ledger JSON is not an object")
        state.update({k: v for k, v in legacy.items() if k != "limits"})
        state["limits"] = {**DEFAULT_LIMITS, **(legacy.get("limits") or {})}
    _write_state_tx(con, state)


_META_KEYS = ("limits", "kill_switch", "equity_high_water_mark", "equity_observed_at", "daily", "equity_last")


def _write_meta_tx(con, state):
    for key in _META_KEYS:
        con.execute("INSERT INTO risk_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, json.dumps(state.get(key))))


def _write_state_tx(con, state):
    _write_meta_tx(con, state)
    con.execute("DELETE FROM open_risk")
    for key, row in (state.get("open_risk") or {}).items():
        stamp = row.get("at", _now())
        con.execute("""INSERT INTO open_risk
            (key,strategy,symbol,side,risk_usdt,notional_usdt,correlation_group,status,at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)""", (key, row.get("strategy"), row.get("symbol"), row.get("side"),
            float(row.get("risk_usdt", 0) or 0), float(row.get("notional_usdt", 0) or 0),
            row.get("correlation_group"), row.get("status", "open"), stamp, row.get("updated_at", stamp)))


def _read_state_tx(con):
    state = _default_state()
    for row in con.execute("SELECT key,value FROM risk_meta"):
        state[row["key"]] = json.loads(row["value"])
    state["limits"] = {**DEFAULT_LIMITS, **(state.get("limits") or {})}
    state["open_risk"] = {}
    for row in con.execute("SELECT * FROM open_risk"):
        state["open_risk"][row["key"]] = {k: row[k] for k in
            ("strategy", "symbol", "side", "risk_usdt", "notional_usdt", "correlation_group", "status", "at", "updated_at")}
    return state


def load_risk_state(path):
    con = _connect(path)
    try:
        con.execute("BEGIN")
        _ensure_legacy_migrated(con, path)
        state = _read_state_tx(con)
        con.execute("COMMIT")
        return state
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def save_risk_state(path, state):
    con = _connect(path)
    try:
        con.execute("BEGIN IMMEDIATE")
        _write_state_tx(con, state)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def _rows(state):
    return list((state.get("open_risk") or {}).values())


def aggregate_open_risk_pct(state, equity_usdt):
    if not equity_usdt or equity_usdt <= 0:
        return None
    return sum(float(r.get("risk_usdt", 0) or 0) for r in _rows(state)) / float(equity_usdt) * 100.0


def correlated_risk_pct(state, equity_usdt, correlation_group, side):
    if not equity_usdt or equity_usdt <= 0 or not correlation_group:
        return None
    return sum(float(r.get("risk_usdt", 0) or 0) for r in _rows(state)
               if r.get("correlation_group") == correlation_group and r.get("side") == side) / float(equity_usdt) * 100.0


def strategy_open_risk_pct(state, equity_usdt, strategy):
    """This strategy's open risk as a share of equity — what its activation allocation caps."""
    if not equity_usdt or equity_usdt <= 0:
        return None
    return sum(float(r.get("risk_usdt", 0) or 0) for r in _rows(state)
               if r.get("strategy") == strategy) / float(equity_usdt) * 100.0


def _plan_set(limits):
    """The owner's capital plan is set: then only the account's count and limits bind (owner, 2026-10-30), so the
    allocation is not split per strategy. The allocation is still validated: an invalid one still refuses."""
    return capital_plan(limits) is not None


def _strategy_cap_pct(limits, share):
    """Absolute strategy cap (in % of equity) from its share of the aggregate risk budget.

    None = no allocation (paper/Demo, where there is no activation record). An invalid share returns None too: callers
    must not treat it as unlimited — the gate rejects it explicitly.
    """
    try:
        share = float(share)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(share) or not (0 < share <= 1.0):
        return None
    agg_cap = float(limits.get("max_aggregate_risk_pct", DEFAULT_LIMITS["max_aggregate_risk_pct"]))
    return agg_cap * share


def _conflicting_position(state, symbol, side, strategy=None):
    """Another strategy already on this coin. The account is one-way: two strategies on one coin share a single
    exchange position — same side, one exit closes both (the other keeps a phantom and a live reduceOnly stop);
    opposite sides net each other out. So one coin, one strategy, whatever the side."""
    base = str(symbol).split(":")[0]
    return next((r for r in _rows(state) if str(r.get("symbol")).split(":")[0] == base
                 and (r.get("side") != side or (strategy is not None and r.get("strategy") != strategy))), None)


def _valid_equity(value):
    try:
        return value is not None and math.isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError):
        return False


def _equity_fresh(observed_at, max_age_s):
    """Freshness gate, not a formality: no timestamp means no evidence that the figure is current, so it is stale.

    The previous `None -> True` made the check a no-op for every caller that omitted the timestamp, which was every
    production caller except the per-user scheduler. A timestamp from the future is also refused: that is a clock
    problem, not fresh evidence (only a small skew is tolerated)."""
    if observed_at is None:
        return False
    try:
        age_limit = float(max_age_s)
        if not math.isfinite(age_limit) or age_limit <= 0:
            return False
        stamp = datetime.fromisoformat(observed_at.replace("Z", "+00:00")) if isinstance(observed_at, str) else datetime.fromtimestamp(float(observed_at), tz=timezone.utc)
        age = (datetime.now(timezone.utc) - stamp).total_seconds()
        return -60.0 <= age <= age_limit
    except (TypeError, ValueError, OverflowError):
        return False


def pre_trade_gate(path, *, strategy, symbol, side, risk_usdt, notional_usdt,
                    equity_usdt, correlation_group=None, allow_strategy_conflicts=False,
                    equity_observed_at=None, max_equity_age_s=30, strategy_risk_share=None):
    """Atomically check all limits and reserve the requested risk.

    ``strategy_risk_share`` is the activation record's allocation for this strategy: a fraction of the account's
    max aggregate risk budget that this strategy's open risk (existing + new) may not exceed. None = no activation
    record (paper/Demo). A value that is not a finite number in (0, 1] is refused, never treated as unlimited.
    """
    if not _valid_equity(equity_usdt):
        return False, "equity unavailable or invalid; refusing to reserve risk"
    if not _equity_fresh(equity_observed_at, max_equity_age_s):
        return False, "equity stale; refusing to reserve risk"
    try:
        risk_usdt = float(risk_usdt)
        notional_usdt = float(notional_usdt or 0)
        if not math.isfinite(risk_usdt) or risk_usdt < 0 or not math.isfinite(notional_usdt):
            raise ValueError
    except (TypeError, ValueError):
        return False, "invalid risk amount"
    con = _connect(path)
    try:
        con.execute("BEGIN IMMEDIATE")
        _ensure_legacy_migrated(con, path)
        state = _read_state_tx(con)
        if state["kill_switch"].get("tripped"):
            con.execute("ROLLBACK")
            return False, f"kill switch is tripped: {state['kill_switch'].get('reason')}"
        limits = state["limits"]
        over = _over_capital_plan(state, equity_usdt, 1)
        if over:
            con.execute("ROLLBACK")
            return False, over
        pct = risk_usdt / float(equity_usdt) * 100.0
        cap = float(limits.get("risk_per_trade_pct", DEFAULT_LIMITS["risk_per_trade_pct"]))
        key = f"{strategy}:{symbol}"
        if state["open_risk"].get(key):
            con.execute("ROLLBACK")
            return False, f"risk reservation already exists for {key}"
        if pct > cap + 1e-9:
            con.execute("ROLLBACK")
            return False, f"per-trade risk {pct:.3f}% exceeds limit {cap}%"
        agg = aggregate_open_risk_pct(state, equity_usdt) or 0.0
        agg_cap = float(limits.get("max_aggregate_risk_pct", DEFAULT_LIMITS["max_aggregate_risk_pct"]))
        if strategy_risk_share is not None:
            strategy_cap = _strategy_cap_pct(limits, strategy_risk_share)
            if strategy_cap is None:
                con.execute("ROLLBACK")
                return False, f"invalid strategy risk allocation {strategy_risk_share!r}"
            strat = strategy_open_risk_pct(state, equity_usdt, strategy) or 0.0
            if not _plan_set(limits) and strat + pct > strategy_cap + 1e-9:
                con.execute("ROLLBACK")
                return False, (f"strategy open risk {strat:.3f}% + new {pct:.3f}% would exceed its allocation "
                               f"{float(strategy_risk_share):.4g} of the aggregate budget ({strategy_cap:.3f}% of equity)")
        if agg + pct > agg_cap + 1e-9:
            con.execute("ROLLBACK")
            return False, f"aggregate open risk {agg:.3f}% + new {pct:.3f}% would exceed limit {agg_cap}%"
        if correlation_group:
            corr = correlated_risk_pct(state, equity_usdt, correlation_group, side) or 0.0
            corr_cap = float(limits.get("max_correlated_risk_pct", DEFAULT_LIMITS["max_correlated_risk_pct"]))
            if corr + pct > corr_cap + 1e-9:
                con.execute("ROLLBACK")
                return False, f"correlated risk in group '{correlation_group}' {corr:.3f}% + new {pct:.3f}% would exceed limit {corr_cap}%"
        if not allow_strategy_conflicts:
            conflict = _conflicting_position(state, symbol, side, strategy)
            if conflict:
                con.execute("ROLLBACK")
                return False, f"strategy conflict: {conflict.get('strategy')} already holds {symbol} {conflict.get('side')}"
        stamp = _now()
        con.execute("INSERT INTO open_risk VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (key, strategy, symbol, side, risk_usdt, notional_usdt, correlation_group, "reserved", stamp, stamp))
        con.execute("COMMIT")
        return True, None
    except (sqlite3.Error, OSError, ValueError) as exc:
        try:
            con.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        return False, f"risk ledger unavailable: {exc}"
    finally:
        con.close()


def pre_trade_gate_basket(path, *, strategy, legs, equity_usdt, equity_observed_at=None, max_equity_age_s=30,
                          strategy_risk_share=None):
    """Atomically reserve every leg of a basket or pair; the strategy allocation caps the basket's whole risk."""
    if not _valid_equity(equity_usdt) or not legs:
        return False, "equity unavailable or empty basket; refusing to reserve risk"
    if not _equity_fresh(equity_observed_at, max_equity_age_s):
        return False, "equity stale; refusing to reserve risk"
    con = _connect(path)
    try:
        con.execute("BEGIN IMMEDIATE")
        _ensure_legacy_migrated(con, path)
        state = _read_state_tx(con)
        if state["kill_switch"].get("tripped"):
            con.execute("ROLLBACK")
            return False, f"kill switch is tripped: {state['kill_switch'].get('reason')}"
        limits = state["limits"]
        over = _over_capital_plan(state, equity_usdt, len(legs))   # a basket enters whole or not at all
        if over:
            con.execute("ROLLBACK"); return False, over
        requested = []
        for leg in legs:
            try:
                risk = float(leg.get("risk_usdt")); notional = float(leg.get("notional_usdt", 0) or 0)
                if not math.isfinite(risk) or risk < 0 or not math.isfinite(notional): raise ValueError
            except (TypeError, ValueError):
                con.execute("ROLLBACK"); return False, "invalid basket risk amount"
            key = f"{strategy}:{leg['symbol']}"
            if key in state["open_risk"]:
                con.execute("ROLLBACK"); return False, f"risk reservation already exists for {key}"
            if not leg.get("allow_strategy_conflicts") and _conflicting_position(state, leg["symbol"], leg["side"], strategy):
                con.execute("ROLLBACK"); return False, f"strategy conflict on {leg['symbol']}"
            pct = risk / float(equity_usdt) * 100.0
            if pct > float(limits.get("risk_per_trade_pct", DEFAULT_LIMITS["risk_per_trade_pct"])) + 1e-9:
                con.execute("ROLLBACK"); return False, f"per-leg risk {pct:.3f}% exceeds limit"
            requested.append((leg, key, risk, notional))
        total_pct = sum(x[2] for x in requested) / float(equity_usdt) * 100.0
        corr_cap = float(limits.get("max_correlated_risk_pct", DEFAULT_LIMITS["max_correlated_risk_pct"]))
        for group in {x[0].get("correlation_group") for x in requested if x[0].get("correlation_group")}:
            for side in {x[0].get("side") for x in requested if x[0].get("correlation_group") == group}:
                existing = correlated_risk_pct(state, equity_usdt, group, side) or 0.0
                added = sum(x[2] for x in requested if x[0].get("correlation_group") == group and x[0].get("side") == side) / float(equity_usdt) * 100.0
                if existing + added > corr_cap + 1e-9:
                    con.execute("ROLLBACK"); return False, f"correlated basket risk exceeds limit {corr_cap}%"
        current_pct = aggregate_open_risk_pct(state, equity_usdt) or 0.0
        cap = float(limits.get("max_aggregate_risk_pct", DEFAULT_LIMITS["max_aggregate_risk_pct"]))
        if strategy_risk_share is not None:
            strategy_cap = _strategy_cap_pct(limits, strategy_risk_share)
            if strategy_cap is None:
                con.execute("ROLLBACK"); return False, f"invalid strategy risk allocation {strategy_risk_share!r}"
            strat = strategy_open_risk_pct(state, equity_usdt, strategy) or 0.0
            if not _plan_set(limits) and strat + total_pct > strategy_cap + 1e-9:
                con.execute("ROLLBACK")
                return False, (f"strategy open risk {strat:.3f}% + basket {total_pct:.3f}% would exceed its allocation "
                               f"{float(strategy_risk_share):.4g} of the aggregate budget ({strategy_cap:.3f}% of equity)")
        if current_pct + total_pct > cap + 1e-9:
            con.execute("ROLLBACK"); return False, f"aggregate basket risk exceeds limit {cap}%"
        for leg, key, risk, notional in requested:
            stamp = _now()
            con.execute("INSERT INTO open_risk VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (key, strategy, leg["symbol"], leg["side"], risk, notional,
                         leg.get("correlation_group"), "reserved", stamp, stamp))
        con.execute("COMMIT"); return True, None
    except (sqlite3.Error, OSError, ValueError) as exc:
        try: con.execute("ROLLBACK")
        except sqlite3.Error: pass
        return False, f"risk ledger unavailable: {exc}"
    finally:
        con.close()


def register_open_risk(path, *, strategy, symbol, side, risk_usdt, notional_usdt, correlation_group=None):
    key = f"{strategy}:{symbol}"
    con = _connect(path)
    try:
        con.execute("BEGIN IMMEDIATE")
        _ensure_legacy_migrated(con, path)
        stamp = _now()
        con.execute("""INSERT INTO open_risk VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(key) DO UPDATE SET strategy=excluded.strategy,symbol=excluded.symbol,
            side=excluded.side,risk_usdt=excluded.risk_usdt,notional_usdt=excluded.notional_usdt,
            correlation_group=excluded.correlation_group,status='open',updated_at=excluded.updated_at""",
            (key, strategy, symbol, side, float(risk_usdt or 0), float(notional_usdt or 0), correlation_group, "open", stamp, stamp))
        con.execute("COMMIT")
    finally:
        con.close()


def mark_reservation_recovery(path, *, strategy, symbol, reason):
    con = _connect(path)
    try:
        con.execute("BEGIN IMMEDIATE")
        _ensure_legacy_migrated(con, path)
        con.execute("UPDATE open_risk SET status='recovery', updated_at=? WHERE key=?", (_now(), f"{strategy}:{symbol}"))
        con.execute("COMMIT")
    finally:
        con.close()


def rollback_reservation(path, *, strategy, symbol):
    con = _connect(path)
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute("DELETE FROM open_risk WHERE key=? AND status='reserved'", (f"{strategy}:{symbol}",))
        con.execute("COMMIT")
    finally:
        con.close()


def release_open_risk(path, *, strategy, symbol):
    con = _connect(path)
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute("DELETE FROM open_risk WHERE key=?", (f"{strategy}:{symbol}",))
        con.execute("COMMIT")
    finally:
        con.close()


def update_equity_and_check_kill_switch(path, equity_usdt, *, equity_observed_at=None, max_equity_age_s=30):
    con = _connect(path)
    try:
        con.execute("BEGIN IMMEDIATE")
        _ensure_legacy_migrated(con, path)
        state = _read_state_tx(con)
        if state["kill_switch"].get("tripped"):
            con.execute("COMMIT")
            return True, state["kill_switch"].get("reason")
        if not _valid_equity(equity_usdt):
            reason = "equity unavailable or invalid; kill switch engaged fail-closed"
            state["kill_switch"] = {"tripped": True, "reason": reason, "at": _now(), "by": "risk_manager"}
            _write_state_tx(con, state); con.execute("COMMIT")
            return True, reason
        if not _equity_fresh(equity_observed_at, max_equity_age_s):
            reason = "equity stale; kill switch engaged fail-closed"
            state["kill_switch"] = {"tripped": True, "reason": reason, "at": _now(), "by": "risk_manager"}
            _write_state_tx(con, state); con.execute("COMMIT")
            return True, reason
        equity_usdt = float(equity_usdt)
        state["equity_observed_at"] = equity_observed_at   # already proven fresh above; never substitute "now"
        state["equity_last"] = equity_usdt          # the dashboard and the bots' sizing cap the capital with it
        hwm = state.get("equity_high_water_mark")
        if hwm is None or equity_usdt > hwm:
            state["equity_high_water_mark"] = equity_usdt
            hwm = equity_usdt
        daily = state.setdefault("daily", {"date": None, "realized_pnl": 0.0, "start_equity": None})
        if daily.get("date") != _today():
            daily.update({"date": _today(), "start_equity": equity_usdt, "realized_pnl": 0.0})
        reason = None
        dd = (hwm - equity_usdt) / hwm * 100.0
        if dd >= float(state["limits"]["max_drawdown_pct"]):
            reason = f"portfolio drawdown {dd:.2f}% >= limit {state['limits']['max_drawdown_pct']}%"
        if reason is None and daily.get("start_equity"):
            loss = (daily["start_equity"] - equity_usdt) / daily["start_equity"] * 100.0
            if loss >= float(state["limits"]["max_daily_loss_pct"]):
                reason = f"daily loss {loss:.2f}% >= limit {state['limits']['max_daily_loss_pct']}%"
        if reason:
            state["kill_switch"] = {"tripped": True, "reason": reason, "at": _now(), "by": "risk_manager"}
        _write_state_tx(con, state); con.execute("COMMIT")
        return reason is not None, reason
    except Exception:
        try:
            con.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        con.close()


def _mutate_meta(path, mutate):
    """Read and change the meta rows (limits, kill switch, daily) in one BEGIN IMMEDIATE transaction, never touching
    open_risk. A load_risk_state / save_risk_state pair left a gap in which a bot's kill-switch trip or reservation
    was overwritten with the stale snapshot (reproduced: the switch un-tripped and open_risk emptied)."""
    con = _connect(path)
    try:
        con.execute("BEGIN IMMEDIATE")
        _ensure_legacy_migrated(con, path)
        state = _read_state_tx(con)
        out = mutate(state)
        _write_meta_tx(con, state)
        con.execute("COMMIT")
        return out
    except Exception:
        try: con.execute("ROLLBACK")
        except sqlite3.Error: pass
        raise
    finally:
        con.close()


def trip_kill_switch(path, reason, *, by="manual"):
    def mutate(state): state["kill_switch"] = {"tripped": True, "reason": str(reason), "at": _now(), "by": by}
    _mutate_meta(path, mutate)


def reset_kill_switch(path, *, operator):
    def mutate(state): state["kill_switch"] = {"tripped": False, "reason": None, "at": _now(), "by": f"reset:{operator}"}
    _mutate_meta(path, mutate)


def update_limits(path, patch):
    """Merge ``patch`` into the limits; returns the new limits."""
    def mutate(state):
        state["limits"].update(patch); return dict(state["limits"])
    return _mutate_meta(path, mutate)


def record_realized_pnl(path, pnl_usdt):
    def mutate(state):
        daily = state.setdefault("daily", {"date": None, "realized_pnl": 0.0, "start_equity": None})
        if daily.get("date") != _today():
            daily.update({"date": _today(), "realized_pnl": 0.0})
        daily["realized_pnl"] = float(daily.get("realized_pnl", 0) or 0) + float(pnl_usdt or 0)
    _mutate_meta(path, mutate)
