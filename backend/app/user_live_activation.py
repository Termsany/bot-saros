"""Per-user live-trading consent/audit and risk-limit record.

Separate from backend/app/live_activation.py, which is the admin/owner's own
live-activation gate (ALLOW_LIVE_TRADING + admin audit record) and is left
untouched. This module is the equivalent gate for a REGULAR user enabling
live trading on their OWN account/keys: an explicit confirmation is required,
and every enable is recorded as an audited consent (who, when, from where,
and what they agreed to), with conservative risk defaults scoped per user.
"""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_LEVERAGE = 2
DEFAULT_RISK_PER_TRADE_PCT = 0.25
DEFAULT_MAX_AGGREGATE_RISK_PCT = 1.0

# Safe bounds a user may not exceed even if they set their own values.
MAX_LEVERAGE = 5
MAX_RISK_PER_TRADE_PCT = 1.0
MAX_AGGREGATE_RISK_PCT_CAP = 3.0

CONSENT_TEXT = (
    "I own this exchange account and these API keys. I am enabling LIVE trading "
    "with my own capital, at my own risk, independent of the platform operator. "
    "I understand this can lose money and I accept full responsibility."
)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _connect(path):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p), timeout=5.0, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=5000")
    con.execute("""CREATE TABLE IF NOT EXISTS user_live_activation (
        user_id TEXT PRIMARY KEY, exchange TEXT NOT NULL, enabled INTEGER NOT NULL,
        leverage INTEGER NOT NULL, risk_per_trade_pct REAL NOT NULL, max_aggregate_risk_pct REAL NOT NULL,
        consent_text TEXT NOT NULL, consented_at TEXT NOT NULL, actor TEXT NOT NULL, ip TEXT,
        disabled_at TEXT, disabled_reason TEXT
    )""")
    # which money the consent is for (Phase 2): records from before it was recorded were real-money ones
    if "environment" not in {r[1] for r in con.execute("PRAGMA table_info(user_live_activation)")}:
        con.execute("ALTER TABLE user_live_activation ADD COLUMN environment TEXT NOT NULL DEFAULT 'live'")
    return con


ENVIRONMENTS = ("demo", "live")


def enable_user_live(path, *, user_id, exchange, confirm, actor, ip=None,
                      leverage=None, risk_per_trade_pct=None, max_aggregate_risk_pct=None, environment="live"):
    """Record an audited per-user consent to trade on `exchange` with their own keys — on Binance Demo (play money)
    or real money (`environment`). A Demo consent never counts for real money.

    `confirm` must exactly equal CONSENT_TEXT: this is the explicit confirmation step,
    not a bare boolean checkbox, so the audit trail proves what the user agreed to.
    """
    if not user_id or not exchange:
        raise ValueError("user_id and exchange are required")
    if environment not in ENVIRONMENTS:
        raise ValueError("environment must be demo or live")
    if confirm != CONSENT_TEXT:
        raise PermissionError("explicit consent text does not match — live trading was not enabled")
    lev = int(leverage) if leverage is not None else DEFAULT_LEVERAGE
    rpt = float(risk_per_trade_pct) if risk_per_trade_pct is not None else DEFAULT_RISK_PER_TRADE_PCT
    agg = float(max_aggregate_risk_pct) if max_aggregate_risk_pct is not None else DEFAULT_MAX_AGGREGATE_RISK_PCT
    if not (1 <= lev <= MAX_LEVERAGE):
        raise ValueError(f"leverage must be between 1 and {MAX_LEVERAGE}")
    if not (0 < rpt <= MAX_RISK_PER_TRADE_PCT):
        raise ValueError(f"risk_per_trade_pct must be between 0 and {MAX_RISK_PER_TRADE_PCT}")
    if not (0 < agg <= MAX_AGGREGATE_RISK_PCT_CAP):
        raise ValueError(f"max_aggregate_risk_pct must be between 0 and {MAX_AGGREGATE_RISK_PCT_CAP}")
    if rpt > agg:
        raise ValueError("risk_per_trade_pct cannot exceed max_aggregate_risk_pct")
    con = _connect(path)
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute("""INSERT INTO user_live_activation
            (user_id, exchange, enabled, leverage, risk_per_trade_pct, max_aggregate_risk_pct,
             consent_text, consented_at, actor, ip, disabled_at, disabled_reason, environment)
            VALUES(?,?,1,?,?,?,?,?,?,?,NULL,NULL,?)
            ON CONFLICT(user_id) DO UPDATE SET
              exchange=excluded.exchange, enabled=1, leverage=excluded.leverage,
              risk_per_trade_pct=excluded.risk_per_trade_pct, max_aggregate_risk_pct=excluded.max_aggregate_risk_pct,
              consent_text=excluded.consent_text, consented_at=excluded.consented_at,
              actor=excluded.actor, ip=excluded.ip, disabled_at=NULL, disabled_reason=NULL, environment=excluded.environment
            """, (user_id, exchange, lev, rpt, agg, confirm, _now(), actor, ip, environment))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()
    return True


def disable_user_live(path, *, user_id, reason="user disabled"):
    con = _connect(path)
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute("UPDATE user_live_activation SET enabled=0, disabled_at=?, disabled_reason=? WHERE user_id=?",
                     (_now(), reason, user_id))
        con.execute("COMMIT")
    finally:
        con.close()


def get_user_live_record(path, *, user_id):
    con = _connect(path)
    try:
        row = con.execute("SELECT * FROM user_live_activation WHERE user_id=?", (user_id,)).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def is_user_live_enabled(path, *, user_id, exchange=None):
    rec = get_user_live_record(path, user_id=user_id)
    if not rec or not rec["enabled"]:
        return False
    if exchange and rec["exchange"] != exchange:
        return False
    return True
