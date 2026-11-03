"""trend_daily — the daily trend (signal in strategies_trend.py): long when the last closed daily candle turns the
trend on, out when it turns off. analyze() and try_enter() in bot.py hand it the cycle; its live entry is
bot._enter_trend_live and its exit bot.close_live_position, both shared. Moved from bot.py unchanged; shared names
are read through `bot` (bots/__init__.py)."""

import bot
from backend.app.execution_safety import futures_net_pnl
from datetime import datetime, timezone


def trend_mode():
    """Daily trend runs alone on daily candles, long only, exits when the trend turns (strategies_trend.py)."""
    return "trend_daily" in (bot.CONFIG.get("enabled_strategies") or [])

def analyze_trend(symbol, df):
    """Daily trend on the closed daily candles (the last row from the exchange is still forming)."""
    import strategies_trend as stt
    closed=df.iloc[:-1]; on,size=stt.signal_now(list(closed.close)); exit_below=stt.exit_level(list(closed.close))
    price=float(df.close.iloc[-1]); lev=int(bot.CONFIG.get("leverage",2))
    sr_info=bot.sr_signal(df)[2]; rsi_info=bot.rsi_macd_signal(df)[2]
    reason=f"ترند صاعد — حجم {size*100:.0f}%" if on else "مفيش ترند صاعد"
    return {"symbol":symbol,"price":price,"total":1.0 if on else 0.0,"decision":"شراء" if on else "انتظار",
            "breakdown":{"trend_daily":(1.0 if on else 0.0,reason)},"amount_mult":1.0,
            "sl":price*(1-stt.STOP_SHARE/lev),"tp":None,"rsi":rsi_info["rsi"],"supports":sr_info["supports"],"resistances":sr_info["resistances"],
            "trend":{"on":on,"size":size,"ts":int(closed.ts.iloc[-1].value//10**6),"exit_below":exit_below},"time":datetime.now(timezone.utc).isoformat()}

def try_enter_trend(symbol, analysis, state, ex):
    """Daily trend: buy at market when the last closed daily candle turns the trend on; sell when it turns off.
    Live: market buy, then a stop on the exchange at the protective level (no target — the exit is the signal)."""
    import strategies_trend as stt
    sig=analysis.get("trend"); price=analysis["price"]
    if not sig: return
    live = not bot.CONFIG["paper_trading"]
    if bot.in_position(state, symbol):
        if sig["on"]: return
        pos=state["positions"][symbol]
        if live:
            try:
                res = bot.close_live_position(ex, symbol, pos, price)
                bot._require_verified_close(res)
            except Exception as e:
                bot.log(f"⚠️ {symbol}: الترند وقف بس القفل فشل — هيحاول تاني الدورة الجاية: {e}")
                bot.notify(f"⚠️ {symbol}: الترند وقف بس أمر القفل فشل — البوت هيحاول تاني. الوقف لسه على المنصة."); return
            exit_px, qty = res["price"], res["qty"]
        else:
            exit_px, qty = price, pos["qty"]
        if live:
            cs = bot._position_contract_size(pos)
            if cs is None:
                raise RuntimeError("missing contract_size for live PnL")
            pnl = futures_net_pnl(pos["entry"], exit_px, qty, cs, pos.get("side", "long"), fee_rate=bot._fee_rate(pos, required=True), funding_pnl=bot._funding_pnl(pos, required=True))
            margin = pos["entry"] * qty * cs / max(1, int(pos.get("leverage", bot.CONFIG.get("leverage", 1))))
        else:
            pnl = (exit_px-pos["entry"])*qty
            margin = pos["entry"] * qty
        mode = bot._live_label() if live else "Paper"
        bot.log(f"📉 اغلاق {symbol} — الترند وقف @ {exit_px:.6g} PnL {pnl:+.4f}")
        state["history"].append({"symbol":symbol,"side":"long","entry":pos["entry"],"exit":exit_px,"qty":qty,"pnl":pnl,"pnl_pct":pnl/margin*100 if margin else 0,"reason":"الترند وقف","time":datetime.now(timezone.utc).isoformat(),"type":"live" if live else "paper","opened":pos.get("time"),"rank":pos.get("rank")})
        state["stats"]["trades"]+=1; state["stats"]["pnl"]+=float(pnl); state["stats"]["wins" if pnl>0 else "losses"]+=1
        state["positions"].pop(symbol,None); state["last_trade"][symbol]=datetime.now(timezone.utc).isoformat()
        if live: bot._closed_cleanly(state, symbol)
        bot.save_state(state)
        if live: bot._release_position_risk(symbol, pos)
        return
    # paper: a coin closed by hand waits for its trend to turn off and on again. Live (the owner's account): a manual
    # close frees the slot and the strategy keeps trading as usual — it may buy the coin again on its next signal
    hold = state.get("manual_hold", {}) if not live else {}
    if symbol in hold:   # closed by hand: wait for the trend to turn off, then a new signal may buy it again
        if not sig["on"]: hold.pop(symbol, None); bot.save_state(state)
        return
    if not analysis.get("in_universe", True): return   # not in the volume top list today: no new trade
    seen=state.setdefault("trend_seen",{})
    if not sig["on"] or seen.get(symbol)==sig["ts"]: return   # one entry per closed daily candle, like the backtest
    if live and bot._ENTRY_BLOCK["reason"]:
        bot.log(f"⛔ {symbol} مفيش دخول — {bot._ENTRY_BLOCK['reason']}"); return   # retried next cycle (trend_seen not marked)
    seen[symbol]=sig["ts"]; bot.save_state(state)
    if bot._strategy_full(state, bot.CONFIG["max_open_positions"]) or not bot.daily_pnl_ok(state): return
    lev=int(bot.CONFIG.get("leverage",2))
    margin=bot.position_size(price, ex, stop_price=sig.get("stop"))*sig["size"]
    if not live:
        try:
            res=bot.place_order(ex,symbol,"long",margin,price)
            sl=res["price"]*(1-stt.STOP_SHARE/lev)
            state["positions"][symbol]={"side":"long","entry":res["price"],"qty":res["qty"],"cost":res["cost"],"notional":res.get("notional"),"contract_size":res.get("contract_size", 1.0),"contract_size_verified":res.get("contract_size_verified", False),"entry_fee_rate":res.get("entry_fee_rate"),"entry_fee_cost":res.get("entry_fee_cost"),"leverage":res.get("leverage",lev),
                "time":datetime.now(timezone.utc).isoformat(),"sl":sl,"tp":None,"breakeven":False,"trend":True,"rank":analysis.get("rank")}
            state["last_trade"][symbol]=datetime.now(timezone.utc).isoformat(); bot.save_state(state)
            bot.log(f"✅ 🟢 لونج وهمي {symbol} ترند يومي x{lev} @ {res['price']:.6g} حجم {sig['size']*100:.0f}% وقف حماية {sl:.6g}")
            bot.notify(f"🟢 لونج {symbol} — ترند يومي x{lev} (Paper)\nدخول {res['price']:.6g} · حجم {sig['size']*100:.0f}% من ${bot.position_size(price, ex)*lev:.0f}\nوقف حماية {sl:.6g} · الخروج لما الترند يقف")
        except Exception as e: bot.log(f"فشل long {symbol}: {e}")
        return
    bot._enter_trend_live(symbol, analysis, state, ex, margin, lev, price)
