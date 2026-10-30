"""Fail-closed, auditable live activation controls.

An environment variable is necessary but never sufficient. Live activation also
requires an explicit administrator record covering the selected account, every
selected strategy, risk allocation, and a passing readiness result. The record is
stored in SQLite and is never exposed as a UI-only toggle.
"""
from __future__ import annotations
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _now():
    return datetime.now(timezone.utc).isoformat()


def _connect(path):
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    new = not p.exists()
    con = sqlite3.connect(str(p), timeout=5.0, isolation_level=None)
    if new:   # shared by the API and the live bot (RAQM_RISK_DIR, one group)
        try: os.chmod(p, 0o660)
        except OSError: pass
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=5000")
    con.execute("""CREATE TABLE IF NOT EXISTS live_activation_audit (
        activation_id TEXT PRIMARY KEY, environment TEXT NOT NULL, account TEXT NOT NULL,
        approved_by TEXT NOT NULL, approved_at TEXT NOT NULL, strategies TEXT NOT NULL,
        risk_allocation TEXT NOT NULL, readiness TEXT NOT NULL, active INTEGER NOT NULL,
        revoked_at TEXT, revoke_reason TEXT
    )""")
    return con


def _env_enabled():
    return os.getenv("ALLOW_LIVE_TRADING", "").strip().lower() == "true"


def activate(path, *, environment, account, approved_by, strategies, risk_allocation, readiness):
    """Create an activation audit record; every gate must pass explicitly."""
    if not _env_enabled():
        raise PermissionError("ALLOW_LIVE_TRADING is not true")
    if environment != "live":
        raise PermissionError("activation is only for the explicit live environment")
    if not account or not approved_by or not strategies:
        raise ValueError("account, administrator approval, and strategies are required")
    if not isinstance(risk_allocation, dict) or any(float(risk_allocation.get(s, 0) or 0) <= 0 for s in strategies):
        raise ValueError("every selected strategy requires a positive risk allocation")
    if not isinstance(readiness, dict) or not strategies or any(readiness.get(s) is not True for s in strategies):
        raise ValueError("every selected strategy must pass readiness")
    activation_id = f"act-{uuid.uuid4().hex}"
    con = _connect(path)
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute("UPDATE live_activation_audit SET active=0, revoked_at=?, revoke_reason=? WHERE active=1", (_now(), "superseded"))
        con.execute("""INSERT INTO live_activation_audit
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (activation_id, environment, account, approved_by, _now(),
            json.dumps(list(strategies)), json.dumps(risk_allocation), json.dumps(readiness), 1, None, None))
        con.execute("COMMIT")
        return activation_id
    except Exception:
        con.execute("ROLLBACK"); raise
    finally:
        con.close()


def revoke(path, *, activation_id=None, reason="operator revoked"):
    con = _connect(path)
    try:
        con.execute("BEGIN IMMEDIATE")
        if activation_id:
            con.execute("UPDATE live_activation_audit SET active=0, revoked_at=?, revoke_reason=? WHERE activation_id=?", (_now(), reason, activation_id))
        else:
            con.execute("UPDATE live_activation_audit SET active=0, revoked_at=?, revoke_reason=? WHERE active=1", (_now(), reason))
        con.execute("COMMIT")
    finally:
        con.close()


def live_activation_allowed(path, *, strategy, account):
    if not _env_enabled():
        return False, "ALLOW_LIVE_TRADING is not enabled"
    con = _connect(path)
    try:
        row = con.execute("SELECT * FROM live_activation_audit WHERE active=1 ORDER BY approved_at DESC LIMIT 1").fetchone()
        if not row:
            return False, "no active administrator approval"
        if row["environment"] != "live" or row["account"] != account:
            return False, "active approval does not match the selected live account"
        strategies = json.loads(row["strategies"]); readiness = json.loads(row["readiness"])
        if strategy not in strategies or readiness.get(strategy) is not True:
            return False, "strategy is not approved and readiness-verified"
        allocation = float(json.loads(row["risk_allocation"]).get(strategy, 0) or 0)
        if allocation <= 0:
            return False, "strategy has no approved risk allocation"
        return True, None
    except (sqlite3.Error, json.JSONDecodeError, TypeError, ValueError) as exc:
        return False, f"activation audit unavailable: {exc}"
    finally:
        con.close()


# ── Demo (play money): yes/no per strategy, same meaning as the live record (an off strategy stops entering, its open
# positions still exit) but no approval workflow and no ALLOW_LIVE_TRADING — it lives in the Demo ledger's folder, so
# it can never be read by a real-money bot. No choice saved yet = every strategy may enter (as before).

def _demo_table(con):
    con.execute("""CREATE TABLE IF NOT EXISTS demo_selection (
        id INTEGER PRIMARY KEY AUTOINCREMENT, strategies TEXT NOT NULL, set_by TEXT NOT NULL, set_at TEXT NOT NULL)""")


def set_demo_strategies(path, *, strategies, set_by):
    con = _connect(path)
    try:
        _demo_table(con)
        con.execute("INSERT INTO demo_selection(strategies,set_by,set_at) VALUES(?,?,?)",
                    (json.dumps(sorted(set(strategies))), str(set_by), _now()))
    finally:
        con.close()


def demo_strategies(path):
    """The latest Demo choice as a list, or None when nothing was chosen yet."""
    if not Path(path).exists():
        return None                       # read-only: never creates the file
    con = _connect(path)
    try:
        _demo_table(con)
        row = con.execute("SELECT strategies FROM demo_selection ORDER BY id DESC LIMIT 1").fetchone()
        return json.loads(row["strategies"]) if row else None
    finally:
        con.close()


def demo_strategy_allowed(path, *, strategy):
    try:
        chosen = demo_strategies(path)
    except (sqlite3.Error, json.JSONDecodeError, TypeError, ValueError) as exc:
        return False, f"demo selection unavailable: {exc}"
    if chosen is None or strategy in chosen:
        return True, None
    return False, "strategy is turned off for Demo on the dashboard"


def active_record(path):
    con = _connect(path)
    try:
        row = con.execute("SELECT activation_id,environment,account,approved_by,approved_at,strategies,active FROM live_activation_audit WHERE active=1 ORDER BY approved_at DESC LIMIT 1").fetchone()
        if not row:
            return None
        result = dict(row)
        result["strategies"] = json.loads(result["strategies"])
        return result
    finally:
        con.close()
