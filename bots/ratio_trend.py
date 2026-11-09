"""ratio_trend — HIGH RISK experiment: every pair among the top 7 Binance USDT-M perpetuals by volume, long/short on
the pair's ratio against its 50-day average; members refreshed weekly. Live: each pair's legs go through one basket
(bot._phase2_live_basket). Moved from bot.py unchanged; shared names are read through `bot` (bots/__init__.py)."""

import bot
import json
import pandas as pd
from datetime import datetime, timezone
from pathlib import Path


RATIO = {"top": 7, "sma": 50, "min_days": 120, "every_days": 7, "exclude": []}   # exclude: --ratio-exclude (research §25)

def ratio_public_name():
    """The ratio bot's public file and paper close-request folder: "ratio", or --public-name for a second one."""
    return bot.CONFIG.get("public_name") or "ratio"

def ratio_mode():
    """HIGH RISK paper experiment: ratio trend on every pair among the top 7 Binance crypto perpetuals by 30-day volume
    (membership refreshed weekly): ratio above its 50-day average -> long the first coin / short the second, below ->
    the reverse; a pair closes when a coin leaves the list. research/ratio_fairness.py (fair version: Sharpe 0.77 after
    2024, max drawdown 795 on $20 x2 legs — it lowered the three bots' combined result, run only to watch it)."""
    return "ratio_trend" in (bot.CONFIG.get("enabled_strategies") or [])

def _daily_closed(ex, sym, cache):
    if sym not in cache: cache[sym] = ex.fetch_ohlcv(sym, "1d", limit=200)[:-1]   # closed candles only
    return cache[sym]

_ratio_rank = {}

def ratio_members(ex, cache):
    skip = {c.upper() for c in bot.RATIO.get("exclude") or []}
    syms = [x for x, _, _ in bot.listing_markets(ex) if x.split("/")[0].upper() not in skip]   # the next ones in line come in
    tick = ex.fetch_tickers()
    cands = sorted(syms, key=lambda x: -float((tick.get(x) or {}).get("quoteVolume") or 0))[:bot.RATIO["top"] * 3]
    rows = []
    for sym in cands:
        try:
            k = bot._daily_closed(ex, sym, cache)
            if len(k) >= bot.RATIO["min_days"]: rows.append((sum(r[4] * r[5] for r in k[-30:]) / 30, sym))
        except Exception as e: bot.log(f"ratio {sym}: {e}")
    top = [sym for _, sym in sorted(rows, reverse=True)[:bot.RATIO["top"]]]
    bot._ratio_rank.clear(); bot._ratio_rank.update({sym: i + 1 for i, sym in enumerate(top)})      # 1 = most volume
    return sorted(top)

def ratio_signal(ex, a, b, cache):
    ka, kb = {r[0]: r[4] for r in bot._daily_closed(ex, a, cache)}, {r[0]: r[4] for r in bot._daily_closed(ex, b, cache)}
    ts = sorted(set(ka) & set(kb))
    if len(ts) < bot.RATIO["sma"] + 1: return 0
    r = [ka[t] / kb[t] for t in ts]
    return 1 if r[-1] > sum(r[-bot.RATIO["sma"]:]) / bot.RATIO["sma"] else -1

def _ratio_close_pair(ex, state, key, prices, reason, fcache):
    pr = state["pairs"].pop(key); pnl = 0.0; fee = 0.0004
    for leg in pr["legs"]:
        sym, sg, e, q = leg["sym"], (1 if leg["side"] == "long" else -1), leg["entry"], leg["qty"]
        x = prices.get(sym) or float(ex.fetch_ticker(sym)["last"]); prices[sym] = x
        since = int(datetime.fromisoformat(pr["time"]).timestamp() * 1000)
        if (sym, since) not in fcache:
            try: fcache[(sym, since)] = sum(float(r["fundingRate"]) for r in ex.fetch_funding_rate_history(sym, since=since, limit=1000))
            except Exception as err: bot.log(f"funding {sym}: {err}"); fcache[(sym, since)] = 0.0
        pnl += sg * (x - e) * q - (e * q + x * q) * fee - sg * fcache[(sym, since)] * q * e
    st = state["stats"]; st["trades"] += 1; st["pnl"] += pnl; st["wins" if pnl > 0 else "losses"] += 1
    state["history"].append({"symbol": key, "long": pr["legs"][0]["sym"], "short": pr["legs"][1]["sym"], "pnl": pnl, "reason": reason, "ranks": pr.get("ranks"),
                             "opened": pr["time"], "time": datetime.now(timezone.utc).isoformat(), "type": "paper"})
    return pnl

def run_once_ratio(ex):
    R = bot.RATIO; state = bot.load_state(); state.setdefault("pairs", {}); now = datetime.now(timezone.utc)
    if not bot.CONFIG["paper_trading"]:
        # a block (recovery, kill switch, unknown position) stops entries only — the live adapters refuse them. The
        # strategy's own exits still run: returning here left open positions without their signal exits
        bot.reconcile_live(state, ex)
        if bot._ENTRY_BLOCK.get("reason"): bot.log(f"⛔ دخول جديد متوقف، الخروج شغّال — {bot._ENTRY_BLOCK['reason']}")
        bot.process_manual_closes(state, ex, {})   # the site's close button (it waited unanswered for the basket bots)
    bot.process_paper_closes(state, ex, ratio_public_name())
    # every cycle: a leg the exchange closed (its stop, or by hand) leaves the other one unhedged until handled
    if not bot.CONFIG["paper_trading"]:
        # reconcile_live books a leg the exchange closed but leaves the pair: the other leg is then an unhedged
        # position the strategy no longer manages, and the pair's next exit failed for good on the missing leg
        for key, pair in list(state["pairs"].items()):
            held = [leg for leg in pair["legs"] if leg["sym"] in state["positions"]]
            if len(held) == len(pair["legs"]): continue
            if held:
                out = [{"symbol": leg["sym"], "side": "close_" + leg["side"], "action": "exit", "position": state["positions"][leg["sym"]],
                        "price": float(ex.fetch_ticker(leg["sym"])["last"]), "order": i, "risk_usdt": 0, "notional_usdt": 0,
                        "correlation_group": bot._correlation_group(leg["sym"])} for i, leg in enumerate(held)]
                result = bot._phase2_live_basket(ex, state, "ratio_trend", f"ratio-orphan-exit:{key}", out, reserve=False)
                if not result or result.get("status") != "filled": continue
                bot.notify(f"⚠️ ratio {key}: رجل اتقفلت على المنصة — الرجل التانية اتقفلت كمان")
            state["pairs"].pop(key, None)
        bot.save_state(state)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0); prices = {}
    if state.get("ratio_day") != today.isoformat():          # once a day, right after the daily close
        cache, fcache = {}, {}
        last = state.get("ratio_members_at")
        if last is None or today - datetime.fromisoformat(last) >= pd.Timedelta(days=R["every_days"]):
            members = bot.ratio_members(ex, cache)
            if len(members) == R["top"]:
                state["ratio_members"], state["ratio_members_at"] = members, today.isoformat()
                state["ratio_rank"] = dict(bot._ratio_rank)
                bot.log(f"🔝 ratio: أعلى {R['top']}: {', '.join(m.split('/')[0] for m in members)}")
        members = state.get("ratio_members") or []
        wanted = {f"{a}|{b}" for i, a in enumerate(members) for b in members[i + 1:]}
        closed = 0.0; flips = 0
        for key in list(state["pairs"]):
            if bot.CONFIG["paper_trading"] and key not in wanted: closed += bot._ratio_close_pair(ex, state, key, prices, "عملة خرجت من القائمة", fcache)
        if not bot.CONFIG["paper_trading"]:
            # Live pairs are always opened and closed through one durable basket intent.
            exits = []
            for key, pair in list(state["pairs"].items()):
                if key not in wanted:
                    for leg in pair["legs"]:
                        if leg["sym"] not in state["positions"]: continue   # already closed and booked
                        exits.append({"symbol": leg["sym"], "side": "close_" + leg["side"], "action": "exit", "position": state["positions"][leg["sym"]],
                                      "price": float(ex.fetch_ticker(leg["sym"])["last"]), "order": len(exits), "risk_usdt": 0, "notional_usdt": 0,
                                      "correlation_group": bot._correlation_group(leg["sym"])})
            if exits:
                result = bot._phase2_live_basket(ex, state, "ratio_trend", "ratio-rebalance-exit", exits, reserve=False)
                if result and result.get("status") == "held":
                    # a leg under review stays open: its pair stays on the books, the others are done and the flips
                    # below still run (returning here froze every pair's exits until a person cleared the mark)
                    for key in list(state["pairs"]):
                        if key not in wanted and not any(l["sym"] in state["positions"] for l in state["pairs"][key]["legs"]):
                            state["pairs"].pop(key, None)
                elif not result or result.get("status") != "filled":
                    bot.save_state(state); return
                else:
                    for key in list(state["pairs"]):
                        if key not in wanted: state["pairs"].pop(key, None)
            for key in sorted(wanted):
                a, b = key.split("|")
                try: sig = bot.ratio_signal(ex, a, b, cache)
                except Exception as e: bot.log(f"ratio {key}: {e}"); continue
                cur = state["pairs"].get(key)
                if not sig or (cur and cur["sign"] == sig): continue
                if cur:
                    legs_out = []
                    for leg in cur["legs"]:
                        if leg["sym"] not in state["positions"]: continue   # already closed and booked
                        legs_out.append({"symbol": leg["sym"], "side": "close_" + leg["side"], "action": "exit", "position": state["positions"][leg["sym"]],
                                         "price": float(ex.fetch_ticker(leg["sym"])["last"]), "order": len(legs_out), "risk_usdt": 0, "notional_usdt": 0,
                                         "correlation_group": bot._correlation_group(leg["sym"])})
                    result = bot._phase2_live_basket(ex, state, "ratio_trend", f"ratio-flip-exit:{key}", legs_out, reserve=False)
                    if result and result.get("status") == "held": continue   # this pair waits for its review; the others go on
                    if not result or result.get("status") != "filled": bot.save_state(state); return
                    state["pairs"].pop(key, None)
                ordered = ((a, "long"), (b, "short")) if sig == 1 else ((b, "long"), (a, "short"))
                new_legs = []
                for i, (sym, side) in enumerate(ordered):
                    px = float(ex.fetch_ticker(sym)["last"]); prices[sym] = px
                    new_legs.append(bot._phase2_leg(sym, side, bot.position_size(px), px, px * (1 - 0.40) if side == "long" else px * (1 + 0.40), None, "ratio_trend", i))
                result = bot._phase2_live_basket(ex, state, "ratio_trend", f"ratio-entry:{key}", new_legs)
                if not result or result.get("status") != "filled": continue
                state["pairs"][key] = {"sign": sig, "time": now.isoformat(), "legs": [{"sym": l["symbol"], "side": l["side"], "entry": state["positions"][l["symbol"]]["entry"], "qty": state["positions"][l["symbol"]]["qty"]} for l in new_legs], "ranks": [(state.get("ratio_rank") or {}).get(a), (state.get("ratio_rank") or {}).get(b)]}
            state["ratio_day"] = today.isoformat(); bot.save_state(state); return
        if bot.CONFIG["paper_trading"]:
            lev = int(bot.CONFIG.get("leverage", 2))
            for key in sorted(wanted):
                a, b = key.split("|")
                try: sig = bot.ratio_signal(ex, a, b, cache)
                except Exception as e: bot.log(f"ratio {key}: {e}"); continue
                if not sig: continue
                cur = state["pairs"].get(key)
                if cur and cur["sign"] == sig: continue
                if cur: closed += bot._ratio_close_pair(ex, state, key, prices, "الترند اتقلب", fcache); flips += 1
                legs = []
                for sym, side in ((a, "long"), (b, "short")) if sig == 1 else ((b, "long"), (a, "short")):
                    x = prices.get(sym) or float(ex.fetch_ticker(sym)["last"]); prices[sym] = x
                    legs.append({"sym": sym, "side": side, "entry": x, "qty": bot.position_size(x) * lev / x})
                rk = state.get("ratio_rank") or {}
                state["pairs"][key] = {"sign": sig, "time": now.isoformat(), "legs": legs, "ranks": [rk.get(a), rk.get(b)]}
        state["ratio_day"] = today.isoformat(); bot.save_state(state)
        bot.log(f"🔄 ratio: {len(state['pairs'])} زوج مفتوح | قفل اليوم {closed:+.4f} | قلب {flips}")
        if closed or flips:
            bot.notify(f"⚠️ HIGH RISK — ratio trend (Paper)\nأزواج مفتوحة {len(state['pairs'])} · اتقلب {flips}\nمقفول النهارده {closed:+.2f}$ · إجمالي محقق {state['stats']['pnl']:+.2f}$")
    for pr in state["pairs"].values():
        for leg in pr["legs"]:
            if leg["sym"] not in prices:
                try: prices[leg["sym"]] = float(ex.fetch_ticker(leg["sym"])["last"])
                except Exception: pass
    bot.write_ratio_status(state, prices)

def write_ratio_status(state, prices):
    out_dir = bot.CONFIG.get("public_dir")
    if not out_dir: return
    pairs = []
    for key, pr in state.get("pairs", {}).items():
        legs, pnl = [], 0.0
        for leg in pr["legs"]:
            x = prices.get(leg["sym"], leg["entry"]); sg = 1 if leg["side"] == "long" else -1
            lp = sg * (x - leg["entry"]) * leg["qty"]; pnl += lp
            legs.append({"symbol": leg["sym"].split(":")[0], "id": leg["sym"].split("/")[0] + "USDT", "side": leg["side"],
                         "entry": leg["entry"], "price": x, "qty": leg["qty"], "pnl": round(lp, 4)})
        margin = sum(l["entry"] * l["qty"] for l in legs) / max(1, int(bot.CONFIG.get("leverage", 2)))
        pairs.append({"pair": key, "long": legs[0], "short": legs[1], "pnl": round(pnl, 4), "margin": round(margin, 2), "opened": pr["time"],
                      "ranks": pr.get("ranks")})
    st = state.get("stats", {}); at = state.get("ratio_members_at")
    data = {"updated": datetime.now(timezone.utc).isoformat(), "risk": "high", "mode": "paper" if bot.CONFIG["paper_trading"] else "live",
            "rules": bot.RATIO, "leverage": int(bot.CONFIG.get("leverage", 2)), "margin": bot.CONFIG.get("trade_amount_usdt"), "started": bot.CONFIG.get("started_at"),
            "members": [m.split("/")[0] for m in sorted(state.get("ratio_members", []), key=lambda m: (state.get("ratio_rank") or {}).get(m, 99))],
            "next_members": (datetime.fromisoformat(at) + pd.Timedelta(days=bot.RATIO["every_days"])).isoformat() if at else None,
            "stats": {"closed": st.get("trades", 0), "wins": st.get("wins", 0), "losses": st.get("losses", 0),
                      "realized": round(float(st.get("pnl", 0)), 4), "unrealized": round(sum(p["pnl"] for p in pairs), 4), "open": len(pairs)},
            "pairs": sorted(pairs, key=lambda p: p["pair"]),
            "history": [{"pair": f"{h['long'].split('/')[0]} / {h['short'].split('/')[0]}" if "long" in h else h["symbol"].split(":")[0],
                         "pnl": bot._r4(h.get("pnl")), "reason": h.get("reason", ""),
                         "time": h.get("time"), "opened": h.get("opened"), "ranks": h.get("ranks")} for h in state.get("history", [])[-300:]][::-1]}
    try:
        name = ratio_public_name(); d = Path(out_dir); tmp = d / f"{name}.json.tmp"
        tmp.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8"); tmp.replace(d / f"{name}.json")
    except Exception as e: bot.log(f"public ratio status: {e}")
