"""Persistent, append-only administrative control state."""
from __future__ import annotations
import json, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STRATEGIES = ("trend_daily", "wave_flats", "listing_short", "momentum_ls", "ratio_trend", "vol_breakout", "rsi2_pullback", "trend_breakout", "default")
DEFAULT_CONFIG = {"enabled": True, "mode": "paper", "timeframe": "1h", "symbols": []}

def now(): return datetime.now(timezone.utc).isoformat()
def db_path(root: Path): return root / "admin_control.sqlite3"
def connect(root: Path):
    con = sqlite3.connect(str(db_path(root)), timeout=5.0, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=5000")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE IF NOT EXISTS admin_state (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)")
    con.execute("""CREATE TABLE IF NOT EXISTS admin_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, actor TEXT NOT NULL,
        action TEXT NOT NULL, result TEXT NOT NULL, details TEXT NOT NULL
    )""")
    return con

def defaults():
    return {"entry_paused": {"paused": False, "reason": None, "at": None, "by": None}, "strategies": {s: dict(DEFAULT_CONFIG) for s in STRATEGIES}}

def read_state(root: Path):
    con=connect(root)
    try:
        state=defaults()
        for r in con.execute("SELECT key,value FROM admin_state"):
            state[r["key"]]=json.loads(r["value"])
        state["strategies"]={s:{**DEFAULT_CONFIG, **(state.get("strategies",{}).get(s) or {})} for s in STRATEGIES}
        return state
    finally: con.close()

def write_state(root: Path, state: dict):
    con=connect(root)
    try:
        con.execute("BEGIN IMMEDIATE")
        for key in ("entry_paused", "strategies"):
            con.execute("INSERT INTO admin_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at", (key,json.dumps(state[key]),now()))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK"); raise
    finally: con.close()

def audit(root: Path, actor: str, action: str, result: str, details: dict[str, Any] | None = None):
    con=connect(root)
    try:
        con.execute("INSERT INTO admin_audit(at,actor,action,result,details) VALUES(?,?,?,?,?)", (now(), actor, action, result, json.dumps(details or {}, ensure_ascii=False, default=str)))
    finally: con.close()

def list_audit(root: Path, limit=100):
    con=connect(root)
    try: return [dict(r) for r in con.execute("SELECT id,at,actor,action,result,details FROM admin_audit ORDER BY id DESC LIMIT ?", (limit,))]
    finally: con.close()

def set_entry_pause(root: Path, paused: bool, actor: str, reason: str | None):
    state=read_state(root); state["entry_paused"]={"paused":paused,"reason":reason,"at":now(),"by":actor}; write_state(root,state); audit(root,actor,"entry_pause" if paused else "entry_resume","ok",state["entry_paused"]); return state["entry_paused"]

def update_strategy(root: Path, strategy: str, patch: dict, actor: str):
    if strategy not in STRATEGIES: raise KeyError(strategy)
    state=read_state(root); cfg=state["strategies"][strategy]; cfg.update(patch); cfg["mode"]="paper"; state["strategies"][strategy]=cfg; write_state(root,state); audit(root,actor,"strategy_update","ok",{"strategy":strategy,"patch":patch}); return cfg

def audit_kill(root: Path, actor: str, action: str, result: str, details=None): audit(root,actor,action,result,details)
