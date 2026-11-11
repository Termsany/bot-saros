"""the multi-leg basket engine, single-leg live entries and exits, stop guards, simple status.
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


def _phase2_engine(state):
    return MultiLegExecutionEngine(bot.STATE_PATH, risk_manager=riskmgr, risk_path=bot.RISK_PATH,
                                   save_state=bot.save_state,
                                   block=lambda reason: bot._ENTRY_BLOCK.__setitem__("reason", str(reason)))


def _phase2_live_basket(ex, state, strategy, intent, legs, *, reserve=True):
    """Execute a deterministic live basket and leave all ambiguity in recovery."""
    if bot.CONFIG.get("paper_trading"):
        raise RuntimeError("Phase 2 live adapter called while paper trading is enabled")
    if bot.binance_env() == "live" and os.getenv("ALLOW_LIVE_TRADING", "").strip().lower() != "true":
        bot._ENTRY_BLOCK["reason"] = "ALLOW_LIVE_TRADING is not enabled"; return None
    is_exit = bool(legs) and all(leg.get("action", "entry") == "exit" for leg in legs)
    # pending journal rows are settled first, whatever blocks this call: an early return here left a flat basket in
    # recovery for good (stale stop, reservations held on every coin of it)
    engine = bot._phase2_engine(state); fills = {}
    cycle_key = f"{strategy}:{intent}"
    cycles = state.setdefault("_execution_cycles", {})
    def _lookup_pending(payload):
        symbols = [leg.get("symbol") for leg in payload.get("legs", []) if leg.get("symbol")]
        try:
            return ex.fetch_positions(symbols) if symbols else []
        except Exception as exc:
            return {"error": str(exc), "authoritative": False}
    def _resolve_pending(item):
        positions = item.get("positions")
        if isinstance(positions, dict) and positions.get("error"):
            return {"status": "recovery_required", "residual": [{"execution_id": item["execution_id"], "reason": positions["error"], "positions": positions}]}
        residual = [{"execution_id": item["execution_id"], "reason": "restart reconciliation requires exchange-confirmed compensation or manual residual recovery", "positions": positions, "legs": item["payload"].get("legs", [])}]
        if not positions or all(float((p.get("contracts") if isinstance(p, dict) else 0) or 0) == 0 for p in (positions or [])):
            from backend.app.oco import cancel_oco_orders
            entry_legs = [leg for leg in item["payload"].get("legs", []) if leg.get("action", "entry") == "entry" and leg.get("client_order_id")]
            try:
                stops_gone = all(cancel_oco_orders(ex, leg["symbol"], pos_id=leg["client_order_id"]) is True for leg in entry_legs)
            except Exception:
                stops_gone = False
            if not stops_gone:   # flat, but a leftover reduceOnly stop could close a later position on that coin
                return {"status": "recovery_required", "residual": [{**residual[0], "reason": "flat, but the legs' own stops could not be confirmed cancelled"}]}
            for leg in entry_legs:   # nothing is open any more: a reservation left here would block the coin for good
                try: riskmgr.rollback_reservation(bot.RISK_PATH, strategy=item["strategy"], symbol=leg["symbol"])
                except Exception as exc: bot.log(f"⚠️ {leg['symbol']}: rollback reservation: {exc}")
            return {"status": "compensated", "residual": []}
        return {"status": "recovery_required", "residual": residual}
    pending = engine.reconcile(position_lookup=_lookup_pending, resolve=_resolve_pending)
    recovery = state.setdefault("recovery_required", {})
    for row in pending:
        if (row.get("resolution") or {}).get("status") == "compensated":
            recovery.pop(f"execution:{row['execution_id']}", None)
            token = (row.get("payload") or {}).get("cycle_token")
            for key in [k for k, v in cycles.items() if v == token]: cycles.pop(key, None)
            for key in [k for k, v in recovery.items() if isinstance(v, dict) and v.get("execution_id") == row["execution_id"]]:
                recovery.pop(key, None)
    unresolved = [row for row in pending if (row.get("resolution") or {}).get("status") == "recovery_required"]
    if unresolved:
        if any(f"execution:{row['execution_id']}" not in recovery for row in unresolved):
            bot.notify(f"🚨 {strategy}: سلة لسه مفتوحة بعد ما البوت رجع ({', '.join(r['intent'] for r in unresolved)}) — راجع المنصة")
        for row in unresolved:
            recovery[f"execution:{row['execution_id']}"] = {"reason": "restart reconciliation residual persisted", "residual": (row.get("resolution") or {}).get("residual"), "at": row["updated_at"]}
        bot._ENTRY_BLOCK["reason"] = "durable live execution residual requires recovery"; bot.save_state(state)
        if not is_exit: return None   # an exit only reduces exposure: a residual elsewhere must not trap open positions
    elif pending:
        bot.save_state(state)
    if not is_exit:
        activation_ok, activation_reason = bot._live_activation_gate(strategy)
        if not activation_ok:
            bot._ENTRY_BLOCK["reason"] = f"live activation blocked — {activation_reason}"; return None
    if bot._ENTRY_BLOCK.get("reason") and not is_exit:
        return None
    if state.get("recovery_required") and not is_exit:
        return None
    small = [leg["symbol"] for leg in legs if leg.get("action", "entry") == "entry" and not bot._meets_min_order(ex, leg["symbol"], leg["margin"])]
    if small:   # Binance would refuse these legs after the others filled: the basket would only be unwound
        bot.log(f"⏸️ {intent}: المارجن أقل من أقل أمر على Binance لـ {', '.join(small)} — السلة مش هتدخل (ارفع المارجن)")
        warned = state.setdefault("min_order_warned", {})
        if warned.get(intent) != datetime.now(timezone.utc).date().isoformat():
            warned[intent] = datetime.now(timezone.utc).date().isoformat(); bot.save_state(state)
            bot.notify(f"⚠️ {strategy}: السلة مش هتدخل — المارجن أقل من أقل أمر على Binance لـ {', '.join(small)}. ارفع المارجن من الداشبورد.")
        return None
    backoff = (state.get("basket_backoff") or {}).get(f"{strategy}:{intent}")
    if backoff and not is_exit and datetime.now(timezone.utc) < datetime.fromisoformat(backoff["until"]):
        return None   # this basket failed and was unwound lately: not again every poll
    held = [leg["symbol"] for leg in legs if leg["symbol"] in (state.get("recovery_required") or {})]
    if is_exit and held:   # a leg whose state is in doubt is left to a person (its exchange stop stays); the rest go
        bot.log(f"⏸️ خروج {intent}: متأجل لحد المراجعة — {', '.join(held)}")
        legs = [leg for leg in legs if leg["symbol"] not in held]
        if not legs: return None
    held_exit = list(held) if is_exit else []
    equity, equity_at = bot._equity_now(ex)
    if equity is None and not is_exit:
        bot._ENTRY_BLOCK["reason"] = "account equity unavailable — blocking new entries"; return None
    if not is_exit:
        tripped, reason = riskmgr.update_equity_and_check_kill_switch(bot.RISK_PATH, equity, equity_observed_at=equity_at, transfers=bot._TRANSFERS["rows"])
        if tripped:
            bot._ENTRY_BLOCK["reason"] = f"Central Risk Manager kill switch is tripped — {reason}"; return None
    equity = equity or 1.0
    # Minted only after reconcile() above had a chance to clear a stale token for this cycle_key: reading
    # it any earlier would reuse a crash-recovered attempt's already-cleared token for this new one.
    cycle_token = cycles.setdefault(cycle_key, uuid.uuid4().hex)
    def execute_leg(leg):
        if leg.get("action", "entry") == "exit":
            result = bot.close_live_position(ex, leg["symbol"], leg["position"], leg.get("price"))
            if result.get("unchanged"): raise RuntimeError(f"unchanged: {result.get('error')}")
            bot._require_verified_close(result)
            fills[leg["symbol"]] = result; return {**result, "qty": result.get("qty", leg["position"].get("qty"))}
        bot._expect_stop(state, leg["symbol"], leg["side"], leg.get("sl"), leg["client_order_id"])   # a crash from here on: reconcile_live protects it
        result = bot.place_order(ex, leg["symbol"], leg["side"], leg["margin"], leg["price"], client_order_id=leg["client_order_id"])
        if float(result.get("qty", 0) or 0) <= 0: raise RuntimeError("leg returned no filled quantity")
        from backend.app.oco import place_oco_orders
        oco = place_oco_orders(ex, leg["symbol"], leg["side"], result["qty"], leg.get("sl"), leg.get("tp"), paper=False, pos_id=leg["client_order_id"])
        result = {**result, "oco": oco}
        authoritative_qty = bot._exchange_position_qty(ex, leg["symbol"], side=leg["side"])
        if authoritative_qty is None: raise RuntimeError("authoritative exchange position evidence unavailable")
        result["authoritative_qty"] = authoritative_qty
        result["authoritative_fill_qty"] = float(result.get("qty", 0) or 0)
        fills[leg["symbol"]] = result; return result
    def unwind_failed_leg(leg):
        """The leg raised after its order may have gone through. Flat + order not filled = nothing to undo;
        an open position on the exchange is closed and its stop removed; anything unclear stays residual."""
        q = bot._exchange_position_qty(ex, leg["symbol"], side=leg["side"])
        def unclear(reason):   # whatever is open there gets a stop now, and again every cycle until it has one
            q2, protected = bot._protect_unrecorded_entry(ex, leg["symbol"], leg["side"], leg.get("sl"), leg["client_order_id"])
            bot.notify(f"🚨 {leg['symbol']}: رجل في سلة {strategy} وقعت ومش متأكدين من حالتها ({reason}) — " +
                   (f"اتحط وقف طوارئ ({q2})" if protected else "البوت هيحاول يحط وقف كل دورة") + ". راجع المنصة.")
            return {"confirmed": False, "reason": reason}
        if q is None: return unclear("position unknown after the leg failed")
        if float(q) == 0:
            flat_ok, why = bot._entry_failed_flat(ex, leg["symbol"], leg["client_order_id"], side=leg["side"])
            if flat_ok: bot._stop_confirmed(state, leg["symbol"]); return {"confirmed": True, "flat": True}
            return unclear(f"not proven flat: {why}")
        try:
            out = compensate(leg, {"qty": q, "price": leg["price"]})
        except Exception as exc:
            return unclear(f"closing the failed leg: {exc}")
        return out if out.get("confirmed") else unclear(out.get("reason") or "unwind not confirmed")
    def compensate(leg, result):
        if leg.get("action", "entry") == "exit": return {"confirmed": False, "reason": "closed exit leg cannot be compensated automatically"}
        close_side = "close_long" if leg["side"] == "long" else "close_short"
        closed = bot.place_order(ex, leg["symbol"], close_side, 0, result.get("price", leg["price"]), close_qty=result.get("qty"), client_order_id=f"{leg['client_order_id']}-c"[:36])
        q = bot._exchange_position_qty(ex, leg["symbol"], side=leg["side"])
        if q is None or float(q or 0) != 0: raise RuntimeError("compensating close outcome ambiguous")
        # the unwound leg's own stop/target are still on the exchange: left there, a reduceOnly stop would close the
        # next position on this coin at a stale price (found by scripts/demo_e2e.py)
        try:
            from backend.app.oco import cancel_oco_orders
            cancelled = cancel_oco_orders(ex, leg["symbol"], pos_id=leg["client_order_id"]) is True
            cancel_error = None if cancelled else "not confirmed"
        except Exception as exc:
            cancelled, cancel_error = False, exc
        if not cancelled:   # flat, but the leg stays residual until its stop is confirmed gone (restart reconciliation)
            bot.log(f"⚠️ {leg['symbol']}: الرجل اتقفلت بس أوامر الحماية بتاعتها ما اتلغتش: {cancel_error}")
            bot.notify(f"⚠️ {leg['symbol']}: رجل اتقفلت تلقائياً بس أمر الوقف بتاعها ممكن يكون لسه على المنصة — راجعه")
            return {"confirmed": False, "reason": f"leg closed but its stop is not confirmed cancelled: {cancel_error}", "close": closed}
        bot._stop_confirmed(state, leg["symbol"])
        return {"confirmed": True, "close": closed}
    for leg in legs:
        if leg.get("action", "entry") == "exit":
            leg["requested_qty"] = float(leg["position"]["qty"])
        else:
            meta = bot._contract_meta(ex, leg["symbol"])
            requested = linear_contracts_from_margin(leg["margin"], int(bot.CONFIG.get("leverage", 2)), leg["price"], meta["contract_size"])
            try: requested = float(ex.amount_to_precision(leg["symbol"], requested))
            except Exception: requested = float(requested)
            if requested <= 0: raise RuntimeError(f"invalid requested quantity for {leg['symbol']}")
            leg["requested_qty"] = requested
    def _persist_fills(filled):
        for leg, fill in filled:
            sym = leg["symbol"]
            if leg.get("action", "entry") == "exit":
                pos = leg["position"]; cs = bot._position_contract_size(pos)
                try:
                    pnl = futures_net_pnl(pos["entry"], fill["price"], fill["qty"], cs, pos.get("side", "long"),
                                          fee_rate=bot._fee_rate(pos, required=True), funding_pnl=bot._funding_pnl(pos, required=True))
                except Exception as exc:   # the close is real: book it; only its PnL is unknown
                    pnl = None; bot.log(f"⚠️ {sym}: PnL الخروج مش متحسب ({exc})")
                state["history"].append({"symbol": sym, "side": pos.get("side", "long"), "entry": pos["entry"], "exit": fill["price"],
                    "qty": fill["qty"], "pnl": pnl, "reason": intent, "time": datetime.now(timezone.utc).isoformat(), "type": "live",
                    "opened": pos.get("time")})
                if pnl is not None:
                    st = state["stats"]; st["trades"] += 1; st["pnl"] += float(pnl); st["wins" if pnl > 0 else "losses"] += 1
                state["positions"].pop(sym, None)
                state["last_trade"][sym] = datetime.now(timezone.utc).isoformat()
                bot._closed_cleanly(state, sym)
                bot.save_state(state)
                bot._release_position_risk(sym, pos)
                continue
            oco = fill.get("oco") or {}
            state["positions"][sym] = {"side": leg["side"], "entry": fill["price"], "qty": fill["qty"], "cost": fill.get("cost"),
                "notional": fill.get("notional"), "contract_size": fill.get("contract_size"), "contract_size_verified": fill.get("contract_size_verified", False),
                "entry_fee_rate": fill.get("entry_fee_rate"), "entry_fee_cost": fill.get("entry_fee_cost"), "leverage": fill.get("leverage", bot.CONFIG.get("leverage", 2)),
                "time": datetime.now(timezone.utc).isoformat(), "sl": leg.get("sl"), "tp": leg.get("tp"), "clientOrderId": leg["client_order_id"],
                "oco_ids": {"pos_id": leg["client_order_id"], "sl": oco.get("sl_id"), "tp": oco.get("tp_id")}, "strategy": strategy, **(leg.get("extra") or {})}
            riskmgr.register_open_risk(bot.RISK_PATH, strategy=strategy, symbol=sym, side=leg["side"], risk_usdt=leg["risk_usdt"],
                notional_usdt=leg["notional_usdt"], correlation_group=leg.get("correlation_group"))
            bot._stop_confirmed(state, sym)
        bot.save_state(state)
        if len(filled) == len(legs): cycles.pop(cycle_key, None)   # partial (closed exits of a failed basket): keep the cycle
        return True
    def protected(leg, result):
        if leg.get("action", "entry") == "exit": return True
        oco = result.get("oco") or {}; return not (oco.get("protection_missing") or oco.get("verify_failed") or oco.get("sl_unverified"))
    result = engine.execute(strategy=strategy, intent=intent, legs=legs, equity_usdt=equity,
                            equity_observed_at=equity_at, strategy_risk_share=bot._live_risk_share(strategy),
                            strategies_sharing=bot._strategies_sharing(), execute_leg=execute_leg,
                            compensate_leg=compensate, verify_protection=protected, state=state, reserve=reserve,
                            persist_fills=_persist_fills, cycle_token=cycle_token, unwind_failed_leg=unwind_failed_leg)
    if result.get("status") in ("compensated", "risk_blocked"):
        cycles.pop(cycle_key, None); bot.save_state(state)
    if held_exit and result.get("status") == "filled":
        # the rest closed, but a leg under review is still open: callers must not treat the basket (a ratio pair, a
        # rebalance) as closed — the pair was dropped and its held leg left with no strategy managing it
        result = {**result, "status": "held", "held": held_exit}
    key = f"{strategy}:{intent}"
    if result.get("status") == "compensated" and not is_exit:
        # unwound: wait before the same basket again (1h, 2h, 4h ...), and after 3 in a row stop and ask a person —
        # it used to be sent again every poll, buying and market-closing the legs each minute
        b = state.setdefault("basket_backoff", {}).get(key) or {"count": 0}
        b["count"] += 1; b["until"] = (datetime.now(timezone.utc) + pd.Timedelta(hours=2 ** (b["count"] - 1))).isoformat()
        state["basket_backoff"][key] = b
        if b["count"] >= 3:
            state.setdefault("recovery_required", {})[f"basket:{key}"] = {"reason": f"basket unwound {b['count']} times in a row", "at": datetime.now(timezone.utc).isoformat()}
        bot.save_state(state)
        bot.notify(f"⚠️ {strategy}: سلة الدخول اتلغت (رجل فشلت والباقي اتقفل) — محاولة {b['count']}" + ("، البوت وقف ومحتاج مراجعة" if b["count"] >= 3 else f"، هيحاول تاني بعد {2 ** (b['count'] - 1)} ساعة"))
    elif result.get("status") == "filled":
        (state.get("basket_backoff") or {}).pop(key, None)
        (state.get("recovery_required") or {}).pop(f"execution:{result.get('execution_id')}", None); bot.save_state(state)
    if result.get("status") == "exit_retry":
        bot.notify(f"⚠️ {strategy}: {intent} — خروج ما اتنفذش ({', '.join(i['leg']['symbol'] for i in result.get('residual') or [])}), هيتعاد الدورة الجاية")
    if result.get("status") in ("recovery_required", "post_fill_recovery"):
        locked = []
        for item in result.get("residual", []) or []:
            sym = item["leg"]["symbol"]; leg = item["leg"]
            if leg.get("action", "entry") == "exit" and "unchanged" in str(item.get("reason", "")):
                continue   # nothing happened on the exchange: the next exit of this coin retries it
            state.setdefault("recovery_required", {})[sym] = {"reason": item.get("reason"), "execution_id": result.get("execution_id"), "at": datetime.now(timezone.utc).isoformat()}
            locked.append(sym)
        bot.save_state(state)
        if result.get("status") == "post_fill_recovery":
            bot.notify(f"🚨 {strategy}: {intent} — الأوامر اتنفذت بس ما اتسجلتش ({', '.join(locked)}). راجع المنصة.")
        else:
            bot.notify(f"🚨 {strategy}: {intent} — " + (f"محتاج مراجعة: {', '.join(locked)}" if locked else "خروج ما اتنفذش، هيتعاد") + ". راجع المنصة.")
    return result


def _phase2_leg(symbol, side, margin, price, sl, tp, strategy, order=0, extra=None):
    lev = int(bot.CONFIG.get("leverage", 2))
    return {"symbol": symbol, "side": side, "margin": margin, "price": price, "sl": sl, "tp": tp,
            "risk_usdt": bot._estimate_trade_risk_usdt(margin, lev, price, sl), "notional_usdt": margin * lev,
            "correlation_group": bot._correlation_group(symbol), "strategy": strategy, "order": order, "extra": extra or {}}


def _protect_unrecorded_entry(ex, symbol, side, sl, cid):
    """An entry raised but the exchange shows a position: put a reduceOnly stop on the exchange quantity now. It can
    only shrink the position, so it is safe even though the fill isn't recorded; the position stays in recovery.
    Returns the exchange quantity (None = unknown, 0 = flat) and whether a stop is on the exchange."""
    q = bot._exchange_position_qty(ex, symbol, side=side)
    if not q or sl is None: return q, False
    try:
        from backend.app.oco import place_oco_orders
        oco = place_oco_orders(ex, symbol, side, q, sl, None, paper=False, pos_id=cid)
        return q, not oco.get("protection_missing") and not oco.get("verify_failed")
    except Exception as exc:
        bot.log(f"⚠️ {symbol}: وقف الطوارئ فشل: {exc}"); return q, False

def _single_leg_live_entry(ex, state, symbol, side, margin, price, sl, tp, strategy, extra=None):

    """Fail-closed single-leg live entry shared by the Phase 1 adapters."""
    if bot.CONFIG.get("paper_trading"):
        raise RuntimeError("live adapter called while paper trading is enabled")
    if bot.binance_env() == "live" and os.getenv("ALLOW_LIVE_TRADING", "").strip().lower() != "true":
        bot._ENTRY_BLOCK["reason"] = "ALLOW_LIVE_TRADING is not enabled"
        return None
    activation_ok, activation_reason = bot._live_activation_gate(strategy)
    if not activation_ok:
        bot._ENTRY_BLOCK["reason"] = f"live activation blocked — {activation_reason}"
        return None
    if bot._ENTRY_BLOCK.get("reason") or state.get("recovery_required"):
        return None
    if not bot._meets_min_order(ex, symbol, margin):
        bot.log(f"⏸️ {symbol}: المارجن {margin:.2f}$ × {bot.CONFIG.get('leverage', 2)} أقل من أقل أمر على Binance — مفيش دخول (ارفع المارجن)"); return None
    refused = state.get("stop_refused") or {}
    if symbol in refused and datetime.now(timezone.utc) - datetime.fromisoformat(refused[symbol]) < pd.Timedelta(days=1):
        return None   # the exchange refused this coin's stop today: buying again would only buy, refuse, sell again
    equity, equity_at = bot._equity_now(ex)
    if equity is None:
        bot._ENTRY_BLOCK["reason"] = "account equity unavailable — blocking new entries"
        return None
    try:
        tripped, reason = riskmgr.update_equity_and_check_kill_switch(bot.RISK_PATH, equity, equity_observed_at=equity_at, transfers=bot._TRANSFERS["rows"])
    except Exception as exc:
        bot._ENTRY_BLOCK["reason"] = f"risk ledger unavailable — blocking new entries: {exc}"
        return None
    if tripped:
        bot._ENTRY_BLOCK["reason"] = f"Central Risk Manager kill switch is tripped — {reason}"
        return None
    leverage = int(bot.CONFIG.get("leverage", 1))
    risk_usdt = bot._estimate_trade_risk_usdt(margin, leverage, price, sl)
    allowed, reason = riskmgr.pre_trade_gate(
        bot.RISK_PATH, strategy=strategy, symbol=symbol, side=side,
        risk_usdt=risk_usdt, notional_usdt=margin * leverage,
        equity_usdt=equity, equity_observed_at=equity_at,
        correlation_group=bot._correlation_group(symbol),
        strategy_risk_share=bot._live_risk_share(strategy), strategies_sharing=bot._strategies_sharing())
    if not allowed:
        bot.log(f"⛔ {symbol} رفض بوابة المخاطر المركزية — {reason}")
        return None
    cid = "raqm-" + uuid.uuid4().hex[:27]   # per attempt; pending_orders keeps it across a crash
    state.setdefault("pending_orders", {})[symbol] = cid
    bot._expect_stop(state, symbol, side, sl, cid)
    try:
        res = bot.place_order(ex, symbol, side, margin, price, client_order_id=cid)
        if float(res.get("qty", 0) or 0) <= 0:
            raise RuntimeError("entry returned no filled quantity")
    except Exception as exc:
        try:
            flat_ok, why = bot._entry_failed_flat(ex, symbol, cid, side=side)
            if flat_ok:
                riskmgr.rollback_reservation(bot.RISK_PATH, strategy=strategy, symbol=symbol)
                state["pending_orders"].pop(symbol, None); bot._stop_confirmed(state, symbol); bot.save_state(state)
                return None
            riskmgr.mark_reservation_recovery(bot.RISK_PATH, strategy=strategy, symbol=symbol, reason=f"entry outcome unknown: {why}")
        except Exception:
            pass
        q, protected = bot._protect_unrecorded_entry(ex, symbol, side, sl, cid)
        state.setdefault("recovery_required", {})[symbol] = {"cid": cid, "reason": f"entry outcome unknown: {exc}", "qty": q,
                                                             "emergency_stop": protected, "at": datetime.now(timezone.utc).isoformat()}
        bot._ENTRY_BLOCK["reason"] = "live entry outcome requires recovery"
        state["pending_orders"].pop(symbol, None); bot.save_state(state)
        bot.notify(f"🚨 {symbol}: أمر الدخول رجّع خطأ ومش متأكدين من نتيجته — " +
               (f"الصفقة ظاهرة على المنصة ({q}) واتحط لها وقف طوارئ عند {sl:.6g}" if protected else
                f"الصفقة ظاهرة على المنصة ({q}) ومن غير وقف — اقفلها يدوي" if q else "راجع المنصة") +
               ". البوت وقف أي دخول جديد.")
        return None
    pos = {"side": side, "entry": res["price"], "qty": res["qty"], "cost": res["cost"],
           "notional": res.get("notional"), "contract_size": res.get("contract_size"),
           "contract_size_verified": res.get("contract_size_verified", False),
           "entry_fee_rate": res.get("entry_fee_rate"), "entry_fee_cost": res.get("entry_fee_cost"),
           "leverage": res.get("leverage", leverage), "time": datetime.now(timezone.utc).isoformat(),
           "sl": sl, "tp": tp, "breakeven": False, "clientOrderId": cid,
           "oco_ids": {"pos_id": cid}, "strategy": strategy, **(extra or {})}
    try:
        from backend.app.oco import place_oco_orders
        oco = place_oco_orders(ex, symbol, side, res["qty"], sl, tp, paper=False, pos_id=cid)
    except Exception as exc:
        oco = {"protection_missing": True, "sl_error": str(exc)}
    pos["oco_ids"].update({"sl": oco.get("sl_id"), "tp": oco.get("tp_id")})
    state["pending_orders"].pop(symbol, None)
    if not oco.get("protection_missing") and not oco.get("verify_failed"): bot._stop_confirmed(state, symbol)
    if oco.get("protection_missing"):
        try:
            closed = bot.close_live_position(ex, symbol, pos, price)
            bot._require_verified_close(closed); close_error = None
        except Exception as exc:
            close_error = exc
        if close_error is None:   # the exchange refused the stop and the position is verified closed: nothing is open
            riskmgr.rollback_reservation(bot.RISK_PATH, strategy=strategy, symbol=symbol); bot._stop_confirmed(state, symbol)
            now = datetime.now(timezone.utc); refused = state.setdefault("stop_refused", {}); refused[symbol] = now.isoformat()
            recent = [k for k, t in refused.items() if now - datetime.fromisoformat(t) < pd.Timedelta(days=1)]
            if len(recent) >= 3:   # not one coin's filter: the account or the order format — stop entering
                bot._ENTRY_BLOCK["reason"] = f"the exchange refused the stop on {len(recent)} coins today"
                state.setdefault("recovery_required", {})["stop_refused"] = {"reason": bot._ENTRY_BLOCK["reason"], "coins": recent, "at": now.isoformat()}
            bot.log(f"⛔ {symbol}: الوقف اترفض فاتقفلت الصفقة على طول"); bot.notify(f"⛔ {symbol}: المنصة رفضت أمر الوقف ({oco.get('sl_error')}) — الصفقة اتقفلت على طول، والعملة دي متوقفة يوم")
            bot.save_state(state); return None
        pos["unprotected"] = True
        state["positions"][symbol] = pos
        riskmgr.mark_reservation_recovery(bot.RISK_PATH, strategy=strategy, symbol=symbol, reason="protective stop missing, close failed")
        state.setdefault("recovery_required", {})[symbol] = {"cid": cid, "reason": f"protective stop missing and the close failed: {close_error}", "at": datetime.now(timezone.utc).isoformat()}
        bot._ENTRY_BLOCK["reason"] = "protective stop requires recovery"
        bot.save_state(state)
        bot.notify(f"🚨 {symbol}: المنصة رفضت أمر الوقف والقفل فشل — الصفقة مفتوحة من غير وقف، اقفلها يدوي")
        return None
    state["positions"][symbol] = pos
    if oco.get("verify_failed"):
        pos["sl_unverified"] = True
        state.setdefault("recovery_required", {})[symbol] = {"cid": cid, "reason": oco.get("verify_warn"), "at": datetime.now(timezone.utc).isoformat()}
        bot._ENTRY_BLOCK["reason"] = "protective order verification requires recovery"
    riskmgr.register_open_risk(bot.RISK_PATH, strategy=strategy, symbol=symbol, side=side,
        risk_usdt=risk_usdt or 0, notional_usdt=margin * leverage, correlation_group=bot._correlation_group(symbol))
    bot.save_state(state)
    return pos


def _closed_cleanly(state, symbol):
    """A verified close: nothing about this coin needs a person any more (its review mark, an expected stop, a due
    exit). Left behind, the mark blocked every new entry on every coin."""
    for book in ("recovery_required", "protect", "exit_due"):
        (state.get(book) or {}).pop(symbol, None)

def _retry_due_exits(ex, state, label):
    """Exits a strategy decided on but couldn't carry out (the exchange didn't answer, a close was refused): tried
    again every cycle until they go through, not only at the next daily signal."""
    for sym, reason in list((state.get("exit_due") or {}).items()):
        if sym not in state["positions"]:
            state["exit_due"].pop(sym, None); continue
        try: price = float(ex.fetch_ticker(sym)["last"])
        except Exception: continue
        if bot._single_leg_live_exit(ex, state, sym, price, reason):
            bot.log(f"✅ {label}: الخروج المتأجل من {sym} اتنفذ ({reason})")

def _single_leg_live_exit(ex, state, symbol, price, reason):
    pos = state["positions"].get(symbol)
    if not pos:
        return False
    if symbol in (state.get("recovery_required") or {}) and not (pos.get("unprotected") or pos.get("sl_unverified")):
        # its state is in doubt but its exchange stop is in place: a person decides. Without a stop it is closed.
        bot.log(f"⏸️ {symbol}: خروج ({reason}) متأجل — الصفقة محتاجة مراجعة"); return False
    try:
        result = bot.close_live_position(ex, symbol, pos, price)
        bot._require_verified_close(result)
        cs = bot._position_contract_size(pos)
        pnl = futures_net_pnl(pos["entry"], result["price"], result["qty"], cs, pos.get("side", "long"),
            fee_rate=bot._fee_rate(pos, required=True), funding_pnl=bot._funding_pnl(pos, required=True))
        state["history"].append({"symbol": symbol, "side": pos.get("side", "long"), "entry": pos["entry"],
            "exit": result["price"], "qty": result["qty"], "pnl": pnl, "reason": reason,
            "time": datetime.now(timezone.utc).isoformat(), "type": "live", "opened": pos.get("time")})
        state["stats"]["trades"] += 1; state["stats"]["pnl"] += float(pnl)
        state["stats"]["wins" if pnl > 0 else "losses"] += 1
        state["positions"].pop(symbol, None); state["last_trade"][symbol] = datetime.now(timezone.utc).isoformat()
        bot._closed_cleanly(state, symbol)
        bot.save_state(state)
        bot._release_position_risk(symbol, pos)
        return True
    except Exception as exc:
        first = symbol not in (state.get("exit_due") or {})
        state.setdefault("exit_due", {})[symbol] = reason
        if isinstance(locals().get("result"), dict) and result.get("unchanged"):
            # nothing happened on the exchange: try again next cycle, the coin is not locked
            bot.log(f"⚠️ {symbol}: الخروج ({reason}) ما اتنفذش — هيتعاد الدورة الجاية: {exc}")
            if first: bot.notify(f"⚠️ {symbol}: الخروج ({reason}) ما اتنفذش ({exc}) — البوت هيحاول تاني كل دورة")
            bot.save_state(state); return False
        state.setdefault("recovery_required", {})[symbol] = {"reason": f"live exit requires recovery: {exc}", "at": datetime.now(timezone.utc).isoformat()}
        bot._ENTRY_BLOCK["reason"] = "live exit requires recovery"
        bot.save_state(state)
        bot.notify(f"🚨 {symbol}: الخروج ({reason}) حالته مش واضحة ({exc}) — راجع المنصة. البوت وقف الدخول الجديد.")
        return False


def _guard_stops(ex, state, prices, label):
    """The 40% protective stop (before liquidation at x2) between the bot's own exits."""
    for sym, pos in list(state["positions"].items()):
        try:
            price = float(ex.fetch_ticker(sym)["last"]); prices[sym] = price
            if price <= pos["sl"]:
                reason = f"وقف {pos['sl']:.6g}"
                if bot.CONFIG.get("paper_trading"):
                    pnl = bot._paper_close(ex, state, sym, price, reason); bot.save_state(state)
                    bot.log(f"🔒 {label}: وقف {sym} @ {price:.6g} PnL {pnl:+.4f}")
                else:
                    bot._single_leg_live_exit(ex, state, sym, price, reason)
        except Exception as e: bot.log(f"{label} {sym}: {e}")

def write_simple_status(name, state, prices, rules, extra):
    """Public <name>.json for a long-only paper bot, in the shape the site reads for momentum.json. Live, it also writes
    the admin page's live status (RAQM_IPC_DIR), so the site's live close button reaches this bot."""
    if not bot.CONFIG["paper_trading"]:
        try: bot.write_live_status(state, prices)
        except Exception as e: bot.log(f"live status: {e}")
    out_dir = bot.CONFIG.get("public_dir")
    if not out_dir: return
    pos = []
    for sym, p in state["positions"].items():
        price = prices.get(sym, p["entry"]); pnl = (price - p["entry"]) * p["qty"]
        margin = p["entry"] * p["qty"] / max(1, int(p.get("leverage", 2)))
        pos.append({"symbol": sym.split(":")[0], "id": sym.split("/")[0] + "USDT", "side": "long", "entry": p["entry"], "price": price,
                    "qty": p["qty"], "margin": round(margin, 2), "sl": p["sl"], "pnl": round(pnl, 4),
                    "pnl_pct": round(pnl / margin * 100, 2) if margin else 0, "opened": p["time"], "exit_at": p.get("exit_at")})
    st = state.get("stats", {})
    data = {"updated": datetime.now(timezone.utc).isoformat(), "mode": "paper" if bot.CONFIG["paper_trading"] else "live", "rules": rules,
            "leverage": int(bot.CONFIG.get("leverage", 2)), "margin": bot.CONFIG.get("trade_amount_usdt"), "started": bot.CONFIG.get("started_at"),
            "stats": {"closed": st.get("trades", 0), "wins": st.get("wins", 0), "losses": st.get("losses", 0),
                      "realized": round(float(st.get("pnl", 0)), 4), "unrealized": round(sum(x["pnl"] for x in pos), 4), "open": len(pos)},
            "positions": pos, **extra,
            "history": [{"symbol": h["symbol"].split(":")[0], "side": h.get("side", "long"), "entry": h["entry"], "exit": h["exit"], "pnl": bot._r4(h.get("pnl")),
                         "reason": h.get("reason", ""), "time": h.get("time"), "opened": h.get("opened")}
                        for h in state.get("history", [])[-300:]][::-1]}
    try:
        d = Path(out_dir); tmp = d / f"{name}.json.tmp"
        tmp.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8"); tmp.replace(d / f"{name}.json")
    except Exception as e: bot.log(f"public {name} status: {e}")
