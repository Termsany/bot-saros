"""rsi2_pullback — Larry Connors' RSI-2: among the top 10 by volume above their 200-day average, buy when the 2-day RSI
is below 5; sell on a close above the 5-day average or after 10 days, stop 40%. Live: bot._single_leg_live_entry /
_single_leg_live_exit. Moved from bot.py unchanged; shared names are read through `bot` (bots/__init__.py)."""

import bot
import pandas as pd
from datetime import datetime, timezone


RSI2 = {"top": 10, "below": 5, "trend_ma": 200, "exit_ma": 5, "max_days": 10, "stop": 0.40}

def rsi2_mode():
    """Paper RSI-2 pullback (Larry Connors): at each daily close, among the top 10 by 30-day volume above their 200-day
    average, buy when the 2-day RSI is below 5; sell after a close above the 5-day average or 10 days, stop 40%."""
    return "rsi2_pullback" in (bot.CONFIG.get("enabled_strategies") or [])

def rsi_wilder(closes, n=2):
    s = pd.Series(closes, dtype=float); d = s.diff().fillna(0)
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return float(100.0 if dn.iloc[-1] == 0 else 100 - 100 / (1 + up.iloc[-1] / dn.iloc[-1]))

def run_once_rsi2(ex):
    R = bot.RSI2; state = bot.load_state(); now = datetime.now(timezone.utc); day = bot._utc_day(now); prices = {}
    if not bot.CONFIG["paper_trading"]:
        # a block (recovery, kill switch, unknown position) stops entries only — the live adapters refuse them. The
        # strategy's own exits still run: returning here left open positions without their signal exits
        bot.reconcile_live(state, ex)
        if bot._ENTRY_BLOCK.get("reason"): bot.log(f"⛔ دخول جديد متوقف، الخروج شغّال — {bot._ENTRY_BLOCK['reason']}")
    bot.process_paper_closes(state, ex, "rsi2")
    if not bot.CONFIG["paper_trading"]:
        bot.process_manual_closes(state, ex, prices); bot._retry_due_exits(ex, state, "RSI-2")
    bot._guard_stops(ex, state, prices, "RSI-2")
    if state.get("rsi2_day") != day.isoformat():
        # once per closed daily candle: exits first, then new entries at about today's open
        universe = bot.volume_universe(ex, R["top"]); watch = []
        for sym in sorted(set(universe) | set(state["positions"])):
            try:
                k = ex.fetch_ohlcv(sym, "1d", limit=R["trend_ma"] + 15)[:-1]   # closed candles only
                c = [r[4] for r in k]
                if len(c) < R["exit_ma"] + 1: continue
                price = float(ex.fetch_ticker(sym)["last"]); prices[sym] = price
                if sym in state["positions"]:
                    pos = state["positions"][sym]
                    held = (day - bot._utc_day(datetime.fromisoformat(pos["time"]))).days
                    if c[-1] > sum(c[-R["exit_ma"]:]) / R["exit_ma"] or held >= R["max_days"]:
                        why = f"قفل فوق متوسط {R['exit_ma']} يوم" if c[-1] > sum(c[-R["exit_ma"]:]) / R["exit_ma"] else f"{R['max_days']} أيام"
                        if bot.CONFIG.get("paper_trading"):
                            pnl = bot._paper_close(ex, state, sym, price, why)
                        else:
                            bot._single_leg_live_exit(ex, state, sym, price, why)
                        if sym in state["positions"]:
                            continue
                        bot.log(f"📉 RSI-2: قفل {sym} @ {price:.6g} ({why}) PnL {pnl:+.4f}" if bot.CONFIG.get("paper_trading") else f"📉 RSI-2: قفل {sym} @ {price:.6g} ({why})")
                    continue
                if sym not in universe or len(c) < R["trend_ma"]: continue
                r2 = bot.rsi_wilder(c, 2); ma = sum(c[-R["trend_ma"]:]) / R["trend_ma"]
                watch.append({"symbol": sym.split(":")[0], "rsi2": round(r2, 1), "above_200": c[-1] > ma, "price": price})
                if r2 < R["below"] and c[-1] > ma:
                    sl = price * (1 - R["stop"])
                    if bot.CONFIG.get("paper_trading"):
                        bot._paper_open(state, sym, price, now, {"sl": sl, "rsi2": round(r2, 1),
                                                             "exit_at": (day + pd.Timedelta(days=R["max_days"])).isoformat()})
                    elif not bot._single_leg_live_entry(ex, state, sym, "long", bot.position_size(price, ex),
                            price, sl, None, "rsi2_pullback", {"rsi2": round(r2, 1),
                            "exit_at": (day + pd.Timedelta(days=R["max_days"])).isoformat()}):
                        continue
                    bot.log(f"✅ 🟢 RSI-2 {sym} @ {price} (RSI-2 {r2:.1f} في ترند صاعد)")
                    bot.notify(f"🟢 RSI-2 {sym.split(':')[0]} (Paper)\nRSI-2 {r2:.1f} وفوق متوسط 200 يوم — دخول {price:.6g}\nخروج: أول قفل يومي فوق متوسط 5 أيام (أقصى {R['max_days']} أيام) · وقف {price * (1 - R['stop']):.6g}")
            except Exception as e: bot.log(f"RSI-2 {sym}: {e}")
        state.update(rsi2_day=day.isoformat(), rsi2_watch=watch); bot.save_state(state)
    for sym in state["positions"]:
        if sym not in prices:
            try: prices[sym] = float(ex.fetch_ticker(sym)["last"])
            except Exception: pass
    bot.write_simple_status("rsi2", state, prices, R, {"day": state.get("rsi2_day"), "watch": state.get("rsi2_watch", [])})
    bot.log(f"📊 RSI-2: {len(state['positions'])} مفتوحة | PnL محقق {state['stats']['pnl']:+.4f}")
