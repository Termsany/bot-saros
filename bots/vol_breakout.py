"""vol_breakout — Larry Williams' volatility breakout: among the top 10 by volume above their 20-day average, buy at
today's open + 0.7 x yesterday's range, sell at the next day's open, 40% guard stop. Live: bot._single_leg_live_entry /
_single_leg_live_exit. Moved from bot.py unchanged; shared names are read through `bot` (bots/__init__.py)."""

import bot
import pandas as pd
from datetime import datetime, timezone


# ── Williams volatility breakout + Connors RSI-2: two paper bots on Binance's public market (research/traders_study.py,
#    traders_robustness.py, breakout_stop_hourly.py) ──
VB = {"top": 10, "k": 0.7, "ma": 20, "stop": 0.40, "slip": 0.001}

def breakout_mode():
    """Paper volatility breakout (Larry Williams): each UTC day, among the top 10 by 30-day volume whose close is above
    its 20-day average, buy when the price trades 0.7 x yesterday's range above today's open; sell at the next day's
    open. No intraday stop (it cut profit in every hourly test), only the 40% guard before liquidation."""
    return "vol_breakout" in (bot.CONFIG.get("enabled_strategies") or [])

def run_once_breakout(ex):
    V = bot.VB; state = bot.load_state(); now = datetime.now(timezone.utc); day = bot._utc_day(now); prices = {}
    if not bot.CONFIG["paper_trading"]:
        # a block (recovery, kill switch, unknown position) stops entries only — the live adapters refuse them. The
        # strategy's own exits still run: returning here left open positions without their signal exits
        bot.reconcile_live(state, ex)
        if bot._ENTRY_BLOCK.get("reason"): bot.log(f"⛔ دخول جديد متوقف، الخروج شغّال — {bot._ENTRY_BLOCK['reason']}")
    bot.process_paper_closes(state, ex, "breakout")
    if not bot.CONFIG["paper_trading"]:
        bot.process_manual_closes(state, ex, prices); bot._retry_due_exits(ex, state, "بريك أوت")
    bot._guard_stops(ex, state, prices, "بريك أوت")
    if state.get("vb_day") != day.isoformat():
        # a new UTC day: yesterday's trades close at today's open, then today's triggers
        day_ms = int(day.timestamp() * 1000); closed = 0.0; n = 0
        for sym in list(state["positions"]):
            try:
                k = ex.fetch_ohlcv(sym, "1d", limit=2)
                px_open = float(k[-1][1]) if k and k[-1][0] == day_ms else float(ex.fetch_ticker(sym)["last"])
                if bot.CONFIG.get("paper_trading"):
                    closed += bot._paper_close(ex, state, sym, px_open, "خروج افتتاح اليوم")
                    n += 1
                elif bot._single_leg_live_exit(ex, state, sym, px_open, "خروج افتتاح اليوم"):
                    closed += 1.0; n += 1
            except Exception as e: bot.log(f"بريك أوت قفل {sym}: {e}")
        plan = {}
        for sym in bot.volume_universe(ex, V["top"]):
            try:
                k = ex.fetch_ohlcv(sym, "1d", limit=V["ma"] + 3)
                if not k or k[-1][0] != day_ms: continue                  # today's candle not open yet
                closes = [r[4] for r in k[:-1]]; prev = k[-2]; rng = prev[2] - prev[3]
                avg = sum(closes[-V["ma"]:]) / V["ma"]
                plan[sym] = {"open": k[-1][1], "trigger": k[-1][1] + V["k"] * rng if rng > 0 else None, "above_ma": closes[-1] > avg,
                             "range": rng}
            except Exception as e: bot.log(f"بريك أوت {sym}: {e}")
        state.update(vb_day=day.isoformat(), vb_plan=plan, vb_done=[]); bot.save_state(state)
        armed = [f"{s.split('/')[0]} {p['trigger']:.6g}" for s, p in plan.items() if p["above_ma"] and p["trigger"]]
        bot.log(f"📐 بريك أوت: يوم جديد — قفل {n} صفقة {closed:+.2f}$ | مستني اختراق: {', '.join(armed) or 'ولا عملة فوق متوسط 20'}")
        if n: bot.notify(f"📐 بريك أوت (Paper): قفل {n} صفقة امبارح على افتتاح النهارده — {closed:+.2f}$")
    bot._guard_stops(ex, state, prices, "بريك أوت")
    plan = state.get("vb_plan") or {}
    for sym, p in plan.items():
        if not (p.get("above_ma") and p.get("trigger")) or sym in state["positions"] or sym in state.get("vb_done", []): continue
        try:
            price = prices.get(sym) or float(ex.fetch_ticker(sym)["last"]); prices[sym] = price
            if price < p["trigger"]: continue
            fill = price * (1 + V["slip"])
            if bot.CONFIG.get("paper_trading"):
                bot._paper_open(state, sym, fill, now, {"sl": fill * (1 - V["stop"]), "trigger": p["trigger"],
                                                    "exit_at": (day + pd.Timedelta(days=1)).isoformat()})
                state.setdefault("vb_done", []).append(sym); bot.save_state(state)
            else:
                pos = bot._single_leg_live_entry(ex, state, sym, "long", bot.position_size(price, ex),
                    fill, fill * (1 - V["stop"]), None, "vol_breakout",
                    {"trigger": p["trigger"], "exit_at": (day + pd.Timedelta(days=1)).isoformat()})
                if not pos: continue
                state.setdefault("vb_done", []).append(sym); bot.save_state(state)
            bot.log(f"✅ 🟢 بريك أوت {sym} @ {fill:.6g} (الاختراق {p['trigger']:.6g})")
            bot.notify(f"🟢 بريك أوت {sym.split(':')[0]} (Paper)\nاخترق {p['trigger']:.6g} — دخول {fill:.6g}\nخروج: افتتاح بكرة 00:00 UTC · وقف أمان {fill * (1 - V['stop']):.6g}")
        except Exception as e: bot.log(f"بريك أوت دخول {sym}: {e}")
    bot.write_simple_status("breakout", state, prices, V, {"day": state.get("vb_day"),
        "plan": [{"symbol": s.split(":")[0], "open": p["open"], "trigger": p["trigger"], "above_ma": p["above_ma"],
                  "entered": s in state.get("vb_done", []), "price": prices.get(s)} for s, p in plan.items()]})
    bot.log(f"📊 بريك أوت: {len(state['positions'])} مفتوحة | PnL محقق {state['stats']['pnl']:+.4f}")
