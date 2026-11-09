"""listing_short — short new Binance USDT-M listings 30 days after listing, hold 90 days, stop 40% above entry, at most
10 open. Live: one-leg baskets through bot._phase2_live_basket. The market list (bot.listing_markets) stays in bot.py:
momentum_ls and ratio_trend use it too. Moved from bot.py unchanged; shared names are read through `bot`."""

import bot
import json
import pandas as pd
from datetime import datetime, timezone
from pathlib import Path


LISTING = {"skip_days": 30, "hold_days": 90, "stop": 0.40, "max_open": 10, "catch_up_days": 3}

def listing_mode():
    """Paper short of new Binance USDT-M listings 30 days after listing, held 90 days, stop 40% above entry,
    at most 10 at once — research/short_study.py idea 2 (README "Short side")."""
    return "listing_short" in (bot.CONFIG.get("enabled_strategies") or [])

def _listing_close(ex, state, sym, price, reason):
    pos = state["positions"].pop(sym); q = pos["qty"]; fee = 0.0004
    funding = 0.0
    try:   # shorts receive positive funding and pay negative funding
        since = int(datetime.fromisoformat(pos["time"]).timestamp() * 1000)
        funding = sum(float(r["fundingRate"]) for r in ex.fetch_funding_rate_history(sym, since=since, limit=1000)) * q * pos["entry"]
    except Exception as e: bot.log(f"funding {sym}: {e}")
    pnl = (pos["entry"] - price) * q - (pos["entry"] * q + price * q) * fee + funding
    margin = pos["entry"] * q / max(1, int(pos.get("leverage", 2)))
    state["history"].append({"symbol": sym, "side": "short", "entry": pos["entry"], "exit": price, "qty": q, "pnl": pnl, "opened": pos["time"],
                             "pnl_pct": pnl / margin * 100 if margin else 0, "funding": funding, "reason": reason,
                             "time": datetime.now(timezone.utc).isoformat(), "type": "paper"})
    st = state["stats"]; st["trades"] += 1; st["pnl"] += pnl; st["wins" if pnl > 0 else "losses"] += 1
    bot.save_state(state)
    bot.log(f"🔒 قفل شورت {sym} — {reason} @ {price:.6g} PnL {pnl:+.4f} (funding {funding:+.4f})")
    return pnl

def run_once_listing(ex):
    L = bot.LISTING; state = bot.load_state(); now = datetime.now(timezone.utc)
    if not bot.CONFIG["paper_trading"]:
        # a block (recovery, kill switch, unknown position) stops entries only — the live adapters refuse them. The
        # strategy's own exits still run: returning here left open positions without their signal exits
        bot.reconcile_live(state, ex)
        if bot._ENTRY_BLOCK.get("reason"): bot.log(f"⛔ دخول جديد متوقف، الخروج شغّال — {bot._ENTRY_BLOCK['reason']}")
        bot.process_manual_closes(state, ex, {})   # the site's close button (it waited unanswered for the basket bots)
    bot.process_paper_closes(state, ex, "listing")
    done = state.setdefault("listing_done", {})
    mk = bot.listing_markets(ex); prices = {}
    # open shorts: protective stop and the 90-day exit
    for sym, pos in list(state["positions"].items()):
        try:
            price = float(ex.fetch_ticker(sym)["last"]); prices[sym] = price
            reason = f"وقف {pos['sl']:.6g}" if price >= pos["sl"] else f"خلصت {L['hold_days']} يوم" if now >= datetime.fromisoformat(pos["exit_at"]) else None
            if reason:
                if bot.CONFIG["paper_trading"]:
                    bot._listing_close(ex, state, sym, price, reason)
                else:
                    leg = {"symbol": sym, "side": "close_short", "action": "exit", "position": pos, "price": price, "order": 0,
                           "risk_usdt": 0, "notional_usdt": 0, "correlation_group": bot._correlation_group(sym)}
                    bot._phase2_live_basket(ex, state, "listing_short", f"listing-exit:{sym}", [leg], reserve=False)   # booked with its PnL
        except Exception as e: bot.log(f"شورت {sym}: {e}")
    # new entries: coins that just turned 30 days old (a few days of slack if the bot was down), oldest listing first;
    # like the backtest, a coin that comes up while all 10 slots are taken is skipped for good
    due = sorted([x for x in mk if L["skip_days"] <= x[2] < L["skip_days"] + L["catch_up_days"] and x[0] not in done], key=lambda x: x[1])
    if not bot.CONFIG["paper_trading"] and (bot._ENTRY_BLOCK.get("reason") or state.get("recovery_required")): due = []   # retried when unblocked
    for sym, listed, age in due:
        if bot.CONFIG["paper_trading"]: done[sym] = now.isoformat()   # live: only once the entry filled (below)
        if bot._strategy_full(state, L["max_open"]):
            done[sym] = now.isoformat()
            bot.log(f"⏸️ {sym} عدّى {L['skip_days']} يوم بس الـ {L['max_open']} أماكن مليانة — اتساب زي الباك تست"); continue
        if not bot.CONFIG["paper_trading"]:
            try:
                price = float(ex.fetch_ticker(sym)["last"]); prices[sym] = price
            except Exception as e:
                bot.log(f"شورت {sym}: {e}"); continue
            leg = bot._phase2_leg(sym, "short", bot.position_size(price), price, price * (1 + L["stop"]), None, "listing_short",
                               extra={"listed": datetime.fromtimestamp(listed / 1000, timezone.utc).isoformat(), "exit_at": (now + pd.Timedelta(days=L["hold_days"])).isoformat()})
            result = bot._phase2_live_basket(ex, state, "listing_short", f"listing-entry:{sym}", [leg])
            if result and result.get("status") == "filled": done[sym] = now.isoformat()
            continue

        try:
            price = float(ex.fetch_ticker(sym)["last"]); prices[sym] = price
            lev = int(bot.CONFIG.get("leverage", 2)); q = bot.position_size(price) * lev / price
            state["positions"][sym] = {"side": "short", "entry": price, "qty": q, "leverage": lev, "time": now.isoformat(),
                "sl": price * (1 + L["stop"]), "tp": None, "listed": datetime.fromtimestamp(listed / 1000, timezone.utc).isoformat(),
                "exit_at": (now + pd.Timedelta(days=L["hold_days"])).isoformat()}
            bot.log(f"✅ 🔴 شورت وهمي {sym} (اتدرجت من {age:.0f} يوم) @ {price:.6g} وقف {price * (1 + L['stop']):.6g}")
            bot.notify(f"🔴 شورت {sym.split(':')[0]} — عملة جديدة (اتدرجت من {age:.0f} يوم) · Paper\nدخول {price:.6g} · x{lev} · هامش ${bot.position_size(price):.0f}\nوقف {price * (1 + L['stop']):.6g} · خروج بعد {L['hold_days']} يوم")
        except Exception as e: bot.log(f"شورت {sym}: {e}")
    bot.save_state(state)
    for sym in state["positions"]:
        if sym not in prices:
            try: prices[sym] = float(ex.fetch_ticker(sym)["last"])
            except Exception: pass
    upcoming = sorted([x for x in mk if x[2] < L["skip_days"]], key=lambda x: -x[2])
    bot.write_listing_status(state, prices, upcoming)
    bot.log(f"📊 شورت مفتوح: {len(state['positions'])}/{L['max_open']} | PnL محقق {state['stats']['pnl']:+.4f} | جاي: {len(upcoming)} عملة")

def write_listing_status(state, prices, upcoming):
    out_dir = bot.CONFIG.get("public_dir")
    if not out_dir: return
    pos = []
    for sym, p in state["positions"].items():
        price = prices.get(sym, p["entry"]); pnl = (p["entry"] - price) * p["qty"]
        margin = p["entry"] * p["qty"] / max(1, int(p.get("leverage", 2)))
        pos.append({"symbol": sym.split(":")[0], "id": sym.split("/")[0] + "USDT", "side": "short", "entry": p["entry"], "price": price,
                    "qty": p["qty"], "margin": round(margin, 2), "sl": p["sl"], "pnl": round(pnl, 4),
                    "pnl_pct": round(pnl / margin * 100, 2) if margin else 0, "opened": p["time"], "exit_at": p["exit_at"]})
    st = state.get("stats", {})
    data = {"updated": datetime.now(timezone.utc).isoformat(), "mode": "paper" if bot.CONFIG["paper_trading"] else "live",
            "rules": bot.LISTING, "leverage": int(bot.CONFIG.get("leverage", 2)), "margin": bot.CONFIG.get("trade_amount_usdt"),
            "started": bot.CONFIG.get("started_at"),
            "stats": {"closed": st.get("trades", 0), "wins": st.get("wins", 0), "losses": st.get("losses", 0),
                      "realized": round(float(st.get("pnl", 0)), 4), "unrealized": round(sum(x["pnl"] for x in pos), 4), "open": len(pos)},
            "positions": sorted(pos, key=lambda x: x["opened"]),
            "upcoming": [{"symbol": s.split(":")[0], "days_left": round(bot.LISTING["skip_days"] - age, 1)} for s, _, age in upcoming[:12]],
            "history": [{"symbol": h["symbol"].split(":")[0], "entry": h["entry"], "exit": h["exit"], "pnl": bot._r4(h.get("pnl")),
                         "reason": h.get("reason", ""), "time": h.get("time"), "opened": h.get("opened")} for h in state.get("history", [])[-200:]][::-1]}
    try:
        d = Path(out_dir); tmp = d / "listing.json.tmp"
        tmp.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8"); tmp.replace(d / "listing.json")
    except Exception as e: bot.log(f"public listing status: {e}")
