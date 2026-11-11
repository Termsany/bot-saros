"""reconciling the books with the exchange, the hourly stop audit, pending protection.
Moved from bot.py unchanged (2026-11-11): a bot-level name used in a function is read as bot.<name>, so the CLI's
settings, bot.py's state paths and the tests' patches on bot reach it. Import bot, not this module."""
import bot
import ccxt, pandas as pd, numpy as np, time, json, os, re, uuid, threading, http.server, socketserver, webbrowser
from datetime import datetime, timezone
from pathlib import Path
import strategies_advanced as adv
from backend.app.execution_safety import AmbiguousFill, authoritative_position_state, futures_net_pnl, linear_contracts_from_margin, normalize_filled_contracts
from backend.app import risk_manager as riskmgr
from backend.app.multi_leg_execution import MultiLegExecutionEngine
from backend.app import live_activation


def _live_label():
    return {"demo": "Demo", "testnet": "Testnet"}.get(bot.binance_env(), "حقيقي")

_ENTRY_BLOCK = {"reason": ""}   # set by reconcile_live each cycle: no new position while the exchange disagrees with us

def reconcile_live(state, ex):
    """Live only, every cycle before anything else: compare our positions with the exchange.
    Flat there = its stop filled (or someone closed it): record it and clean up. Unknown positions or a size
    mismatch block new entries and alert once — the account must be used by the bot alone (a sub-account)."""
    bot._ENTRY_BLOCK["reason"] = ""
    equity, equity_at = bot._equity_now(ex)
    if equity is None:
        bot._ENTRY_BLOCK["reason"] = "account equity unavailable — blocking new entries until the risk gate can size risk"
        bot.log(f"⚠️ {bot._ENTRY_BLOCK['reason']}")
    else:
        try:
            tripped, kill_reason = riskmgr.update_equity_and_check_kill_switch(bot.RISK_PATH, equity, equity_observed_at=equity_at, transfers=bot._TRANSFERS["rows"])
            if tripped:
                bot._ENTRY_BLOCK["reason"] = f"Central Risk Manager kill switch is tripped — {kill_reason}"
                bot.log(f"🛑 {bot._ENTRY_BLOCK['reason']}")
        except Exception as e:
            # Ledger unavailable: fail closed — block new entries rather than trade blind on risk state.
            bot._ENTRY_BLOCK["reason"] = f"risk ledger unavailable — blocking new entries: {e}"
            bot.log(f"⚠️ {bot._ENTRY_BLOCK['reason']}")
    try:
        live = {}
        positions = ex.fetch_positions()
        # An empty list is a NORMAL, valid answer — a flat account (no open positions) — not a bad read.
        # Only a non-list response (None, a dict error body ccxt didn't raise on, etc.) is actually
        # incomplete/untrustworthy and should block entries. Blocking on a merely-empty list meant a bot
        # could never take its very first trade from a clean account (every fresh demo/testnet/live account
        # starts flat) — discovered during Testnet E2E validation (Phase 1 of the live-trading roadmap).
        if not isinstance(positions, list):
            bot._ENTRY_BLOCK["reason"] = "exchange position snapshot is empty or incomplete"
            bot.log(f"⚠️ {bot._ENTRY_BLOCK['reason']}")
            bot.save_state(state)
            return
        for p in positions:
            c = p.get("contracts") if p.get("contracts") is not None else (p.get("info") or {}).get("positionAmt")
            if c and abs(float(c)) > 0: live[(p.get("symbol") or "").split(":")[0]] = abs(float(c))
    except Exception as e:
        bot._ENTRY_BLOCK["reason"] = f"مقدرناش نقرا الصفقات من المنصة: {e}"; bot.log(f"⚠️ {bot._ENTRY_BLOCK['reason']}"); return
    for sym, pos in list(state["positions"].items()):
        q = live.get(sym.split(":")[0])
        flat = state.setdefault("_flat_seen", {})
        if q:
            flat.pop(sym, None)
            # Position is still open on the exchange: opportunistically retry cancelling any stale
            # replacement stop left over from a prior SL amendment whose old-leg cancel was ambiguous
            # (covers restart recovery too, since this is durably persisted in pos["oco_ids"]).
            pending = (pos.get("oco_ids") or {}).get("sl_pending_cancel") or (pos.get("oco_ids") or {}).get("sl_pending_cleanup")
            pending_key = "sl_pending_cancel" if (pos.get("oco_ids") or {}).get("sl_pending_cancel") else "sl_pending_cleanup"
            if pending and pending.get("id"):
                try:
                    from backend.app.oco import cancel_oco_orders
                    if cancel_oco_orders(ex, sym, sl_id=pending["id"]) is True:
                        pos["oco_ids"].pop(pending_key, None)
                        bot.save_state(state)
                except Exception:
                    pass
        elif bot._exchange_position_qty(ex, sym) != 0.0:
            flat.pop(sym, None); continue                                   # the per-coin check disagrees (or failed): wait
        if not q:
            flat[sym] = flat.get(sym, 0) + 1
            if flat[sym] < 2: continue                                     # flat twice in a row before believing it
            flat.pop(sym, None)
            fills = []
            try:
                since = int(datetime.fromisoformat(pos["time"]).timestamp() * 1000)
                close_side = "sell" if pos.get("side", "long") == "long" else "buy"
                fills = [t for t in bot._trades_since(ex, sym, since) if t.get("side") == close_side and float(t.get("filled", t.get("amount", 0)) or 0) > 0]
            except Exception:
                fills = []
            if not fills:
                state.setdefault("recovery_required", {})[sym] = {"reason": "exchange flat but no authoritative closing fill", "at": datetime.now(timezone.utc).isoformat()}
                bot._ENTRY_BLOCK["reason"] = "exchange exit has no authoritative fill evidence"
                bot.save_state(state)
                continue
            fill_rows = []
            for fill in fills:
                try:
                    fq = float(fill.get("filled", fill.get("amount", 0)) or 0)
                    fp = float(fill.get("average") or fill.get("price"))
                    if fq > 0 and fp > 0:
                        fill_rows.append((fq, fp, fill))
                except (TypeError, ValueError):
                    continue
            total_filled = sum(x[0] for x in fill_rows)
            if total_filled + 1e-9 < float(pos.get("qty", 0)):
                state.setdefault("recovery_required", {})[sym] = {"reason": "closing fills are partial or incomplete", "filled": total_filled, "expected": pos.get("qty"), "at": datetime.now(timezone.utc).isoformat()}
                bot._ENTRY_BLOCK["reason"] = "partial closing fill requires recovery"
                bot.save_state(state)
                continue
            exit_px = sum(qty * px for qty, px, _ in fill_rows) / total_filled
            aggregate_fill = {"filled": total_filled, "price": exit_px, "fee": bot._summed_fee(f for _, _, f in fill_rows)}
            cs = bot._position_contract_size(pos)
            if cs is None:
                state.setdefault("recovery_required", {})[sym] = {"reason": "missing contract_size for realized PnL", "at": datetime.now(timezone.utc).isoformat()}
                bot.save_state(state)
                continue
            try:
                bot._refresh_fee_evidence(ex, sym, pos, aggregate_fill)
                bot._refresh_funding_evidence(ex, sym, pos)
            except Exception as e:
                state.setdefault("recovery_required", {})[sym] = {"reason": f"funding evidence unavailable: {e}", "at": datetime.now(timezone.utc).isoformat()}
                bot._ENTRY_BLOCK["reason"] = "funding evidence unavailable for live accounting"
                bot.save_state(state)
                continue
            pnl = futures_net_pnl(pos["entry"], exit_px, pos["qty"], cs, pos.get("side", "long"), fee_rate=bot._fee_rate(pos, required=True), funding_pnl=bot._funding_pnl(pos, required=True))
            by_hand = exit_px > float(pos.get("sl") or 0) * 1.01   # well above the stop: closed by hand in the Binance app
            why = "اتقفلت يدوي من Binance" if by_hand else "وقف الحماية اتنفذ على المنصة"
            bot.log(f"🔒 {sym}: {why} @ {exit_px:.6g} PnL {pnl:+.2f}")
            ids = pos.get("oco_ids") or {}
            try:
                cleanup_ok = bot._cancel_all_protective_orders(ex, sym, pos) if (ids.get("pos_id") or ids.get("sl") or ids.get("tp") or ids.get("sl_pending_cancel") or ids.get("sl_pending_cleanup")) else True
            except Exception:
                cleanup_ok = False
            if not cleanup_ok:
                state.setdefault("recovery_required", {})[sym] = {"reason": "protective cancellation unconfirmed after exchange flat", "at": datetime.now(timezone.utc).isoformat()}
                bot._ENTRY_BLOCK["reason"] = "protective cancellation requires recovery"
                bot.save_state(state)
                continue
            state["history"].append({"symbol": sym, "side": pos.get("side", "long"), "entry": pos["entry"], "exit": exit_px, "qty": pos["qty"], "pnl": pnl,
                "pnl_pct": pnl / (pos["entry"] * pos["qty"] * cs / max(1, int(pos.get("leverage", bot.CONFIG.get("leverage", 1))))) * 100, "reason": "قفل يدوي من Binance" if by_hand else "وقف المنصة", "time": datetime.now(timezone.utc).isoformat(),
                "type": "live", "opened": pos.get("time"), "rank": pos.get("rank")})
            state["stats"]["trades"] += 1; state["stats"]["pnl"] += float(pnl); state["stats"]["wins" if pnl > 0 else "losses"] += 1
            state["positions"].pop(sym, None); state["last_trade"][sym] = datetime.now(timezone.utc).isoformat()
            state.get("recovery_required", {}).pop(sym, None)
            bot.save_state(state)
            bot._release_position_risk(sym, pos)
        elif abs(q - float(pos["qty"])) > 0.02 * float(pos["qty"]):
            if sym not in state.setdefault("recovery_required", {}):
                state["recovery_required"][sym] = {"reason": f"الكمية على المنصة {q} مش {pos['qty']}", "at": datetime.now(timezone.utc).isoformat()}
                bot.notify(f"🚨 {sym}: الكمية على المنصة {q} مختلفة عن البوت {pos['qty']} — راجعها. البوت وقف أي دخول جديد.")
    bot._protect_pending(ex, state, live)
    bot._audit_stops(ex, state, live)
    mine = {k.split(":")[0] for k in state["positions"]}
    unknown = sorted(set(live) - mine - bot._held_by_other_strategies())
    if unknown:
        bot._ENTRY_BLOCK["reason"] = f"صفقات على المنصة البوت مفتحهاش: {', '.join(unknown)}"
        if state.get("_unknown_seen") != unknown:
            bot.notify(f"⚠️ {bot._ENTRY_BLOCK['reason']} — البوت مش هيفتح جديد لحد ما تتقفل. استخدم حساب فرعي للبوت لوحده.")
        state["_unknown_seen"] = unknown
    else:
        state.pop("_unknown_seen", None)
    bot.save_state(state)

STOP_AUDIT_S = 3600
AUDIT_REASON = "stop missing on the exchange (hourly stop check)"

def _audit_stops(ex, state, live, now=None):
    """reconcile_live, hourly (owner, 2026-11-08): every open position's recorded stop must still be on the exchange.
    A stop cancelled by hand in the Binance app, or dropped by the exchange, used to leave the position open with no
    protection while the bot's book still said "protected". Missing on two readings in a row (one read can lag; the
    second runs on the next cycle) = the position is marked sl_unverified, which stops new entries and makes the
    watchdog alert, plus a recovery_required entry and one Telegram message. Read only: it places and cancels nothing,
    a person decides. When the stop is seen again, its own mark is cleared (and nobody else's)."""
    now = now or datetime.now(timezone.utc)
    audit = state.setdefault("_stop_audit", {})
    pending = audit.get("missing") or {}
    try:
        recent = audit.get("at") and (now - datetime.fromisoformat(audit["at"])).total_seconds() < bot.STOP_AUDIT_S
    except (TypeError, ValueError):
        recent = False
    if recent and not pending:
        return
    from backend.app.oco import _owned_orders, _oco_id
    missing = {}
    for sym, pos in state["positions"].items():
        ids = pos.get("oco_ids") or {}
        want = {x for x in (ids.get("sl"), _oco_id(ids["pos_id"], "sl") if ids.get("pos_id") else None) if x}
        if not want or not live.get(sym.split(":")[0]) or pos.get("unprotected"):
            continue                                            # no stop of its own, flat, or already flagged
        if pos.get("sl_unverified") and not pos.get("stop_audit_missing"):
            continue                                            # the stop machinery is already handling this one
        try:
            found, complete = _owned_orders(ex, sym, want)
        except Exception:
            found, complete = {}, False
        if not complete:
            if sym in pending: missing[sym] = pending[sym]      # inconclusive: neither a miss nor a clear
            continue
        if found:
            if pos.pop("stop_audit_missing", None):
                pos.pop("sl_unverified", None)
                if (state.get("recovery_required") or {}).get(sym, {}).get("reason") == bot.AUDIT_REASON:
                    state["recovery_required"].pop(sym, None)
                bot.notify(f"✅ {sym}: وقف الخسارة رجع ظاهر على المنصة")
            continue
        missing[sym] = pending.get(sym, 0) + 1
        if missing[sym] >= 2 and not pos.get("stop_audit_missing"):
            pos["stop_audit_missing"] = now.isoformat(); pos["sl_unverified"] = True
            state.setdefault("recovery_required", {}).setdefault(sym, {"reason": bot.AUDIT_REASON, "at": now.isoformat()})
            bot.notify(f"🚨 {sym}: وقف الخسارة مش موجود على Binance (اتلغى؟). الصفقة مفتوحة من غير حماية، والبوت وقف أي دخول "
                   f"جديد. حط وقف بإيدك عند {pos.get('sl')} أو اقفل الصفقة.")
    audit["missing"] = {k: v for k, v in missing.items() if v < 2}
    if not audit["missing"]:
        audit["at"] = now.isoformat()
    bot.save_state(state)

def _expect_stop(state, symbol, side, sl, cid):
    """Before an entry order goes out: until its stop is confirmed, reconcile_live puts a reduceOnly stop on whatever
    the exchange holds for this coin (a crash between order and stop, a fill whose outcome was unclear, a stop the
    exchange refused). Saved before the order, so it survives a restart."""
    if sl is None: return
    state.setdefault("protect", {})[symbol] = {"side": side, "sl": float(sl), "cid": cid, "at": datetime.now(timezone.utc).isoformat()}
    bot.save_state(state)

def _stop_confirmed(state, symbol):
    (state.get("protect") or {}).pop(symbol, None)

def _protect_pending(ex, state, live):
    """reconcile_live, every live cycle: give each expected-but-unconfirmed position its stop.

    A flat exchange reading is only believed after TWO consecutive cycles (the sibling reconciliation
    loop above requires the same, since the exchange's readings sometimes lag) — tracked per entry in
    info['flat_seen']. Once believed, an entry whose stop was actually placed ('protected') must have
    that stop cancelled-and-confirmed-gone before the book entry is dropped: otherwise it is left live on
    the exchange forever and can close an unrelated later position on the same symbol."""
    book = state.get("protect") or {}
    if not book: return
    from backend.app.oco import place_oco_orders, cancel_oco_orders, _owned_orders, _oco_id
    for sym, info in list(book.items()):
        pos = state["positions"].get(sym)
        if pos and not pos.get("unprotected") and not pos.get("sl_unverified"):
            book.pop(sym, None); continue                       # recorded with its stop: nothing left to do
        q = live.get(sym.split(":")[0])
        if not q:
            info["flat_seen"] = info.get("flat_seen", 0) + 1
            if info["flat_seen"] < 2: continue                  # flat twice in a row before believing it
            if info.get("protected"):
                try:
                    cancelled = cancel_oco_orders(ex, sym, sl_id=_oco_id(info["cid"], "sl"))
                except Exception as exc:
                    cancelled = False; bot.log(f"⚠️ {sym}: إلغاء وقف الحماية بعد التصفية فشل: {exc}")
                if not cancelled: continue                      # unconfirmed cancel: keep the entry, retry next cycle
            book.pop(sym, None); continue                       # nothing on the exchange to protect any more
        info["flat_seen"] = 0
        if info.get("protected"): continue
        try:
            found, complete = _owned_orders(ex, sym, {_oco_id(info["cid"], "sl")})
            if not complete: continue                           # inconclusive read: not a green light, retry next cycle
            if found: ok = True                                 # placed before a crash: don't send a second one
            else:
                oco = place_oco_orders(ex, sym, info["side"], q, info["sl"], None, paper=False, pos_id=info["cid"])
                ok = not oco.get("protection_missing") and not oco.get("verify_failed")
        except Exception as exc:
            ok = False; bot.log(f"⚠️ {sym}: وقف الحماية فشل تاني: {exc}")
        if not ok: continue                                     # next cycle again
        info.update(protected=True, qty=q)
        if pos:
            pos["unprotected"] = False; pos["sl_unverified"] = False
            pos.setdefault("oco_ids", {}).update({"pos_id": info["cid"], "sl": _oco_id(info["cid"], "sl")})
        else:
            state.setdefault("recovery_required", {}).setdefault(sym, {"reason": "position on the exchange without a recorded entry", "qty": q, "at": datetime.now(timezone.utc).isoformat()})
        bot.notify(f"🛡️ {sym}: اتحط وقف على المنصة عند {info['sl']:.6g} لكمية {q} — الصفقة لسه محتاجة مراجعة")
    bot.save_state(state)

def _held_by_other_strategies():
    """Coins another strategy holds on this account, from the shared risk ledger (reserved, open or in recovery). Every
    live strategy runs as its own bot on the same account; without this each saw the others' positions as strangers
    and stopped entering. A position no strategy has in the ledger still blocks. Ledger unreadable: none (fail closed)."""
    me = bot._current_strategy_name()
    try:
        rows = riskmgr.load_risk_state(bot.RISK_PATH).get("open_risk") or {}
    except Exception:
        return set()
    return {str(r.get("symbol", "")).split(":")[0] for r in rows.values() if r.get("strategy") != me}

def _ipc_dir():
    """Folder shared with the backend (RAQM_IPC_DIR, e.g. /opt/raqm-ipc): live status out, close requests in."""
    d = os.getenv("RAQM_IPC_DIR", "").strip()
    return Path(d) if d else None

def _write_json_atomic(path, data):
    """New temp file with an unpredictable name (O_EXCL: never follows a link someone planted), then rename over the
    target (rename replaces a link instead of writing through it). mkstemp() defaults to mode 0600 (owner only);
    chmod to 0660 before the rename so the API (group raqmapi on the shared setgid dir) can read it too — the
    same convention risk_manager.py/live_activation.py already use for their sqlite files."""
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".w-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh: fh.write(json.dumps(data, ensure_ascii=False, default=str))
        try: os.chmod(tmp, 0o660)
        except OSError: pass
        os.replace(tmp, path)
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise
