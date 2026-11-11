"""momentum_ls — cross-sectional momentum on Binance USDT-M: every week (Monday 00:00 UTC) long the 5 strongest and
short the 5 weakest of the top 50 by volume on their last 2 weeks' return, stop 40%. Live: one basket per rebalance
through bot._phase2_live_basket. Moved from bot.py unchanged; shared names are read through `bot` (bots/__init__.py)."""

import bot
import json
import pandas as pd
from datetime import datetime, timezone
from pathlib import Path


# Monday and the full week from 2026-11-03 to 2026-11-11.
# weekday 2 = Wednesday, hold 6 days (owner, 2026-11-11; research/README.md §23): the basket opens on Wednesday
# 00:00 UTC, closes on Tuesday 00:00 and stays flat until the next Wednesday. The best open day that held up both before
# 2024 and after (Wednesday-6: +$2,527, worst DD $323, Sharpe 0.83 / 1.34; Monday-7: +$1,943, $476, 0.60 / 1.15).
MOM = {"weeks": 2, "top": 50, "n": 5, "min_days": 60, "stop": 0.40, "every_days": 7, "weekday": 2, "score": "return", "min_ranked": 20, "hold_days": 6, "catch_up_days": 1}
# hold_days < every_days: the basket closes that many days after its week began and stays flat until the next
# rebalance. bot.py --mom-weekday / --mom-hold change these two on Demo only: real money runs the defaults.
# catch_up_days: a week whose open was missed (bot down, kill switch, foreign positions) still opens up to that many
# days late (Thursday); after that the bot waits for the next Wednesday rather than open a basket for a few days.

# --momentum-retail (owner, 2026-11-07; research §29, paper only): the same weekly basket, ranked against the crowd —
# among the top 20 by 30-day volume (150+ days listed), long the 3 whose all-accounts long/short ratio (Binance, the
# last 3 days' hourly values) is lowest, short the 3 where it is highest; every Wednesday, as the study's weeks ran
RETAIL = {"top": 20, "n": 3, "min_days": 150, "weekday": 2, "score": "retail", "ls_hours": 72, "min_ranked": 8, "hold_days": 7}


def momentum_public_name():
    """The momentum bot's public file and paper close-request folder: "momentum", or --public-name for a second one."""
    return bot.CONFIG.get("public_name") or "momentum"


def retail_ratio(ex, sym):
    """Mean of Binance's all-accounts long/short ratio over the last RETAIL ls_hours hours, or None."""
    rows = ex.fapiDataGetGlobalLongShortAccountRatio({"symbol": sym.split("/")[0] + "USDT", "period": "1h", "limit": RETAIL["ls_hours"]})
    vals = [float(r["longShortRatio"]) for r in rows or [] if r.get("longShortRatio") not in (None, "")]
    return sum(vals) / len(vals) if len(vals) >= RETAIL["ls_hours"] // 2 else None


def momentum_hold_over(last_iso, today, hold_days=None, every_days=None):
    """True when the basket of the week that began at `last_iso` has been held `hold_days` and must close before the
    next rebalance (Wednesday-6: Tuesday 00:00). Never with a full week's hold: the rebalance itself closes it."""
    hold = int(hold_days if hold_days is not None else MOM["hold_days"])
    every = int(every_days if every_days is not None else MOM["every_days"])
    if not last_iso or hold >= every:
        return False
    return today >= datetime.fromisoformat(last_iso) + pd.Timedelta(days=hold)


def momentum_slot(today, weekday=None):
    """The start of the basket week `today` (00:00 UTC) falls in: the latest `weekday` on or before it."""
    weekday = MOM["weekday"] if weekday is None else weekday
    return today - pd.Timedelta(days=(today.weekday() - weekday) % 7)


def momentum_due(last_iso, today, every_days=None, weekday=None, hold_days=None, catch_up_days=None):
    """The basket is rebuilt at the first cycle after 00:00 UTC on `weekday`, once per week. A week whose day was
    missed (the bot down, or entries blocked) is caught up at most `catch_up_days` later, and never in the flat days
    after `hold_days`; mom_last then records the week's start, so a late basket keeps the week's close. No rebalance
    yet: the same window. `today` is 00:00 UTC. Without a weekday (weekday=False): every `every_days` from the last."""
    every = int(every_days if every_days is not None else MOM["every_days"])
    weekday = MOM["weekday"] if weekday is None else weekday
    hold = int(hold_days if hold_days is not None else MOM["hold_days"])
    late = int(catch_up_days if catch_up_days is not None else MOM.get("catch_up_days", 1))
    if weekday is False:
        return not last_iso or today - datetime.fromisoformat(last_iso) >= pd.Timedelta(days=every)
    slot = momentum_slot(today, weekday)
    if today >= slot + pd.Timedelta(days=min(hold, every, late + 1)):
        return False                                       # too late in the week: wait for the next one
    return not last_iso or datetime.fromisoformat(last_iso) < slot


def momentum_next(last_iso, every_days=None, weekday=None):
    """The next rebalance's day (00:00 UTC) after the one recorded: the next `weekday`, within `every_days`."""
    if not last_iso:
        return None
    every_days = MOM["every_days"] if every_days is None else every_days
    weekday = MOM["weekday"] if weekday is None else weekday
    last = datetime.fromisoformat(last_iso)
    if weekday is False:
        return last + pd.Timedelta(days=every_days)
    return last + pd.Timedelta(days=(weekday - last.weekday()) % 7 or 7)

def momentum_mode():
    """Paper cross-sectional momentum on Binance: every 7 days rank the top 50 USDT perpetuals by 30-day volume on
    their last 2 weeks' return, long the strongest 5 and short the weakest 5 for a week, stop 40% —
    research/pump_momentum_study.py idea 2 (Liu, Tsyvinski & Wu 2022)."""
    return "momentum_ls" in (bot.CONFIG.get("enabled_strategies") or [])

def momentum_rank(ex):
    """[(symbol, return over MOM weeks)] weakest first, among the top MOM["top"] by 30-day average USDT volume
    (crypto perpetuals with >= min_days closed daily candles)."""
    syms = [s for s, _, _ in bot.listing_markets(ex)]
    tick = ex.fetch_tickers()
    cands = sorted(syms, key=lambda s: -float((tick.get(s) or {}).get("quoteVolume") or 0))[:bot.MOM["top"] * 3]
    rows = []
    for sym in cands:
        try:
            k = ex.fetch_ohlcv(sym, "1d", limit=max(70, bot.MOM["min_days"] + 10))[:-1]          # closed candles only
            if len(k) < bot.MOM["min_days"]: continue
            rows.append((sum(r[4] * r[5] for r in k[-30:]) / 30, sym, k[-1][4] / k[-1 - 7 * bot.MOM["weeks"]][4] - 1))
        except Exception as e: bot.log(f"momentum {sym}: {e}")
    top = sorted(rows, reverse=True)[:bot.MOM["top"]]
    if bot.MOM.get("score") == "retail":
        # against the crowd: the highest long/short ratio first (the shorts), the lowest last (the longs)
        scored = []
        for _, sym, _ in top:
            try:
                r = retail_ratio(ex, sym)
                if r is not None: scored.append((sym, r))
            except Exception as e: bot.log(f"retail ratio {sym}: {e}")
        return sorted(scored, key=lambda x: -x[1])
    return [(sym, ret) for _, sym, ret in sorted(top, key=lambda r: r[2])]

def run_once_momentum(ex):
    M = bot.MOM; state = bot.load_state(); now = datetime.now(timezone.utc); prices = {}
    if not bot.CONFIG["paper_trading"]:
        # a block (recovery, kill switch, unknown position) stops entries only — the live adapters refuse them. The
        # strategy's own exits still run: returning here left open positions without their signal exits
        bot.reconcile_live(state, ex)
        if bot._ENTRY_BLOCK.get("reason"): bot.log(f"⛔ دخول جديد متوقف، الخروج شغّال — {bot._ENTRY_BLOCK['reason']}")
        bot.process_manual_closes(state, ex, {})   # the site's close button (it waited unanswered for the basket bots)
    bot.process_paper_closes(state, ex, momentum_public_name())
    # protective stops during the week (paper; live, the stop order is on the exchange and reconcile_live books its fill —
    # _paper_close here dropped the live position from the books without closing it on the exchange)
    for sym, pos in (list(state["positions"].items()) if bot.CONFIG["paper_trading"] else []):
        try:
            price = float(ex.fetch_ticker(sym)["last"]); prices[sym] = price
            hit = price >= pos["sl"] if pos["side"] == "short" else price <= pos["sl"]
            if hit:
                pnl = bot._paper_close(ex, state, sym, price, f"وقف {pos['sl']:.6g}"); bot.save_state(state)
                bot.log(f"🔒 وقف {pos['side']} {sym} @ {price:.6g} PnL {pnl:+.4f}")
        except Exception as e: bot.log(f"مومنتم {sym}: {e}")
    # weekly rebalance, at the first cycle after the daily close (00:00 UTC) on Wednesday (momentum_due). mom_last
    # records the week's start (momentum_slot), not the day a late basket opened: the close stays on the week's Tuesday
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    last = state.get("mom_last")
    week = momentum_slot(today, M.get("weekday")).isoformat() if M.get("weekday") is not False else today.isoformat()
    # the week's close (hold_days from its start): flat from here until the next rebalance day
    if state["positions"] and momentum_hold_over(last, today, M.get("hold_days"), M["every_days"]):
        if not bot.CONFIG["paper_trading"]:
            exits = []
            for sym in sorted(state["positions"]):
                px = float(ex.fetch_ticker(sym)["last"]); pos = state["positions"][sym]
                exits.append({"symbol": sym, "side": "close_" + pos["side"], "action": "exit", "position": pos, "price": px, "order": 0,
                              "risk_usdt": 0, "notional_usdt": 0, "correlation_group": bot._correlation_group(sym)})
            result = bot._phase2_live_basket(ex, state, "momentum_ls", "momentum-hold-exit", exits, reserve=False)
            if not result or result.get("status") != "filled":
                bot.save_state(state); return
        else:
            for sym in list(state["positions"]):
                try: bot._paper_close(ex, state, sym, float(ex.fetch_ticker(sym)["last"]), f"خروج بعد {M['hold_days']} أيام")
                except Exception as e: bot.log(f"قفل {sym}: {e}")
        bot.save_state(state)
        bot.log(f"⏹️ مومنتم: السلة اتقفلت بعد {M['hold_days']} أيام — مفيش صفقات لحد التبديل الجاي")
    if bot.momentum_due(last, today, M["every_days"], M.get("weekday"), M.get("hold_days"), M.get("catch_up_days")):
        ranked = bot.momentum_rank(ex)
        if len(ranked) >= M.get("min_ranked", 20) and len(ranked) >= 2 * M["n"]:
            closed = 0.0
            lev = int(bot.CONFIG.get("leverage", 2)); picks = [(s, r, "short") for s, r in ranked[:M["n"]]] + [(s, r, "long") for s, r in ranked[-M["n"]:]]
            if not bot.CONFIG["paper_trading"]:
                exits = []
                for sym in sorted(state["positions"]):
                    px = float(ex.fetch_ticker(sym)["last"]); pos = state["positions"][sym]
                    exits.append({"symbol": sym, "side": "close_" + pos["side"], "action": "exit", "position": pos, "price": px, "order": 0,
                                  "risk_usdt": 0, "notional_usdt": 0, "correlation_group": bot._correlation_group(sym)})
                if exits:
                    closed_result = bot._phase2_live_basket(ex, state, "momentum_ls", "momentum-rebalance-exit", exits, reserve=False)
                    if not closed_result or closed_result.get("status") != "filled":
                        bot.save_state(state); return
                entries = []
                for sym, ret, side in picks:
                    px = float(ex.fetch_ticker(sym)["last"]); prices[sym] = px
                    stop = px * (1 + M["stop"]) if side == "short" else px * (1 - M["stop"])
                    entries.append(bot._phase2_leg(sym, side, bot.position_size(px), px, stop, None, "momentum_ls", extra={"ret": ret}))
                result = bot._phase2_live_basket(ex, state, "momentum_ls", "momentum-rebalance-entry", entries)
                if result and result.get("status") == "filled":
                    state["mom_last"] = week; state["mom_ranking"] = [{"symbol": s.split(":")[0], "ret": round(r * 100, 1)} for s, r in ranked]; bot.save_state(state)
                return
            for sym in list(state["positions"]):
                try:
                    price = float(ex.fetch_ticker(sym)["last"]); closed += bot._paper_close(ex, state, sym, price, "تبديل أسبوعي")
                except Exception as e: bot.log(f"قفل {sym}: {e}")
            for sym, ret, side in picks:
                try:
                    price = float(ex.fetch_ticker(sym)["last"]); prices[sym] = price; q = bot.position_size(price) * lev / price
                    sl = price * (1 + M["stop"]) if side == "short" else price * (1 - M["stop"])
                    state["positions"][sym] = {"side": side, "entry": price, "qty": q, "leverage": lev, "time": now.isoformat(),
                                               "sl": sl, "tp": None, "ret": ret}
                except Exception as e: bot.log(f"فتح {sym}: {e}")
            state["mom_last"] = week
            state["mom_ranking"] = [{"symbol": s.split(":")[0], "ret": round(r * 100, 1)} for s, r in ranked]
            bot.save_state(state)
            retail = M.get("score") == "retail"
            fmt = (lambda r: f"L/S {r:.2f}") if retail else (lambda r: f"{r * 100:+.0f}%")
            longs = ", ".join(f"{s.split('/')[0]} {fmt(r)}" for s, r, sd in picks if sd == "long")
            shorts = ", ".join(f"{s.split('/')[0]} {fmt(r)}" for s, r, sd in picks if sd == "short")
            bot.log(f"🔄 مومنتم: تبديل أسبوعي — قفل {closed:+.4f} | لونج: {longs} | شورت: {shorts}")
            if retail:
                bot.notify(f"🔄 عكس الأغلبية — تبديل أسبوعي (Paper)\nالأسبوع اللي فات: {closed:+.2f}$\n🟢 لونج (الأغلبية شورت): {longs}\n🔴 شورت (الأغلبية لونج): {shorts}")
            else:
                bot.notify(f"🔄 مومنتم — تبديل أسبوعي (Paper)\nالأسبوع اللي فات: {closed:+.2f}$\n🟢 لونج الأقوى: {longs}\n🔴 شورت الأضعف: {shorts}")
        else: bot.log(f"مومنتم: {len(ranked)} عملة بس في القائمة — مفيش تبديل")
        if M.get("score") == "retail":       # its ranking on the page: the crowd's ratio, not a 2-week return
            state["mom_ranking"] = [{"symbol": s.split(":")[0], "ratio": round(r, 3)} for s, r in ranked]; bot.save_state(state)
    for sym in state["positions"]:
        if sym not in prices:
            try: prices[sym] = float(ex.fetch_ticker(sym)["last"])
            except Exception: pass
    bot.write_momentum_status(state, prices)
    bot.log(f"📊 مومنتم: {len(state['positions'])} مفتوحة | PnL محقق {state['stats']['pnl']:+.4f}")

def write_momentum_status(state, prices):
    out_dir = bot.CONFIG.get("public_dir")
    if not out_dir: return
    pos = []
    for sym, p in state["positions"].items():
        price = prices.get(sym, p["entry"]); sg = 1 if p["side"] == "long" else -1
        pnl = sg * (price - p["entry"]) * p["qty"]; margin = p["entry"] * p["qty"] / max(1, int(p.get("leverage", 2)))
        pos.append({"symbol": sym.split(":")[0], "id": sym.split("/")[0] + "USDT", "side": p["side"], "entry": p["entry"], "price": price,
                    "qty": p["qty"], "margin": round(margin, 2), "sl": p["sl"], "pnl": round(pnl, 4),
                    "pnl_pct": round(pnl / margin * 100, 2) if margin else 0, "opened": p["time"],
                    **({"ratio": round(float(p.get("ret", 0)), 3)} if bot.MOM.get("score") == "retail" else {"ret": round(p.get("ret", 0) * 100, 1)})})
    st = state.get("stats", {}); last = state.get("mom_last")
    data = {"updated": datetime.now(timezone.utc).isoformat(), "mode": "paper" if bot.CONFIG["paper_trading"] else "live", "rules": bot.MOM,
            "leverage": int(bot.CONFIG.get("leverage", 2)), "margin": bot.CONFIG.get("trade_amount_usdt"), "started": bot.CONFIG.get("started_at"),
            "last_rebalance": last, "next_rebalance": bot.momentum_next(last, bot.MOM["every_days"], bot.MOM["weekday"]).isoformat() if last else None,
            "stats": {"closed": st.get("trades", 0), "wins": st.get("wins", 0), "losses": st.get("losses", 0),
                      "realized": round(float(st.get("pnl", 0)), 4), "unrealized": round(sum(x["pnl"] for x in pos), 4), "open": len(pos)},
            "positions": sorted(pos, key=lambda x: (x["side"], -x.get("ret", 0), x.get("ratio", 0))),
            **({"ranking": state.get("mom_ranking", [])} if bot.MOM.get("score") == "retail" else {}),
            "history": [{"symbol": h["symbol"].split(":")[0], "side": h.get("side"), "entry": h["entry"], "exit": h["exit"], "pnl": bot._r4(h.get("pnl")),
                         "reason": h.get("reason", ""), "time": h.get("time"), "opened": h.get("opened"), "ret": h.get("ret")}
                        for h in state.get("history", [])[-300:]][::-1]}
    try:
        name = momentum_public_name(); d = Path(out_dir); tmp = d / f"{name}.json.tmp"
        tmp.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8"); tmp.replace(d / f"{name}.json")
    except Exception as e: bot.log(f"public momentum status: {e}")
