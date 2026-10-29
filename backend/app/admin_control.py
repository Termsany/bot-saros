"""Persistent, append-only administrative control state."""
from __future__ import annotations
import json, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STRATEGIES = ("trend_daily", "listing_short", "momentum_ls", "ratio_trend", "vol_breakout", "rsi2_pullback", "trend_breakout", "default")
DEFAULT_CONFIG = {"enabled": True, "mode": "paper", "timeframe": "1h", "symbols": []}

def now(): return datetime.now(timezone.utc).isoformat()
def db_path(root: Path): return root / "admin_control.sqlite3"
def connect(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path(root)), timeout=5.0, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=5000")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE IF NOT EXISTS admin_state (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)")
    con.execute("""CREATE TABLE IF NOT EXISTS admin_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, actor TEXT NOT NULL,
        action TEXT NOT NULL, result TEXT NOT NULL, details TEXT NOT NULL
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS strategy_desired (
        strategy TEXT PRIMARY KEY, enabled INTEGER NOT NULL, paused INTEGER NOT NULL,
        status TEXT NOT NULL, updated_at TEXT NOT NULL
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS strategy_runtime (
        strategy TEXT PRIMARY KEY, status TEXT NOT NULL, heartbeat TEXT,
        last_cycle TEXT, error TEXT, task_id TEXT, updated_at TEXT NOT NULL
    )""")
    return con

def _ensure_strategy_rows(con):
    stamp = now()
    for s in STRATEGIES:
        con.execute("INSERT OR IGNORE INTO strategy_desired(strategy,enabled,paused,status,updated_at) VALUES(?,?,?,?,?)", (s, 0, 0, "stopped", stamp))
        con.execute("INSERT OR IGNORE INTO strategy_runtime(strategy,status,heartbeat,last_cycle,error,task_id,updated_at) VALUES(?,?,?,?,?,?,?)", (s, "stopped", None, None, None, None, stamp))

def defaults():
    return {"entry_paused": {"paused": False, "reason": None, "at": None, "by": None}, "strategies": {s: dict(DEFAULT_CONFIG) for s in STRATEGIES}}

def read_state(root: Path):
    con=connect(root)
    try:
        _ensure_strategy_rows(con)
        state=defaults()
        for r in con.execute("SELECT key,value FROM admin_state"):
            state[r["key"]]=json.loads(r["value"])
        state["strategies"]={s:{**DEFAULT_CONFIG, **(state.get("strategies",{}).get(s) or {})} for s in STRATEGIES}
        for r in con.execute("SELECT strategy,enabled,paused FROM strategy_desired"):
            state["strategies"][r["strategy"]].update(enabled=bool(r["enabled"]), paused=bool(r["paused"]))
        return state
    finally: con.close()

def write_state(root: Path, state: dict):
    con=connect(root)
    try:
        con.execute("BEGIN IMMEDIATE")
        for key in ("entry_paused", "strategies"):
            con.execute("INSERT INTO admin_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at", (key,json.dumps(state[key]),now()))
        _ensure_strategy_rows(con)
        for s, cfg in state["strategies"].items():
            con.execute("UPDATE strategy_desired SET enabled=?,paused=?,updated_at=? WHERE strategy=?", (int(bool(cfg.get("enabled"))), int(bool(cfg.get("paused"))), now(), s))
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

def set_strategy_lifecycle(root: Path, strategy: str, action: str, actor: str):
    if strategy not in STRATEGIES: raise KeyError(strategy)
    if action not in ("start", "stop", "pause", "resume"): raise ValueError(action)
    state = read_state(root); cfg = state["strategies"][strategy]
    if action == "start": cfg.update(enabled=True, paused=False)
    elif action == "stop": cfg.update(enabled=False, paused=False)
    elif action == "pause": cfg.update(enabled=True, paused=True)
    else: cfg.update(enabled=True, paused=False)
    cfg["mode"] = "paper"; state["strategies"][strategy] = cfg; write_state(root, state)
    audit(root, actor, "strategy_" + action, "ok", {"strategy": strategy})
    return cfg

def get_runtime(root: Path, strategy: str):
    if strategy not in STRATEGIES: raise KeyError(strategy)
    con=connect(root)
    try:
        _ensure_strategy_rows(con)
        return dict(con.execute("SELECT strategy,status,heartbeat,last_cycle,error,task_id,updated_at FROM strategy_runtime WHERE strategy=?", (strategy,)).fetchone())
    finally: con.close()

def all_runtime(root: Path): return {s: get_runtime(root, s) for s in STRATEGIES}

_UNSET = object()

def mark_runtime(root: Path, strategy: str, *, status: str, heartbeat=_UNSET, last_cycle=_UNSET, error: str | None = None, task_id=_UNSET):
    old = get_runtime(root, strategy); stamp = now(); con=connect(root)
    heartbeat_value = old.get("heartbeat") if heartbeat is _UNSET else heartbeat
    task_id_value = old.get("task_id") if task_id is _UNSET else task_id
    last_cycle_value = old.get("last_cycle") if last_cycle is _UNSET else last_cycle
    try:
        _ensure_strategy_rows(con)
        con.execute("UPDATE strategy_runtime SET status=?,heartbeat=?,last_cycle=?,error=?,task_id=?,updated_at=? WHERE strategy=?", (status, heartbeat_value, last_cycle_value, error, task_id_value, stamp, strategy))
    finally: con.close()
    return get_runtime(root, strategy)

def invalidate_runtime(root: Path, strategy: str):
    """Invalidate persisted liveness before a lifecycle action can await it."""
    return mark_runtime(root, strategy, status="stopped", heartbeat=None, last_cycle=None, error=None, task_id=None)

def controls(root: Path, strategy: str):
    cfg=read_state(root)["strategies"][strategy]
    return {"enabled": bool(cfg.get("enabled")), "paused": bool(cfg.get("paused")), "active": bool(cfg.get("enabled")) and not bool(cfg.get("paused"))}

def audit_kill(root: Path, actor: str, action: str, result: str, details=None): audit(root,actor,action,result,details)
