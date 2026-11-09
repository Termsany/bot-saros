"""trend_breakout — trend-template breakout: among the top 100 by volume in a stage-2 uptrend, buy a close above the
previous 20 days' high; sell on a close below the 20-day average, stop 40%. Live: bot._single_leg_live_entry /
_single_leg_live_exit. Moved from bot.py unchanged; shared names are read through `bot` (bots/__init__.py)."""

import bot
from datetime import datetime, timezone


# ── trend-template breakout: what was left of Minervini / Darvas after research/vcp_deep.py (the contraction and the
#    breakout-volume conditions only hurt). Paper experiment — it added profit but not risk-adjusted return. ──
TB = {"top": 100, "L": 20, "exit_ma": 20, "stop": 0.40, "slip": 0.0005}

def tbreak_mode():
    """Paper trend-template breakout: at each daily close, among the top 100 by 30-day volume in a stage-2 uptrend
    (close > 50 > 150 > 200-day averages), buy when the close breaks the previous 20 days' high; sell after a close
    below the 20-day average; stop 40%."""
    return "trend_breakout" in (bot.CONFIG.get("enabled_strategies") or [])

def run_once_tbreak(ex):
    T = bot.TB; state = bot.load_state(); now = datetime.now(timezone.utc); day = bot._utc_day(now); prices = {}
    if not bot.CONFIG["paper_trading"]:
        # a block (recovery, kill switch, unknown position) stops entries only — the live adapters refuse them. The
        # strategy's own exits still run: returning here left open positions without their signal exits
        bot.reconcile_live(state, ex)
        if bot._ENTRY_BLOCK.get("reason"): bot.log(f"⛔ دخول جديد متوقف، الخروج شغّال — {bot._ENTRY_BLOCK['reason']}")
    bot.process_paper_closes(state, ex, "tbreak")
    if not bot.CONFIG["paper_trading"]:
        bot.process_manual_closes(state, ex, prices); bot._retry_due_exits(ex, state, "اختراق الترند")
    bot._guard_stops(ex, state, prices, "اختراق الترند")
    if state.get("tb_day") != day.isoformat():
        universe = bot.volume_universe(ex, T["top"]); watch = []; opened = []
        sma = lambda xs, n: sum(xs[-n:]) / n
        for sym in sorted(set(universe) | set(state["positions"])):
            try:
                k = ex.fetch_ohlcv(sym, "1d", limit=215)[:-1]          # closed candles only
                c = [r[4] for r in k]; h = [r[2] for r in k]
                if len(c) < T["exit_ma"] + 1: continue
                if sym in state["positions"]:
                    if c[-1] < sma(c, T["exit_ma"]):
                        price = float(ex.fetch_ticker(sym)["last"]); prices[sym] = price
                        if bot.CONFIG.get("paper_trading"):
                            pnl = bot._paper_close(ex, state, sym, price, f"قفل تحت متوسط {T['exit_ma']} يوم")
                            bot.log(f"📉 اختراق الترند: قفل {sym} @ {price:.6g} PnL {pnl:+.4f}")
                        else:
                            bot._single_leg_live_exit(ex, state, sym, price, f"قفل تحت متوسط {T['exit_ma']} يوم")
                        if sym in state["positions"]:
                            continue
                        bot.log(f"📉 اختراق الترند: قفل {sym} @ {price:.6g}" if not bot.CONFIG.get("paper_trading") else "")
                    continue
                if sym not in universe or len(c) < 201: continue
                m50, m150, m200 = sma(c, 50), sma(c, 150), sma(c, 200); hi = max(h[-T["L"] - 1:-1])
                if not (c[-1] > m50 > m150 > m200): continue
                watch.append({"symbol": sym.split(":")[0], "close": c[-1], "high": hi, "gap_pct": round((hi / c[-1] - 1) * 100, 1)})
                if c[-1] > hi:
                    price = float(ex.fetch_ticker(sym)["last"]) * (1 + T["slip"]); prices[sym] = price
                    if bot.CONFIG.get("paper_trading"):
                        bot._paper_open(state, sym, price, now, {"sl": price * (1 - T["stop"]), "breakout": hi})
                    elif not bot._single_leg_live_entry(ex, state, sym, "long", bot.position_size(price, ex),
                            price, price * (1 - T["stop"]), None, "trend_breakout", {"breakout": hi}):
                        continue
                    opened.append(f"{sym.split('/')[0]} {price:.6g}")
                    bot.log(f"✅ 🟢 اختراق الترند {sym} @ {price:.6g} (قفل {c[-1]:.6g} فوق أعلى {T['L']} يوم {hi:.6g})")
            except Exception as e: bot.log(f"اختراق الترند {sym}: {e}")
        if opened:
            bot.notify(f"🟢 اختراق الترند (Paper) — {len(opened)} صفقة جديدة\n" + "\n".join(opened) +
                   f"\nخروج: قفل يومي تحت متوسط {T['exit_ma']} يوم · وقف 40%")
        state.update(tb_day=day.isoformat(), tb_watch=sorted(watch, key=lambda w: w["gap_pct"])[:15]); bot.save_state(state)
    for sym in state["positions"]:
        if sym not in prices:
            try: prices[sym] = float(ex.fetch_ticker(sym)["last"])
            except Exception: pass
    bot.write_simple_status("tbreak", state, prices, T, {"day": state.get("tb_day"), "watch": state.get("tb_watch", [])})
    bot.log(f"📊 اختراق الترند: {len(state['positions'])} مفتوحة | PnL محقق {state['stats']['pnl']:+.4f}")
