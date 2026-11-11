"""single-strategy entries (trend live entry, try_enter) and paper opens.
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


def _enter_trend_live(symbol, analysis, state, ex, margin, lev, price):
    import strategies_trend as stt
    from backend.app.oco import place_oco_orders
    activation_ok, activation_reason = bot._live_activation_gate("trend_daily")
    if not activation_ok:
        bot._ENTRY_BLOCK["reason"] = f"live activation blocked — {activation_reason}"
        bot.log(f"⛔ {symbol} {bot._ENTRY_BLOCK['reason']}"); return
    # the exchange's minimum order value (Binance: $5, ETH $20, BTC $50) — skip instead of having it rejected
    try: min_cost = float(((ex.market(symbol).get("limits") or {}).get("cost") or {}).get("min") or 5)
    except Exception: min_cost = 5.0
    if margin * lev < min_cost * 1.05:
        bot.log(f"⏸️ {symbol} حجم {margin*lev:.2f}$ أقل من أقل أمر على المنصة {min_cost}$ — مفيش دخول"); return
    try:
        bal = ex.fetch_balance()
        free = float((bal.get("USDT") or {}).get("free") or (bal.get("free") or {}).get("USDT") or 0)
    except Exception as e:
        bot.log(f"⏸️ {symbol} فحص الرصيد فشل — مفيش دخول: {e}"); return
    if free < margin * 1.02:
        bot.log(f"⏸️ {symbol} رصيد {free:.2f}$ مش كفاية لهامش {margin:.2f}$"); return
    equity, equity_at = bot._equity_now(ex)
    if equity is None:
        bot.log(f"⏸️ {symbol} equity unavailable — no entry"); return
    sl_estimate = price * (1 - stt.STOP_SHARE / lev)
    risk_usdt = bot._estimate_trade_risk_usdt(margin, lev, price, sl_estimate)
    allowed, reason = riskmgr.pre_trade_gate(
        bot.RISK_PATH, strategy="trend_daily", symbol=symbol, side="long",
        risk_usdt=risk_usdt, notional_usdt=margin * lev, equity_usdt=equity,
        equity_observed_at=equity_at, correlation_group=bot._correlation_group(symbol),
        strategy_risk_share=bot._live_risk_share("trend_daily"), strategies_sharing=bot._strategies_sharing())
    if not allowed:
        bot.log(f"⛔ {symbol} رفض بوابة المخاطر المركزية — {reason}"); return
    cid = "raqm-" + uuid.uuid4().hex[:27]   # per attempt — a fixed id per symbol matched trade #1's order on trade #2
    state.setdefault("pending_orders", {})[symbol] = cid; bot.save_state(state)   # survives a crash between order and record
    bot._expect_stop(state, symbol, "long", sl_estimate, cid)
    try:
        res = bot.place_order(ex, symbol, "long", margin, price, client_order_id=cid)
    except Exception as e:
        q = bot._exchange_position_qty(ex, symbol)
        if q is None:
            riskmgr.mark_reservation_recovery(bot.RISK_PATH, strategy="trend_daily", symbol=symbol, reason="entry outcome unknown")
            state.setdefault("recovery_required", {})[symbol] = {"cid": cid, "reason": f"entry error, position unknown: {e}", "at": datetime.now(timezone.utc).isoformat()}
            bot.save_state(state)
            bot.notify(f"🚨 {symbol}: أمر الدخول رجّع خطأ ومقدرناش نعرف اتنفذ ولا لأ — راجع المنصة. البوت وقف أي دخول جديد."); return
        flat_ok, why = bot._entry_failed_flat(ex, symbol, cid, side="long") if q == 0 else (False, "")
        if flat_ok:
            riskmgr.rollback_reservation(bot.RISK_PATH, strategy="trend_daily", symbol=symbol)
            state["pending_orders"].pop(symbol, None); bot.save_state(state)
            bot.log(f"فشل دخول {symbol}: {e}"); return
        if q == 0:   # one flat reading only — the order may have filled and the position not shown yet
            riskmgr.mark_reservation_recovery(bot.RISK_PATH, strategy="trend_daily", symbol=symbol, reason=f"entry error, not proven flat: {why}")
            state.setdefault("recovery_required", {})[symbol] = {"cid": cid, "reason": f"entry error, not proven flat ({why}): {e}", "at": datetime.now(timezone.utc).isoformat()}
            bot._ENTRY_BLOCK["reason"] = "live entry outcome requires recovery"
            bot.save_state(state)
            bot.notify(f"🚨 {symbol}: أمر الدخول رجّع خطأ ومش متأكدين إنه ما اتنفذش ({why}) — راجع المنصة. البوت وقف أي دخول جديد.")
            return
        q, protected = bot._protect_unrecorded_entry(ex, symbol, "long", sl_estimate, cid)
        state.setdefault("recovery_required", {})[symbol] = {"cid": cid, "reason": f"entry error with an open position but no authoritative entry fill: {e}", "qty": q,
                                                             "emergency_stop": protected, "at": datetime.now(timezone.utc).isoformat()}
        riskmgr.mark_reservation_recovery(bot.RISK_PATH, strategy="trend_daily", symbol=symbol, reason="open position without authoritative fill")
        bot._ENTRY_BLOCK["reason"] = "live entry fill evidence unavailable"
        bot.save_state(state)
        bot.notify(f"🚨 {symbol}: الصفقة ظهرت على المنصة لكن مفيش fill موثوق — دخلت recovery وممنوع تداول جديد. " +
               (f"اتحط وقف طوارئ عند {sl_estimate:.6g}" if protected else "ومن غير وقف — اقفلها يدوي"))
        return
    sl = res["price"] * (1 - stt.STOP_SHARE / lev)
    pos = {"side":"long","entry":res["price"],"qty":res["qty"],"cost":res["cost"],"notional":res.get("notional"),"contract_size":res.get("contract_size", 1.0),"contract_size_verified":res.get("contract_size_verified", False),"entry_fee_rate":res.get("entry_fee_rate"),"entry_fee_cost":res.get("entry_fee_cost"),"leverage":res.get("leverage",lev),
           "time":datetime.now(timezone.utc).isoformat(),"sl":sl,"tp":None,"breakeven":False,"trend":True,"rank":analysis.get("rank"),
           "clientOrderId": cid, "oco_ids": {"pos_id": cid}, "strategy": "trend_daily"}
    try:
        oco = place_oco_orders(ex, symbol, "long", res["qty"], sl, None, paper=False, pos_id=cid)
    except Exception as e:
        oco = {"sl_error": str(e), "protection_missing": True}
    pos["oco_ids"]["sl"] = oco.get("sl_id")
    state["pending_orders"].pop(symbol, None)
    if not oco.get("protection_missing") and not oco.get("verify_failed"): bot._stop_confirmed(state, symbol)
    else: state["protect"][symbol]["sl"] = float(sl)               # retried at the real stop level
    if oco.get("protection_missing"):
        bot.notify(f"🚨 {symbol}: أمر الوقف اترفض ({oco.get('sl_error')}) — بيقفل الصفقة فورا")
        try:
            r = bot.close_live_position(ex, symbol, pos, price)
            bot._require_verified_close(r)
            cs = bot._position_contract_size(pos)
            if cs is None:
                raise RuntimeError("missing contract_size for live PnL")
            pnl = futures_net_pnl(pos["entry"], r["price"], r["qty"], cs, pos.get("side", "long"), fee_rate=bot._fee_rate(pos, required=True), funding_pnl=bot._funding_pnl(pos, required=True))
            state["history"].append({"symbol":symbol,"side":"long","entry":pos["entry"],"exit":r["price"],"qty":r["qty"],"pnl":pnl,"pnl_pct":pnl/(pos["entry"]*r["qty"]*cs/max(1, int(pos.get("leverage", bot.CONFIG.get("leverage", 1)))))*100,
                "reason":"الوقف اترفض — قفل فوري","time":datetime.now(timezone.utc).isoformat(),"type":"live","opened":pos["time"],"rank":pos.get("rank")})
            state["stats"]["trades"]+=1; state["stats"]["pnl"]+=float(pnl); state["stats"]["wins" if pnl>0 else "losses"]+=1
            state["last_trade"][symbol]=datetime.now(timezone.utc).isoformat(); bot.save_state(state)
            riskmgr.release_open_risk(bot.RISK_PATH, strategy="trend_daily", symbol=symbol)
            bot.log(f"🔒 {symbol}: اتقفلت فورا لأن الوقف اترفض"); return
        except Exception as e:
            pos["unprotected"] = True
            state.setdefault("recovery_required", {})[symbol] = {"reason": f"no stop and close failed: {e}", "at": datetime.now(timezone.utc).isoformat()}
            bot.notify(f"🚨🚨 {symbol}: الصفقة مفتوحة من غير وقف والقفل فشل — اقفلها يدويا من Binance دلوقتي. البوت وقف أي دخول جديد.")
    elif oco.get("verify_failed"):
        pos["sl_unverified"] = True
        state.setdefault("recovery_required", {})[symbol] = {"reason": oco.get("verify_warn"), "at": datetime.now(timezone.utc).isoformat()}
        bot.notify(f"🚨 {symbol}: الوقف اتقبل بس مش لاقيه على المنصة — راجعه. البوت وقف أي دخول جديد.")
    state["positions"][symbol] = pos
    try:
        riskmgr.register_open_risk(bot.RISK_PATH, strategy="trend_daily", symbol=symbol, side="long",
            risk_usdt=bot._estimate_trade_risk_usdt(margin, lev, res["price"], sl) or 0,
            notional_usdt=margin * lev, correlation_group=bot._correlation_group(symbol))
    except Exception as e:
        bot.log(f"risk ledger register failed {symbol}: {e}")
    state["last_trade"][symbol]=datetime.now(timezone.utc).isoformat(); bot.save_state(state)
    bot.log(f"✅ 🟢 لونج {bot._live_label()} {symbol} ترند يومي x{lev} @ {res['price']:.6g} qty {res['qty']} وقف على المنصة {sl:.6g}")
    bot.notify(f"🟢 لونج {symbol} — ترند يومي x{lev} ({bot._live_label()})\nدخول {res['price']:.6g} · هامش {margin:.2f}$\nوقف على المنصة {sl:.6g} · الخروج لما الترند يقف")

def try_enter(symbol, analysis, state, ex):
    """فيوتشر: لونج لو سكور > buy_threshold، شورت لو سكور < sell_threshold"""
    if not bot.CONFIG.get("paper_trading") and not bot.in_position(state, symbol):
        # Entries only: an open position still has to be able to exit on its signal.
        activation_ok, activation_reason = bot._live_activation_gate(bot._current_strategy_name())
        if not activation_ok:
            bot._ENTRY_BLOCK["reason"] = f"live activation blocked — {activation_reason}"
            bot.log(f"⛔ {symbol} {bot._ENTRY_BLOCK['reason']}")
            return
    if not bot.CONFIG.get("paper_trading") and bot._ENTRY_BLOCK["reason"] and not bot.in_position(state, symbol):
        bot.log(f"⛔ {symbol} دخول متوقف — {bot._ENTRY_BLOCK['reason']}")
        return
    # Block every new entry while any position needs a human (unprotected / unverified / ambiguous order)
    if state.get("recovery_required"):
        if bot.trend_mode() and bot.in_position(state, symbol):
            return bot.try_enter_trend(symbol, analysis, state, ex)   # an open position still exits on its signal
        bot.log(f"⛔ {symbol} دخول متوقف — فيه صفقة محتاجة مراجعة: {', '.join(state['recovery_required'])}")
        return
    if state.get("pending_orders", {}).get(symbol):
        # try to reconcile ambiguous timeout before blocking
        cid_pending = state["pending_orders"][symbol]
        try:
            if not bot.CONFIG.get("paper_trading"):
                found = bot._reconcile_fills_by_client_id(ex, symbol, cid_pending)
                if found:
                    fq = normalize_filled_contracts(found)
                    if fq and fq>0:
                        bot.log(f"♻️ {symbol} reconcile: pending {cid_pending} found fill {fq} — completing")
                        # complete as if order succeeded: create pos if needed (caller handles); just clear pending
                        # we cannot infer sl/tp here; mark recovery to re-verify
                        state.setdefault("recovery_required", {})[symbol] = {"cid": cid_pending, "found": found, "reason": "entry filled after a timeout — no stop placed"}
                        bot.notify(f"🚨 {symbol}: أمر دخول اتنفذ بعد timeout ومن غير وقف على المنصة. راجعه يدويا — البوت وقف أي دخول جديد.")
                        state["pending_orders"].pop(symbol, None)
                        bot.save_state(state)
                        return
        except Exception:
            pass
        bot.log(f"⏸️ {symbol} طلب معلق — تخطي الدخول حتى التأكد")
        return
    if bot.trend_mode(): return bot.try_enter_trend(symbol, analysis, state, ex)
    if bot.wave_mode(): return bot.try_enter_wave(symbol, analysis, state, ex)
    total=analysis["total"]; price=analysis["price"]
    is_long = total > bot.CONFIG["buy_threshold"]
    is_short = total < bot.CONFIG["sell_threshold"]
    has_pos = bot.in_position(state, symbol)

    # لو عنده صفقة وجاءت إشارة عكسية قوية — اقفلها
    if has_pos:
        pos = state["positions"][symbol]; side = pos.get("side","long")
        # لونج + بيع قوي => اقفل، شورت + شراء قوي => اقفل
        should_close = (side=="long" and total < bot.CONFIG["strong_sell"]) or (side=="short" and total > bot.CONFIG["strong_buy"])
        if should_close:
            qty=pos["qty"]; entry=pos["entry"]
            try:
                pnl=(price-entry)*qty if side=="long" else (entry-price)*qty
                pct=(pnl/(entry*qty)*100) if entry*qty else 0
                if bot.CONFIG["paper_trading"]:
                    bot.log(f"📉 اغلاق عكسي {side} {symbol} سكور {total:+.3f} @ {price:.4f} PnL {pnl:+.4f} ({pct:+.2f}%)")
                    state["history"].append({"symbol":symbol,"side":side,"entry":entry,"exit":price,"qty":qty,"pnl":pnl,"pnl_pct":pct,"reason":"اشارة عكسية قوية","time":datetime.now(timezone.utc).isoformat(),"type":"paper"})
                else:
                    res=bot.close_live_position(ex, symbol, pos, price)
                    bot._require_verified_close(res)
                    cs = bot._position_contract_size(pos)
                    if cs is None:
                        raise RuntimeError("missing contract_size for live PnL")
                    pnl = futures_net_pnl(entry, res["price"], res["qty"], cs, side, fee_rate=bot._fee_rate(pos, required=True), funding_pnl=bot._funding_pnl(pos, required=True))
                    pct=(pnl/(entry*res["qty"]*cs/max(1, int(pos.get("leverage", bot.CONFIG.get("leverage", 1)))))*100) if entry*res["qty"] else 0
                    bot.log(f"📉 اغلاق حقيقي {side} {symbol} @ {res['price']:.4f} PnL {pnl:+.4f}")
                    state["history"].append({"symbol":symbol,"side":side,"entry":entry,"exit":res["price"],"qty":res["qty"],"pnl":pnl,"pnl_pct":pct,"reason":"اشارة عكسية","time":datetime.now(timezone.utc).isoformat(),"type":"live"})
                state["stats"]["trades"]+=1; state["stats"]["pnl"]+=float(pnl)
                if pnl>0: state["stats"]["wins"]+=1
                else: state["stats"]["losses"]+=1
                state["positions"].pop(symbol,None); state["last_trade"][symbol]=datetime.now(timezone.utc).isoformat()
                if not bot.CONFIG["paper_trading"]: bot._closed_cleanly(state, symbol)
                bot.save_state(state)
                if not bot.CONFIG["paper_trading"]: bot._release_position_risk(symbol, pos)
            except Exception as e:
                if not bot.CONFIG["paper_trading"]:
                    state.setdefault("recovery_required", {})[symbol] = {"reason": f"reversal close accounting or protective cleanup unconfirmed: {e}", "at": datetime.now(timezone.utc).isoformat()}
                    bot._ENTRY_BLOCK["reason"] = "reversal close requires recovery"
                    bot.save_state(state)
                bot.log(f"فشل اغلاق {symbol} {side}: {e}")
            return

    if not has_pos:
        side=None
        if is_long: side="long"
        elif is_short: side="short"
        else: return
        if bot._strategy_full(state, bot.CONFIG["max_open_positions"]): return
        if not bot.cooldown_ok(state,symbol): return
        # === Week 1 filters ===
        # Daily loss guard
        if not bot.daily_pnl_ok(state):
            bot.log(f"⏸️ {symbol} إيقاف يومي — خسارة اليوم تجاوزت {bot.CONFIG.get('max_daily_loss_pct')}%")
            return
        # ADX filter — نحتاج df للـ ADX، نجيبه
        _f_df = None
        try:
            _f_df=bot.fetch_ohlcv(symbol, bot.CONFIG["timeframe"], limit=60, ex=ex)
            adx_v=bot.adx_value(_f_df)
            if adx_v < float(bot.CONFIG.get("adx_threshold", 18)):
                bot.log(f"⏸️ {symbol} فلتر ADX {adx_v:.1f} < {bot.CONFIG.get('adx_threshold')} — سوق عرضي")
                return
            if not bot.volume_ok(_f_df):
                bot.log(f"⏸️ {symbol} فلتر حجم — حجم ضعيف")
                return
        except Exception as e:
            bot.log(f"فلتر ADX/Vol {symbol}: {e}")
        # HTF filter
        # Regime filter: عرضي = يحتاج سكور أقوى
        try:
            _reg = bot.regime_detect(_f_df)
            if bot.CONFIG.get("regime_filter") and _reg=="range" and abs(total) < 0.30:
                bot.log(f"⏸️ {symbol} سوق عرضي ({_reg}) — يحتاج سكور ±0.30، الحالي {total:+.2f}")
                return
        except: pass
        if not bot.htf_trend_ok(symbol, side, ex):
            bot.log(f"⏸️ {symbol} فلتر ترند 4h — لا تدخل {side} عكس الترند الأكبر")
            return
        try:
            risk_sl, _risk_tp = bot.dynamic_sl_tp(analysis["price"], side, _f_df)
        except Exception:
            risk_sl = None
        amount=bot.position_size(analysis["price"], ex, stop_price=risk_sl)*analysis["amount_mult"]
        if not bot.CONFIG["paper_trading"]:
            try:
                bal=ex.fetch_balance()
                # فيوتشر: الرصيد في USDT
                usdt=0
                try: usdt=float(bal.get("USDT",{}).get("free",0) or 0)
                except: usdt=0
                if usdt==0:
                    try: usdt=float(bal["free"].get("USDT",0))
                    except: pass
                if usdt < amount: bot.log(f"رصيد غير كافي {usdt:.2f} < {amount:.2f}"); return
            except Exception as e:
                bot.log(f"فحص الرصيد فشل — مفيش دخول: {e}"); return
            equity, equity_at = bot._equity_now(ex)
            if equity is None:
                bot.log(f"⏸️ {symbol} equity unavailable — no entry"); return
            risk_usdt = bot._estimate_trade_risk_usdt(amount, bot.CONFIG.get("leverage", 5), price, risk_sl)
            allowed, reason = riskmgr.pre_trade_gate(
                bot.RISK_PATH, strategy=bot._current_strategy_name(), symbol=symbol, side=side,
                risk_usdt=risk_usdt, notional_usdt=amount * bot.CONFIG.get("leverage", 5), equity_usdt=equity,
                equity_observed_at=equity_at, correlation_group=bot._correlation_group(symbol),
                strategy_risk_share=bot._live_risk_share(bot._current_strategy_name()), strategies_sharing=bot._strategies_sharing())
            if not allowed:
                bot.log(f"⛔ {symbol} رفض بوابة المخاطر المركزية — {reason}"); return
        try:
            order_side="long" if side=="long" else "short"
            _f_df2 = _f_df if '_f_df' in locals() else bot.fetch_ohlcv(symbol, bot.CONFIG["timeframe"], limit=60, ex=ex)
            cid = "raqm-" + uuid.uuid5(uuid.NAMESPACE_URL, f"{bot._current_strategy_name()}|{symbol}|{side}").hex[:27]
            # pending flag for idempotent recovery (P0-05)
            state.setdefault("pending_orders", {})[symbol] = cid
            try: bot.save_state(state)
            except: pass
            res=bot.place_order(ex,symbol,order_side,amount,price, client_order_id=cid)
            sl, tp = bot.dynamic_sl_tp(price, side, _f_df2)
            pos = {"side":side,"entry":res["price"],"qty":res["qty"],"cost":res["cost"],"notional":res.get("notional",amount*bot.CONFIG.get("leverage",5)),"contract_size":res.get("contract_size", 1.0),"contract_size_verified":res.get("contract_size_verified", False),"entry_fee_rate":res.get("entry_fee_rate"),"entry_fee_cost":res.get("entry_fee_cost"),"leverage":res.get("leverage",bot.CONFIG.get("leverage",5)),"time":datetime.now(timezone.utc).isoformat(),"sl":sl,"tp":tp,"breakeven":False, "clientOrderId": cid}
            if not bot.CONFIG["paper_trading"]:
                from backend.app.oco import place_oco_orders
                pos_id = cid
                oco = None
                try:
                    oco = place_oco_orders(ex, symbol, side, res["qty"], sl, tp, paper=False, pos_id=pos_id)
                except Exception as e:
                    oco = {"sl_error": str(e), "tp_error": str(e), "both_failed": True, "protection_missing": True}
                pos["oco_ids"] = {"sl": (oco or {}).get("sl_id"), "tp": (oco or {}).get("tp_id"), "pos_id": pos_id}
                if oco is None or oco.get("protection_missing"):
                    # the exchange refused the stop: close at once; if that fails too, keep tracking the position
                    reason = f"SL err={(oco or {}).get('sl_error')}"
                    bot.log(f"⚠️ OCO فشل {symbol} {side} — {reason} — إغلاق طارئ")
                    bot.notify(f"🚨 {symbol}: أمر الوقف اترفض على المنصة — بيقفل الصفقة فورا")
                    flatten_qty, flatten_price = res["qty"], res["price"]
                    try:
                        for p in ex.fetch_positions([symbol]) or []:
                            s = p.get("symbol") or (p.get("info") or {}).get("symbol", "")
                            if s == symbol or s.split(":")[0] == symbol:
                                raw = p.get("contracts") if p.get("contracts") is not None else (p.get("info") or {}).get("size")
                                if raw is not None and float(raw) > 0: flatten_qty = float(raw)
                                break
                    except Exception:
                        pass
                    flatten_ok = False
                    fr = {}
                    try:
                        close_side = "close_long" if side == "long" else "close_short"
                        fr = bot.place_order(ex, symbol, close_side, 0, flatten_price, close_qty=flatten_qty)
                        try:
                            still_open = False
                            for p in ex.fetch_positions([symbol]) or []:
                                s = p.get("symbol") or (p.get("info") or {}).get("symbol", "")
                                if s == symbol or s.split(":")[0] == symbol:
                                    c = p.get("contracts") if p.get("contracts") is not None else (p.get("info") or {}).get("size")
                                    if float(c or 0) != 0: still_open = True
                            flatten_ok = not still_open
                        except Exception:
                            flatten_ok = float(fr.get("qty", 0) or 0) > 0
                    except Exception as ee:
                        bot.log(f"فشل إغلاق طارئ {symbol}: {ee}")
                    if flatten_ok:
                        cleanup_ok = True
                        if oco:
                            try:
                                from backend.app.oco import cancel_oco_orders
                                cleanup_ok = bool(cancel_oco_orders(ex, symbol, pos_id=pos_id))
                            except Exception:
                                cleanup_ok = False
                        if not cleanup_ok:
                            pos["unprotected"] = True
                            pos["strategy"] = bot._current_strategy_name()
                            state["positions"][symbol] = pos
                            state.setdefault("recovery_required", {})[symbol] = {"cid": cid, "reason": "emergency flatten succeeded but protective cancellation is unconfirmed", "at": datetime.now(timezone.utc).isoformat()}
                            bot._ENTRY_BLOCK["reason"] = "protective cancellation requires recovery"
                            state.get("pending_orders", {}).pop(symbol, None)
                            bot.save_state(state)
                            return
                        cs = bot._position_contract_size(pos)
                        try:
                            bot._refresh_fee_evidence(ex, symbol, pos, fr.get("raw"))
                            bot._refresh_funding_evidence(ex, symbol, pos)
                            if cs is None or not fr.get("price") or not fr.get("qty"):
                                raise RuntimeError("emergency close fill evidence incomplete")
                            pnl = futures_net_pnl(pos["entry"], fr["price"], fr["qty"], cs, side, fee_rate=bot._fee_rate(pos, required=True), funding_pnl=bot._funding_pnl(pos, required=True))
                        except Exception as e:
                            state["positions"][symbol] = pos
                            state.setdefault("recovery_required", {})[symbol] = {"cid": cid, "reason": f"emergency close accounting unavailable: {e}", "at": datetime.now(timezone.utc).isoformat()}
                            bot._ENTRY_BLOCK["reason"] = "emergency close accounting requires recovery"
                            bot.save_state(state)
                            return
                        state["history"].append({"symbol": symbol, "side": side, "entry": pos["entry"], "exit": fr["price"], "qty": fr["qty"], "pnl": pnl, "funding_pnl": pos.get("funding_pnl"), "reason": "emergency flatten", "time": datetime.now(timezone.utc).isoformat(), "type": "live"})
                        state["stats"]["trades"] += 1
                        state["stats"]["pnl"] += float(pnl)
                        state["stats"]["wins" if pnl > 0 else "losses"] += 1
                        bot.log(f"🔒 إغلاق طارئ {symbol} نجح — qty {flatten_qty} — PnL {pnl:+.4f}")
                        state.get("pending_orders", {}).pop(symbol, None)
                        state.get("recovery_required", {}).pop(symbol, None)
                        state["last_trade"][symbol] = datetime.now(timezone.utc).isoformat()
                        try: bot.save_state(state)
                        except: pass
                        return
                    # still open on the exchange without a stop: the bot keeps managing it (its own SL/TP check)
                    # and no new entry anywhere until someone resolves it
                    pos["unprotected"] = True
                    pos["strategy"] = bot._current_strategy_name()
                    state["positions"][symbol] = pos
                    state.setdefault("recovery_required", {})[symbol] = {"cid": cid, "reason": "unprotected: " + reason, "qty": flatten_qty, "price": flatten_price, "at": datetime.now(timezone.utc).isoformat()}
                    state.get("pending_orders", {}).pop(symbol, None)
                    try:
                        riskmgr.register_open_risk(bot.RISK_PATH, strategy=pos["strategy"], symbol=symbol, side=side,
                            risk_usdt=bot._estimate_trade_risk_usdt(amount, pos.get("leverage", bot.CONFIG.get("leverage", 5)), flatten_price, None) or 0,
                            notional_usdt=amount * pos.get("leverage", bot.CONFIG.get("leverage", 5)),
                            correlation_group=bot._correlation_group(symbol))
                    except Exception as e:
                        bot.log(f"risk ledger register failed {symbol}: {e}")
                    try: bot.save_state(state)
                    except: pass
                    bot.log(f"🚨 {symbol} RECOVERY_REQUIRED — صفقة مفتوحة من غير وقف، الدخول متوقف لحد ما تتراجع")
                    bot.notify(f"🚨 {symbol}: الإغلاق الطارئ فشل — الصفقة مفتوحة من غير وقف على المنصة. راجعها يدويا. البوت وقف أي دخول جديد.")
                    return
                if oco.get("tp_missing"):
                    bot.log(f"⚠️ {symbol}: الهدف اترفض ({oco.get('tp_error')}) — الوقف شغال، والبوت هيقفل عند الهدف بنفسه")
                    bot.notify(f"⚠️ {symbol}: أمر الهدف اترفض على المنصة — الوقف موجود، والبوت هيقفل عند الهدف بنفسه")
                if oco.get("verify_failed"):
                    # accepted by the exchange but not found afterwards: keep the position, stop new entries, alert
                    pos["sl_unverified"] = bool(oco.get("sl_unverified"))
                    state.setdefault("recovery_required", {})[symbol] = {"cid": cid, "reason": oco.get("verify_warn"), "at": datetime.now(timezone.utc).isoformat()}
                    bot.log(f"🚨 {symbol}: {oco.get('verify_warn')} — الدخول متوقف لحد ما تتراجع")
                    bot.notify(f"🚨 {symbol}: أوامر الحماية اتقبلت بس مش لاقيها على المنصة ({oco.get('verify_warn')}). راجعها يدويا — البوت وقف أي دخول جديد.")
            state["positions"][symbol]=pos
            if not bot.CONFIG["paper_trading"]:
                pos["strategy"] = bot._current_strategy_name()
                try:
                    riskmgr.register_open_risk(bot.RISK_PATH, strategy=pos["strategy"], symbol=symbol, side=side,
                        risk_usdt=bot._estimate_trade_risk_usdt(amount, pos.get("leverage", bot.CONFIG.get("leverage", 5)), res["price"], sl) or 0,
                        notional_usdt=amount * pos.get("leverage", bot.CONFIG.get("leverage", 5)),
                        correlation_group=bot._correlation_group(symbol))
                except Exception as e:
                    bot.log(f"risk ledger register failed {symbol}: {e}")
            try:
                if pos.get("oco_ids"):
                    state.setdefault("_last_oco", {})[symbol] = dict(pos["oco_ids"])
            except:
                pass
            state.get("pending_orders", {}).pop(symbol, None)
            state["last_trade"][symbol]=datetime.now(timezone.utc).isoformat(); bot.save_state(state)
            mode="وهمي" if bot.CONFIG["paper_trading"] else "حقيقي"
            lev_txt=f" x{res.get('leverage',bot.CONFIG.get('leverage',5))}" if bot.CONFIG.get("market")=="future" else ""
            emoji="🟢 لونج" if side=="long" else "🔴 شورت"
            bot.log(f"✅ {emoji} {mode} {symbol}{lev_txt} @ {res['price']:.6f} qty {res['qty']} SL {sl:.4f} TP {tp:.4f} سكور {total:+.3f} {analysis['decision']}")
        except Exception as e:
            if not bot.CONFIG.get("paper_trading"):
                try:
                    if "pos" in locals() and pos.get("qty"):
                        riskmgr.mark_reservation_recovery(bot.RISK_PATH, strategy=pos.get("strategy") or bot._current_strategy_name(), symbol=symbol, reason=f"entry workflow ambiguous: {e}")
                    else:
                        riskmgr.rollback_reservation(bot.RISK_PATH, strategy=bot._current_strategy_name(), symbol=symbol)
                except Exception as risk_exc:
                    bot.log(f"risk reservation recovery failed {symbol}: {risk_exc}")
            bot.log(f"فشل {side} {symbol}: {e}")


def _utc_day(now):
    return now.replace(hour=0, minute=0, second=0, microsecond=0)

def _paper_open(state, sym, price, now, extra):
    lev = int(bot.CONFIG.get("leverage", 2)); q = bot.position_size(price) * lev / price
    state["positions"][sym] = {"side": "long", "entry": price, "qty": q, "leverage": lev, "time": now.isoformat(), "tp": None, **extra}
    return q
