"""Fail-closed durable execution engine for live baskets and pairs.

The engine deliberately knows nothing about a particular strategy or exchange.  The
caller supplies order, close, position and protection callbacks; this keeps paper
signal code unchanged while making every live workflow journaled and recoverable.
"""
from __future__ import annotations

import json
import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def _db_path(path):
    p = Path(path)
    return p.with_suffix(p.suffix + ".execution.sqlite3") if p.suffix else Path(str(p) + ".execution.sqlite3")


def _now():
    return datetime.now(timezone.utc).isoformat()


class ExecutionRecoveryRequired(RuntimeError):
    pass


class MultiLegExecutionEngine:
    """Journal-first basket executor with deterministic ordering and compensation."""

    def __init__(self, journal_path, *, risk_manager, risk_path, save_state=None, block=None):
        self.path = _db_path(journal_path)
        self.riskmgr = risk_manager
        self.risk_path = risk_path
        self.save_state = save_state or (lambda state: None)
        self.block = block or (lambda reason: None)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        con = sqlite3.connect(str(self.path), timeout=5.0, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout=5000")
        return con

    def _init_db(self):
        con = self._connect()
        try:
            con.execute("""CREATE TABLE IF NOT EXISTS executions (
                execution_id TEXT PRIMARY KEY, strategy TEXT NOT NULL, intent TEXT NOT NULL,
                status TEXT NOT NULL, payload TEXT NOT NULL, residual TEXT, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL)""")
            con.execute("""CREATE TABLE IF NOT EXISTS execution_steps (
                execution_id TEXT NOT NULL, step_no INTEGER NOT NULL, symbol TEXT NOT NULL,
                action TEXT NOT NULL, client_order_id TEXT NOT NULL, status TEXT NOT NULL,
                result TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(execution_id, step_no))""")
            con.execute("""CREATE TABLE IF NOT EXISTS execution_residuals (
                execution_id TEXT PRIMARY KEY, payload TEXT NOT NULL, status TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        finally:
            con.close()

    def _write_execution(self, execution_id, strategy, intent, status, payload, residual=None):
        con = self._connect()
        try:
            stamp = _now()
            con.execute("""INSERT INTO executions(execution_id,strategy,intent,status,payload,residual,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(execution_id) DO UPDATE SET status=excluded.status,
                payload=excluded.payload,residual=excluded.residual,updated_at=excluded.updated_at""",
                (execution_id, strategy, intent, status, json.dumps(payload, default=str),
                 json.dumps(residual, default=str) if residual is not None else None, stamp, stamp))
        finally:
            con.close()

    def _write_step(self, execution_id, n, leg, status, result=None, error=None):
        con = self._connect()
        try:
            stamp = _now()
            con.execute("""INSERT INTO execution_steps(execution_id,step_no,symbol,action,client_order_id,status,result,error,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(execution_id,step_no) DO UPDATE SET status=excluded.status,
                result=excluded.result,error=excluded.error,updated_at=excluded.updated_at""",
                (execution_id, n, leg["symbol"], leg.get("action", "entry"), leg["client_order_id"], status,
                 json.dumps(result, default=str) if result is not None else None, str(error) if error else None, stamp, stamp))
        finally:
            con.close()

    def _reserve(self, strategy, legs, equity):
        fn = getattr(self.riskmgr, "pre_trade_gate_basket", None)
        if callable(fn):
            return fn(self.risk_path, strategy=strategy, legs=legs, equity_usdt=equity)
        reserved = []
        for leg in legs:
            ok, reason = self.riskmgr.pre_trade_gate(self.risk_path, strategy=strategy, **leg, equity_usdt=equity)
            if not ok:
                for prior in reserved:
                    self.riskmgr.rollback_reservation(self.risk_path, strategy=strategy, symbol=prior["symbol"])
                return False, reason
            reserved.append(leg)
        return True, None

    def _release(self, strategy, legs):
        for leg in legs:
            try:
                self.riskmgr.release_open_risk(self.risk_path, strategy=strategy, symbol=leg["symbol"])
            except Exception:
                pass

    @staticmethod
    def _stable_id(strategy, intent, legs):
        identity = "|".join(f"{leg.get('symbol')}:{leg.get('side')}:{leg.get('action','entry')}:{leg.get('leg_id',leg.get('order',0))}"
                             for leg in sorted(legs, key=lambda x: (int(x.get('order', 0)), x['symbol'])))
        return "exec-" + hashlib.sha256(f"{strategy}|{intent}|{identity}".encode()).hexdigest()[:32]

    def execute(self, *, strategy, intent, legs, equity_usdt, execute_leg, compensate_leg,
                verify_protection, state=None, execution_id=None, reserve=True,
                persist_fills=None):
        """Execute a basket. ``legs`` are sorted by caller-provided ``order`` then symbol."""
        if not legs:
            raise ValueError("basket must contain at least one leg")
        execution_id = execution_id or self._stable_id(strategy, intent, legs)
        ordered = sorted(legs, key=lambda x: (int(x.get("order", 0)), x["symbol"]))
        for leg in ordered:
            leg.setdefault("client_order_id", "raqm-" + hashlib.sha256(
                f"{strategy}|{intent}|{leg['symbol']}|{leg.get('side')}|{leg.get('action','entry')}|{leg.get('leg_id',leg.get('order',0))}".encode()
            ).hexdigest()[:27])
        existing = self._connect()
        try:
            row = existing.execute("SELECT status,payload FROM executions WHERE execution_id=?", (execution_id,)).fetchone()
            if row and row["status"] == "filled":
                return {"ok": True, "status": "filled", "execution_id": execution_id, "fills": [] , "reused": True}
        finally:
            existing.close()
        payload = {"legs": ordered, "intent": intent}
        self._write_execution(execution_id, strategy, intent, "intent_persisted", payload)
        ok, reason = (True, None) if not reserve else self._reserve(strategy, ordered, equity_usdt)
        if not ok:
            self._write_execution(execution_id, strategy, intent, "risk_blocked", payload, {"reason": reason})
            return {"ok": False, "status": "risk_blocked", "reason": reason, "execution_id": execution_id}
        filled = []
        try:
            for n, leg in enumerate(ordered, 1):
                self._write_step(execution_id, n, leg, "started")
                try:
                    result = execute_leg(leg)
                    requested = leg.get("requested_qty", leg.get("qty"))
                    actual = float(result.get("qty", 0) or 0) if result else 0.0
                    if not result or actual <= 0:
                        raise RuntimeError("leg returned no filled quantity")
                    if requested is not None and actual + 1e-9 < float(requested):
                        raise RuntimeError(f"partial fill: requested={requested}, filled={actual}")
                    filled.append((leg, result))
                    self._write_step(execution_id, n, leg, "filled", result=result)
                except Exception as exc:
                    self._write_step(execution_id, n, leg, "failed", error=exc)
                    residual = []
                    for prior, prior_result in reversed(filled):
                        try:
                            cres = compensate_leg(prior, prior_result)
                            if not cres or cres.get("confirmed") is False:
                                raise RuntimeError("compensation not confirmed")
                            self._write_step(execution_id, ordered.index(prior) + 1, prior, "compensated", result=cres)
                        except Exception as cexc:
                            residual.append({"leg": prior, "fill": prior_result, "reason": str(cexc)})
                    if residual:
                        self._write_execution(execution_id, strategy, intent, "recovery_required", payload, residual)
                        con = self._connect()
                        try:
                            con.execute("INSERT OR REPLACE INTO execution_residuals VALUES(?,?,?,?,?)",
                                        (execution_id, json.dumps(residual, default=str), "open", _now(), _now()))
                        finally:
                            con.close()
                        self.block("multi-leg residual exposure requires recovery")
                        return {"ok": False, "status": "recovery_required", "execution_id": execution_id, "residual": residual}
                    if reserve:
                        self._release(strategy, ordered)
                    self._write_execution(execution_id, strategy, intent, "compensated", payload)
                    return {"ok": False, "status": "compensated", "execution_id": execution_id}
                if not verify_protection(leg, result):
                    raise ExecutionRecoveryRequired(f"protective order verification failed for {leg['symbol']}")
            if persist_fills is not None:
                try:
                    persisted = persist_fills(filled)
                except Exception as exc:
                    persisted = False
                    persist_error = exc
                if persisted is not True:
                    reason = str(locals().get("persist_error", "caller-side persistence not confirmed"))
                    self._write_execution(execution_id, strategy, intent, "post_fill_recovery", payload,
                                           [{"leg": leg, "fill": result, "reason": reason} for leg, result in filled])
                    self.block("post-fill caller persistence requires recovery")
                    return {"ok": False, "status": "post_fill_recovery", "execution_id": execution_id}
            self._write_execution(execution_id, strategy, intent, "filled", payload)
            return {"ok": True, "status": "filled", "execution_id": execution_id, "fills": filled}
        except Exception as exc:
            residual = []
            for prior, prior_result in reversed(filled):
                try:
                    cres = compensate_leg(prior, prior_result)
                    if not cres or cres.get("confirmed") is False:
                        raise RuntimeError("compensation not confirmed")
                    self._write_step(execution_id, ordered.index(prior) + 1, prior, "compensated", result=cres)
                except Exception as cexc:
                    residual.append({"leg": prior, "fill": prior_result, "reason": str(cexc)})
            if not residual and reserve:
                self._release(strategy, ordered)
            self._write_execution(execution_id, strategy, intent, "recovery_required" if residual else "compensated", payload, residual or None)
            if residual:
                self.block(str(exc))
            return {"ok": False, "status": "recovery_required" if residual else "compensated", "execution_id": execution_id, "residual": residual, "reason": str(exc)}

    def pending(self):
        con = self._connect()
        try:
            rows = con.execute("SELECT * FROM executions WHERE status IN ('intent_persisted','started','recovery_required','post_fill_recovery') ORDER BY created_at").fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()

    def reconcile(self, *, position_lookup, compensation_lookup=None, resolve=None):
        """Reconcile durable pending intents; resolve may compensate or persist residuals."""
        out = []
        for row in self.pending():
            item = dict(row)
            item["payload"] = json.loads(item["payload"])
            item["residual"] = json.loads(item["residual"] or "null")
            if compensation_lookup and item["residual"]:
                item["compensation"] = compensation_lookup(item["residual"])
            item["positions"] = position_lookup(item["payload"])
            if resolve:
                decision = resolve(item)
                item["resolution"] = decision
                if isinstance(decision, dict) and decision.get("status") in {"filled", "compensated", "recovery_required"}:
                    self._write_execution(item["execution_id"], item["strategy"], item["intent"], decision["status"], item["payload"], decision.get("residual"))
            out.append(item)
        return out
