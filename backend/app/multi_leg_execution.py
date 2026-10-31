"""Fail-closed durable execution engine for live baskets and pairs.

The engine deliberately knows nothing about a particular strategy or exchange.  The
caller supplies order, close, position and protection callbacks; this keeps paper
signal code unchanged while making every live workflow journaled and recoverable.
"""
from __future__ import annotations

import json
import hashlib
import uuid
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

    def _reserve(self, strategy, legs, equity, equity_observed_at=None, strategy_risk_share=None, strategies_sharing=None):
        fn = getattr(self.riskmgr, "pre_trade_gate_basket", None)
        if callable(fn):
            return fn(self.risk_path, strategy=strategy, legs=legs, equity_usdt=equity,
                      equity_observed_at=equity_observed_at, strategy_risk_share=strategy_risk_share,
                      strategies_sharing=strategies_sharing)
        reserved = []
        for leg in legs:
            ok, reason = self.riskmgr.pre_trade_gate(self.risk_path, strategy=strategy, **leg, equity_usdt=equity,
                                                     equity_observed_at=equity_observed_at,
                                                     strategy_risk_share=strategy_risk_share,
                                                     strategies_sharing=strategies_sharing)
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
    def _stable_id(strategy, intent, legs, cycle_token):
        identity = "|".join(f"{leg.get('symbol')}:{leg.get('side')}:{leg.get('action','entry')}:{leg.get('leg_id',leg.get('order',0))}"
                             for leg in sorted(legs, key=lambda x: (int(x.get('order', 0)), x['symbol'])))
        return "exec-" + hashlib.sha256(f"{strategy}|{intent}|{cycle_token}|{identity}".encode()).hexdigest()[:32]

    def execute(self, *, strategy, intent, legs, equity_usdt, execute_leg, compensate_leg,
                verify_protection, state=None, execution_id=None, reserve=True,
                persist_fills=None, cycle_token=None, unwind_failed_leg=None, equity_observed_at=None,
                strategy_risk_share=None, strategies_sharing=None):
        """Execute a basket. ``legs`` are sorted by caller-provided ``order`` then symbol.

        ``unwind_failed_leg(leg)`` is asked about an entry leg that raised: its order may have filled before the
        error (no fill evidence in time, a position read that failed). It must return {"confirmed": True} only when
        the leg is proven flat (unfilled, or closed again); anything else keeps the leg as residual exposure."""
        if not legs:
            raise ValueError("basket must contain at least one leg")
        ordered = sorted(legs, key=lambda x: (int(x.get("order", 0)), x["symbol"]))
        # Reuse only an explicitly supplied cycle or an unfinished durable cycle.
        # A terminal cycle must never be resurrected by reusing a fixed intent.
        if execution_id is None and cycle_token is None:
            con = self._connect()
            try:
                row = con.execute("SELECT execution_id,payload FROM executions WHERE strategy=? AND intent=? AND status IN ('intent_persisted','started','recovery_required','post_fill_recovery') ORDER BY updated_at DESC LIMIT 1", (strategy, intent)).fetchone()
                if row:
                    execution_id = row["execution_id"]
                    try: cycle_token = json.loads(row["payload"]).get("cycle_token")
                    except (TypeError, ValueError): pass
            finally:
                con.close()
        cycle_token = cycle_token or uuid.uuid4().hex
        execution_id = execution_id or self._stable_id(strategy, intent, ordered, cycle_token)
        for leg in ordered:
            leg.setdefault("client_order_id", "raqm-" + hashlib.sha256(
                f"{strategy}|{intent}|{cycle_token}|{leg['symbol']}|{leg.get('side')}|{leg.get('action','entry')}|{leg.get('leg_id',leg.get('order',0))}".encode()
            ).hexdigest()[:27])
        existing = self._connect()
        try:
            row = existing.execute("SELECT status,payload FROM executions WHERE execution_id=?", (execution_id,)).fetchone()
            if row and row["status"] == "filled":
                return {"ok": True, "status": "filled", "execution_id": execution_id, "fills": [] , "reused": True}
        finally:
            existing.close()
        payload = {"legs": ordered, "intent": intent, "cycle_token": cycle_token}
        self._write_execution(execution_id, strategy, intent, "intent_persisted", payload)
        ok, reason = (True, None) if not reserve else self._reserve(strategy, ordered, equity_usdt, equity_observed_at,
                                                                   strategy_risk_share, strategies_sharing)
        if not ok:
            self._write_execution(execution_id, strategy, intent, "risk_blocked", payload, {"reason": reason})
            return {"ok": False, "status": "risk_blocked", "reason": reason, "execution_id": execution_id}
        filled = []
        # an exit-only basket: every leg is an independent reduce-only close. One that fails is left as residual and
        # the others are still tried and booked — stopping at the first failure left a rebalance half-closed (a
        # lopsided, directional book) until a person stepped in
        all_exits = all(leg.get("action", "entry") == "exit" for leg in ordered)
        exit_failures = []
        try:
            for n, leg in enumerate(ordered, 1):
                self._write_step(execution_id, n, leg, "started")
                try:
                    result = execute_leg(leg)
                    requested = leg.get("requested_qty", leg.get("qty"))
                    # Unit callers may omit exchange quantity metadata; the live adapter always sets it.
                    if requested is None:
                        requested = float(result.get("qty", 0) or 0) if result else 0.0
                    if requested <= 0:
                        raise RuntimeError("live leg is missing a positive requested_qty")
                    actual = float(result.get("qty", 0) or 0) if result else 0.0
                    if not result or actual <= 0:
                        raise RuntimeError("leg returned no filled quantity")
                    authoritative = result.get("authoritative_qty", actual) if result else None
                    evidence = result.get("authoritative_fill_qty", result.get("fill_evidence_qty", actual)) if result else None
                    if authoritative is None or evidence is None:
                        raise RuntimeError("authoritative exchange fill/position evidence is missing")
                    if actual + 1e-9 < float(requested) or float(authoritative) + 1e-9 < float(requested) or float(evidence) + 1e-9 < float(requested):
                        raise RuntimeError(f"partial fill: requested={requested}, filled={actual}")
                    filled.append((leg, result))
                    self._write_step(execution_id, n, leg, "filled", result=result)
                except Exception as exc:
                    self._write_step(execution_id, n, leg, "failed", error=exc)
                    if all_exits:
                        exit_failures.append({"leg": leg, "fill": None, "reason": f"exit leg failed: {exc}"})
                        continue
                    residual = []
                    if leg.get("action", "entry") == "exit":
                        # the position this exit leg was closing is still open (or unknown): it is the exposure
                        residual.append({"leg": leg, "fill": None, "reason": f"exit leg failed: {exc}"})
                    elif unwind_failed_leg is not None:
                        try:
                            uw = unwind_failed_leg(leg)
                            if not uw or uw.get("confirmed") is not True:
                                raise RuntimeError((uw or {}).get("reason") or "failed leg not proven flat")
                            self._write_step(execution_id, n, leg, "compensated", result=uw)
                        except Exception as uexc:
                            residual.append({"leg": leg, "fill": None, "reason": f"leg failed ({exc}); {uexc}"})
                    done_exits = [(prior, r) for prior, r in filled if prior.get("action", "entry") == "exit"]
                    for prior, prior_result in reversed(filled):
                        if prior.get("action", "entry") == "exit":
                            continue          # really closed — booked below, not reopened
                        try:
                            cres = compensate_leg(prior, prior_result)
                            if not cres or cres.get("confirmed") is False:
                                raise RuntimeError("compensation not confirmed")
                            self._write_step(execution_id, ordered.index(prior) + 1, prior, "compensated", result=cres)
                        except Exception as cexc:
                            residual.append({"leg": prior, "fill": prior_result, "reason": str(cexc)})
                    if done_exits and persist_fills is not None:
                        try:
                            if persist_fills(done_exits) is not True: raise RuntimeError("closed exit legs not persisted")
                        except Exception as pexc:
                            residual.extend({"leg": prior, "fill": r, "reason": f"closed, not booked: {pexc}"} for prior, r in done_exits)
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
            if exit_failures:
                residual = list(exit_failures)
                if filled and persist_fills is not None:
                    try:
                        if persist_fills(filled) is not True: raise RuntimeError("closed exit legs not persisted")
                    except Exception as pexc:
                        residual.extend({"leg": leg, "fill": r, "reason": f"closed, not booked: {pexc}"} for leg, r in filled)
                if all("unchanged" in str(item["reason"]) for item in residual):
                    # nothing happened on the exchange for the legs left: the caller simply tries them again. A
                    # recovery row here stayed pending, re-marked the coin after the retry had closed it, and blocked
                    # every entry for good
                    self._write_execution(execution_id, strategy, intent, "exit_retry", payload, residual)
                    return {"ok": False, "status": "exit_retry", "execution_id": execution_id, "residual": residual, "fills": filled}
                self._write_execution(execution_id, strategy, intent, "recovery_required", payload, residual)
                con = self._connect()
                try:
                    con.execute("INSERT OR REPLACE INTO execution_residuals VALUES(?,?,?,?,?)",
                                (execution_id, json.dumps(residual, default=str), "open", _now(), _now()))
                finally:
                    con.close()
                return {"ok": False, "status": "recovery_required", "execution_id": execution_id, "residual": residual,
                        "fills": filled}
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
                    return {"ok": False, "status": "post_fill_recovery", "execution_id": execution_id,
                            "residual": [{"leg": leg, "fill": result, "reason": reason} for leg, result in filled]}
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
                    if decision.get("status") == "recovery_required":
                        con = self._connect()
                        try:
                            con.execute("INSERT OR REPLACE INTO execution_residuals VALUES(?,?,?,?,?)", (item["execution_id"], json.dumps(decision.get("residual") or [], default=str), "open", _now(), _now()))
                        finally:
                            con.close()
            out.append(item)
        return out
