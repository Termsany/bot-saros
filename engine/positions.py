"""stop/target checks of open positions and the wave entries.
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


def check_sl_tp(state, prices, ex=None):
    closed=[]; closed_positions={}
    for symbol,pos in list(state["positions"].items()):
        price=prices.get(symbol)
        if price is None: continue
        entry=pos["entry"]; side=pos.get("side","long"); sl=pos.get("sl"); tp=pos.get("tp")
        if pos.get("trend"): tp=float("inf") if side=="long" else 0.0   # no target: exits on the trend signal (try_enter_trend)
        if sl is None or tp is None:
            if side=="long": sl=entry*(1-bot.CONFIG["stop_loss_pct"]); tp=entry*(1+bot.CONFIG["take_profit_pct"])
            else: sl=entry*(1+bot.CONFIG["stop_loss_pct"]); tp=entry*(1-bot.CONFIG["take_profit_pct"])
        wave=pos.get("wave")
        if wave:
            sign=1 if side=="long" else -1
            # Wave Flats: stop to entry once price breaks the correction extreme (the backtest checks at the candle close)
            # Stage C (d): LIVE must amend exchange SL; otherwise flag unverified
            if not pos.get("breakeven") and sign*(price-wave["be"])>0:
                old_sl_w = sl
                new_sl_w = entry
                if not bot.CONFIG.get("paper_trading"):
                    if not bot._amend_exchange_sl(symbol, pos, new_sl_w, old_sl_w, ex, state):
                        pos["sl_unverified"] = True
                        pos["sl_sync"] = pos.get("sl_sync", "recovery")
                        continue
                pos["sl"]=sl=new_sl_w; pos["breakeven"]=True; bot.save_state(state)
                tag_w = " (UNVERIFIED - exchange SL not moved)" if pos.get("sl_unverified") else " (exchange verified)" if not bot.CONFIG.get("paper_trading") else ""
                bot.log(f"♻️ {symbol} {side} كسر قمة التصحيح {wave['be']:.6g} — الوقف لنقطة الدخول {entry:.6g}")
            # TP1: close half (Running/Expanded Flat only); paper only — LIVE is refused for Wave Flats
            if wave.get("tp1") and not wave.get("tp1_done") and sign*(price-wave["tp1"])>=0 and bot.CONFIG["paper_trading"]:
                half=pos["qty"]/2; pnl=(price-entry)*half*sign
                state["history"].append({"symbol":symbol,"side":side,"entry":entry,"exit":price,"qty":half,"pnl":pnl,"pnl_pct":pnl/(entry*half)*100,"reason":f"TP1 نص الكمية {wave['tp1']:.6g}","time":datetime.now(timezone.utc).isoformat(),"type":"paper"})
                state["stats"]["pnl"]+=float(pnl); pos["qty"]-=half; wave["tp1_done"]=True; bot.save_state(state)
                bot.log(f"🎯 {symbol} {side} TP1 @ {price:.6g} — قفل نص الكمية PnL {pnl:+.4f}")
        # ♻️ Breakeven — بعد 50% للهدف ينقل الوقف لنقطة الدخول
        # Breakeven - after 50% to target move SL to entry (Stage C (d): LIVE must amend exchange)
        if bot.CONFIG.get("breakeven_enabled") and not pos.get("breakeven") and not wave and not pos.get("trend"):
            trig_pct = float(bot.CONFIG.get("breakeven_trigger_pct", 0.5))
            off = float(bot.CONFIG.get("breakeven_offset_pct", 0.001))
            trig_price = entry + (tp - entry) * trig_pct if side=="long" else entry - (entry - tp) * trig_pct
            hit_be = (price >= trig_price) if side=="long" else (price <= trig_price)
            if hit_be:
                be_sl = entry * (1 + off) if side=="long" else entry * (1 - off)
                do_be = (side=="long" and be_sl > sl) or (side=="short" and be_sl < sl)
                if do_be:
                    old_sl = sl
                    if not bot.CONFIG.get("paper_trading"):
                        if not bot._amend_exchange_sl(symbol, pos, be_sl, old_sl, ex, state):
                            pos["sl_unverified"] = True
                            pos["sl_sync"] = pos.get("sl_sync", "recovery")
                            continue
                    pos["sl"] = be_sl
                    sl = pos["sl"]
                    pos["breakeven"] = True
                    try: bot.save_state(state)
                    except: pass
                    tag = " (UNVERIFIED - exchange SL not moved)" if pos.get("sl_unverified") else " (exchange verified)" if not bot.CONFIG.get("paper_trading") else ""
                    bot.log(f"Breakeven {symbol} {side} @ {price:.4f} SL {be_sl:.4f}{tag}")
                    bot.notify(f"Breakeven {symbol} {side} - SL {be_sl:.4f}{tag}")
                else:
                    pos["breakeven"] = True
                    try: bot.save_state(state)
                    except: pass
        reason=""; hit=False
        if side=="long":
            if price<=sl: hit=True; reason=f"وقف لونج SL {sl:.4f}" + (" (breakeven)" if pos.get("breakeven") else "")
            elif price>=tp: hit=True; reason=f"هدف لونج TP {tp:.4f}"
        else:
            if price>=sl: hit=True; reason=f"وقف شورت SL {sl:.4f}" + (" (breakeven)" if pos.get("breakeven") else "")
            elif price<=tp: hit=True; reason=f"هدف شورت TP {tp:.4f}"
        if not hit: continue
        qty=pos["qty"]
        try:
            if bot.CONFIG["paper_trading"]:
                pnl=(price-entry)*qty if pos.get("side","long")=="long" else (entry-price)*qty; pnl_pct=(pnl/(entry*qty)*100) if entry*qty else 0
                bot.log(f"🔒 اغلاق {symbol} {reason} @ {price:.4f} PnL {pnl:+.4f} ({pnl_pct:+.2f}%)")
                state["history"].append({"symbol":symbol,"side":pos.get("side","long"),"entry":entry,"exit":price,"qty":qty,"pnl":pnl,"pnl_pct":pnl_pct,"reason":reason,"time":datetime.now(timezone.utc).isoformat(),"type":"paper","opened":pos.get("time"),"rank":pos.get("rank")})
            else:
                res=bot.close_live_position(ex or bot.get_exchange(auth=True)[0], symbol, pos, price)
                bot._require_verified_close(res)
                cs = bot._position_contract_size(pos)
                if cs is None:
                    raise RuntimeError("missing contract_size for live PnL")
                pnl = futures_net_pnl(entry, res["price"], res["qty"], cs, pos.get("side", "long"), fee_rate=bot._fee_rate(pos, required=True), funding_pnl=bot._funding_pnl(pos, required=True))
                bot.log(f"🔒 اغلاق حقيقي {symbol} @ {res['price']:.4f} PnL {pnl:+.4f}")
                state["history"].append({"symbol":symbol,"side":pos.get("side","long"),"entry":entry,"exit":res["price"],"qty":res["qty"],"pnl":pnl,"pnl_pct":(res["price"]/entry-1)*100,"reason":reason,"time":datetime.now(timezone.utc).isoformat(),"type":"live"})
            state["stats"]["trades"]+=1; state["stats"]["pnl"]+=float(pnl)
            if pnl>0: state["stats"]["wins"]+=1
            else: state["stats"]["losses"]+=1
            closed.append(symbol); closed_positions[symbol] = pos
        except Exception as e:
            if not bot.CONFIG["paper_trading"]:
                state.setdefault("recovery_required", {})[symbol] = {"reason": f"live close accounting or protective cleanup unconfirmed: {e}", "at": datetime.now(timezone.utc).isoformat()}
                bot._ENTRY_BLOCK["reason"] = "live close requires recovery"
                bot.save_state(state)
            bot.log(f"فشل اغلاق {symbol}: {e}")
    for s in closed:
        state["positions"].pop(s,None); state["last_trade"][s]=datetime.now(timezone.utc).isoformat()
    flagged = False
    for s in list(bot._SL_AMEND_FAILED):
        bot._SL_AMEND_FAILED.discard(s)
        if s in state["positions"]:
            flagged = True
            # the fallback cancels the old stop before placing the new one: if that failed there may be no stop at all
            state.setdefault("recovery_required", {})[s] = {"reason": "exchange stop not moved / maybe missing", "at": datetime.now(timezone.utc).isoformat()}
            bot.log(f"🚨 {s}: تحريك الوقف على المنصة فشل — ممكن الصفقة تكون من غير وقف. الدخول متوقف لحد ما تتراجع")
            bot.notify(f"🚨 {s}: تحريك الوقف على المنصة فشل — ممكن الصفقة تكون من غير وقف. راجعها يدويا، البوت وقف أي دخول جديد.")
    if closed or flagged:
        bot.save_state(state)
        if not bot.CONFIG["paper_trading"]:
            for s, pos in closed_positions.items(): bot._release_position_risk(s, pos)

    return closed

def try_enter_wave(symbol, analysis, state, ex):
    """Wave Flats: enter at market on a new setup from the last closed candle, with the setup's own stop/targets."""
    sig=analysis.get("wave")
    if not sig or bot.in_position(state, symbol): return
    seen=state.setdefault("wave_seen",{})
    if seen.get(symbol)==sig["ts"]: return   # one entry per signal candle (the loop polls every minute)
    seen[symbol]=sig["ts"]; bot.save_state(state)
    side="long" if sig["dir"]==1 else "short"; price=analysis["price"]
    tp=sig["tgt2"] if sig["two"] else sig["tgt1"]
    if bot._strategy_full(state, bot.CONFIG["max_open_positions"]) or not bot.daily_pnl_ok(state): return
    if (side=="long" and price<=sig["stop"]) or (side=="short" and price>=sig["stop"]):
        bot.log(f"⏸️ {symbol} {sig['kind']} — السعر عدّى الوقف قبل الدخول"); return
    if not bot.CONFIG["paper_trading"]:
        pos = bot._single_leg_live_entry(ex, state, symbol, side, bot.position_size(price, ex, stop_price=sig["stop"]),
            price, sig["stop"], tp, "wave_flats", {"wave": {"kind": sig["kind"], "tp1": sig["tgt1"] if sig["two"] else None,
            "tp1_done": False, "be": sig["be"]}})
        if pos:
            state["last_trade"][symbol]=datetime.now(timezone.utc).isoformat(); bot.save_state(state)
        return
    if bot._strategy_full(state, bot.CONFIG["max_open_positions"]) or not bot.daily_pnl_ok(state): return
    side="long" if sig["dir"]==1 else "short"; price=analysis["price"]
    if (side=="long" and price<=sig["stop"]) or (side=="short" and price>=sig["stop"]):
        bot.log(f"⏸️ {symbol} {sig['kind']} — السعر عدّى الوقف قبل الدخول"); return
    try:
        res=bot.place_order(ex,symbol,side,bot.position_size(price, ex, stop_price=sig["stop"]),price)
        tp=sig["tgt2"] if sig["two"] else sig["tgt1"]
        state["positions"][symbol]={"side":side,"entry":res["price"],"qty":res["qty"],"cost":res["cost"],"notional":res.get("notional"),"contract_size":res.get("contract_size", 1.0),"contract_size_verified":res.get("contract_size_verified", False),"entry_fee_rate":res.get("entry_fee_rate"),"entry_fee_cost":res.get("entry_fee_cost"),"leverage":res.get("leverage",bot.CONFIG.get("leverage",5)),
            "time":datetime.now(timezone.utc).isoformat(),"sl":sig["stop"],"tp":tp,"breakeven":False,
            "wave":{"kind":sig["kind"],"tp1":sig["tgt1"] if sig["two"] else None,"tp1_done":False,"be":sig["be"]}}
        state["last_trade"][symbol]=datetime.now(timezone.utc).isoformat(); bot.save_state(state)
        emoji="🟢 لونج" if side=="long" else "🔴 شورت"
        tp1_txt=f" TP1 {sig['tgt1']:.6g}" if sig["two"] else ""
        bot.log(f"✅ {emoji} وهمي {symbol} {sig['kind']} @ {res['price']:.6g} SL {sig['stop']:.6g} TP {tp:.6g}{tp1_txt}")
    except Exception as e: bot.log(f"فشل {side} {symbol}: {e}")
