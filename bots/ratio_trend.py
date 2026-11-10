"""ratio_trend — HIGH RISK experiment: every pair among the top 7 Binance USDT-M perpetuals by volume, long/short on
the pair's ratio against its 50-day average; members refreshed weekly. Live: each pair's legs go through one basket
(bot._phase2_live_basket). Moved from bot.py unchanged; shared names are read through `bot` (bots/__init__.py)."""

import bot
import json
import pandas as pd
from datetime import datetime, timezone
from pathlib import Path


RATIO = {"top": 7, "sma": 50, "min_days": 120, "every_days": 7, "exclude": [], "net": False, "stop": 0.40, "trail": 0.0}
# trail: --ratio-trail, paper pairs only — out when the ratio is that far below its best since entry (research §35)
# exclude: --ratio-exclude (research §25). net: --ratio-net — one position per coin, the sum of its pairs (run_once_ratio_net)

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
    state["history"].append({"symbol": key, "long": pr["legs"][0]["sym"], "short": pr["legs"][1]["sym"], "pnl": pnl, "reason": reason, "ranks": pr.get("ranks"), "peak": pr.get("peak"),
                             "opened": pr["time"], "time": datetime.now(timezone.utc).isoformat(), "type": "paper"})
    return pnl

def run_once_ratio(ex):
    if bot.RATIO.get("net"):
        return run_once_ratio_net(ex)
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
            blocked = state.setdefault("ratio_blocked", {})
            for key in list(blocked):
                if key not in wanted: blocked.pop(key)                 # left the members: a fresh start when it's back
            if R.get("trail"): closed += _ratio_trail_exits(ex, state, prices, fcache)
            for key in sorted(wanted):
                a, b = key.split("|")
                try: sig = bot.ratio_signal(ex, a, b, cache)
                except Exception as e: bot.log(f"ratio {key}: {e}"); continue
                if not sig: continue
                if key in blocked:
                    if blocked[key] == sig: continue                   # trailed out: flat until the trend turns
                    blocked.pop(key)
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
    if bot.CONFIG["paper_trading"]: _ratio_track_peaks(state, prices)
    bot.write_ratio_status(state, prices)


def _ratio_trail_exits(ex, state, prices, fcache):
    """--ratio-trail (owner, 2026-11-10; research §35, B2): once a day, right after the daily close, a pair whose price
    ratio — in its trade's direction, from the legs' entries — is `trail` below its best daily value since entry is
    closed; it stays flat until its 50-day sign changes (state["ratio_blocked"]). Paper only."""
    trail, closed = float(bot.RATIO["trail"]), 0.0
    for key, pr in list(state["pairs"].items()):
        a, b = key.split("|")
        try:
            for s in (a, b):
                if s not in prices: prices[s] = float(ex.fetch_ticker(s)["last"])
        except Exception as e:
            bot.log(f"ratio trail {key}: {e}"); continue
        ent = {l["sym"]: l["entry"] for l in pr["legs"]}
        x = ((prices[a] / prices[b]) / (ent[a] / ent[b])) ** pr["sign"]   # 1 = entry, >1 = the trade's way
        pr["best"] = max(float(pr.get("best", 1.0)), x)
        if x <= pr["best"] * (1 - trail):
            sign = pr["sign"]
            closed += bot._ratio_close_pair(ex, state, key, prices, f"trailing {trail:.0%}", fcache)
            state["ratio_blocked"][key] = sign
    return closed


def _ratio_track_peaks(state, prices):
    """Each paper pair's best running PnL (price only, no fees or funding), kept in its history row at close: shows how
    much a pair made before the trend turned (owner, 2026-11-10; research/ratio_exit_study.py)."""
    changed = False
    for pr in state["pairs"].values():
        try:
            now = sum((1 if l["side"] == "long" else -1) * (prices[l["sym"]] - l["entry"]) * l["qty"] for l in pr["legs"])
        except KeyError:
            continue                                         # a price not read this cycle: next one
        if now > pr.get("peak", float("-inf")):
            pr["peak"] = round(now, 4); changed = True
    if changed: bot.save_state(state)


# ── the netted ratio trend (--ratio-net; owner 2026-11-09, docs/ratio-trend-live-plan.md §1) ──
# Every pair among the members still gives its sign, but the bot holds their sum: one position per coin of
# |units| x the unit margin, long when the sum is positive, short when negative (7 coins: +6 ... -6). A one-way
# account holds one position per coin, so this is the only way to trade all 21 pairs live; the paired path held
# whichever coin-disjoint pairs came first. Its PnL is the pairs' (research/ratio_netting_study.py, §25 is this).
# A coin whose units change is closed and reopened at the new size with a fresh 40% stop
# (research/ratio_net_live_study.py prices that against trading the change only: about 8% of the profit). A coin
# whose stop fired stays flat until its units change, as the study.
def ratio_targets(ex, members, cache):
    """{coin: net units} over every pair among `members`; a pair without enough history adds nothing."""
    t = {}
    for i, a in enumerate(members):
        for b in members[i + 1:]:
            sig = bot.ratio_signal(ex, a, b, cache)
            if not sig: continue
            t[a] = t.get(a, 0) + sig; t[b] = t.get(b, 0) - sig
    return {c: u for c, u in t.items() if u}


def ratio_net_plan(target, prev, positions):
    """(close, open): the coins to close and the coins to open at `target`, given the last target the bot traded
    (`prev`: {coin: {"units", "opened"}}) and what it holds. A coin whose units changed is closed (if held) and
    reopened; one whose units didn't change and that it opened is left alone even if flat (its stop fired); one it
    never managed to open is tried again."""
    pu = {c: v.get("units", 0) for c, v in prev.items()}
    changed = {c for c in set(target) | set(pu) if target.get(c, 0) != pu.get(c, 0)}
    retry = {c for c in target if c not in changed and not prev.get(c, {}).get("opened") and c not in positions}
    return sorted(c for c in changed if c in positions), sorted(c for c in changed | retry if target.get(c, 0))


def run_once_ratio_net(ex):
    R = bot.RATIO; state = bot.load_state(); state.setdefault("ratio_net", {}); now = datetime.now(timezone.utc); prices = {}
    live = not bot.CONFIG["paper_trading"]
    if state.get("pairs"):
        # the paired path's book: switching a running bot between the two would orphan its legs
        bot.log("⛔ ratio --ratio-net: الحالة فيها أزواج من النسخة القديمة — قفلهم الأول أو استخدم ملف حالة جديد"); return
    if live:
        bot.reconcile_live(state, ex)
        if bot._ENTRY_BLOCK.get("reason"): bot.log(f"⛔ دخول جديد متوقف، الخروج شغّال — {bot._ENTRY_BLOCK['reason']}")
        bot.process_manual_closes(state, ex, {})
    bot.process_paper_closes(state, ex, ratio_public_name())
    for sym, pos in (list(state["positions"].items()) if not live else []):   # paper stops; live, Binance holds them
        try:
            price = float(ex.fetch_ticker(sym)["last"]); prices[sym] = price
            if price >= pos["sl"] if pos["side"] == "short" else price <= pos["sl"]:
                pnl = bot._paper_close(ex, state, sym, price, f"وقف {pos['sl']:.6g}"); bot.save_state(state)
                bot.log(f"🔒 وقف {pos['side']} {sym} @ {price:.6g} PnL {pnl:+.4f}")
        except Exception as e: bot.log(f"ratio {sym}: {e}")
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if state.get("ratio_day") != today.isoformat():          # once a day, right after the daily close
        cache = {}
        last = state.get("ratio_members_at")
        if last is None or today - datetime.fromisoformat(last) >= pd.Timedelta(days=R["every_days"]):
            members = bot.ratio_members(ex, cache)
            if len(members) == R["top"]:
                state["ratio_members"], state["ratio_members_at"] = members, today.isoformat()
                state["ratio_rank"] = dict(bot._ratio_rank)
                bot.log(f"🔝 ratio: أعلى {R['top']}: {', '.join(m.split('/')[0] for m in members)}")
        members = state.get("ratio_members") or []
        if len(members) != R["top"]:
            bot.log(f"ratio: {len(members)} عملة بس — مفيش تغيير النهارده"); state["ratio_day"] = today.isoformat(); bot.save_state(state)
        else:
            try: target = bot.ratio_targets(ex, members, cache)
            except Exception as e:                            # a signal not read: no trade on half the pairs; next cycle
                bot.log(f"ratio: {e}"); bot.write_ratio_net_status(state, prices); return
            prev = state["ratio_net"]
            close, open_ = bot.ratio_net_plan(target, prev, state["positions"])
            lev = int(bot.CONFIG.get("leverage", 2)); closed = 0.0
            if live:
                exits = [{"symbol": c, "side": "close_" + state["positions"][c]["side"], "action": "exit", "position": state["positions"][c],
                          "price": float(ex.fetch_ticker(c)["last"]), "order": i, "risk_usdt": 0, "notional_usdt": 0,
                          "correlation_group": bot._correlation_group(c)} for i, c in enumerate(close)]
                if exits:
                    result = bot._phase2_live_basket(ex, state, "ratio_trend", "ratio-net-exit", exits, reserve=False)
                    if not result or result.get("status") != "filled": bot.save_state(state); return
                entries = []
                for i, c in enumerate(open_):
                    u = target[c]; px = float(ex.fetch_ticker(c)["last"]); prices[c] = px; side = "long" if u > 0 else "short"
                    stop = px * (1 - R["stop"]) if u > 0 else px * (1 + R["stop"])
                    entries.append(bot._phase2_leg(c, side, bot.position_size(px) * abs(u), px, stop, None, "ratio_trend", i, extra={"units": u}))
                if entries:
                    result = bot._phase2_live_basket(ex, state, "ratio_trend", "ratio-net-entry", entries)
                    if not result or result.get("status") != "filled": bot.save_state(state); return   # tried again next cycle
            else:
                for c in close:
                    try: closed += bot._paper_close(ex, state, c, float(ex.fetch_ticker(c)["last"]), "الوزن اتغير")
                    except Exception as e: bot.log(f"قفل {c}: {e}")
                for c in open_:
                    try:
                        u = target[c]; px = float(ex.fetch_ticker(c)["last"]); prices[c] = px; side = "long" if u > 0 else "short"
                        state["positions"][c] = {"side": side, "entry": px, "qty": bot.position_size(px) * abs(u) * lev / px, "leverage": lev,
                                                 "time": now.isoformat(), "sl": px * (1 - R["stop"]) if u > 0 else px * (1 + R["stop"]),
                                                 "tp": None, "units": u}
                    except Exception as e: bot.log(f"فتح {c}: {e}")
            opened_now = set(open_)
            state["ratio_net"] = {c: {"units": u, "opened": c in state["positions"] or (bool(prev.get(c, {}).get("opened")) and c not in opened_now)}
                                  for c, u in target.items()}
            state["ratio_day"] = today.isoformat(); bot.save_state(state)
            if close or open_:
                fmt = ", ".join(f"{c.split('/')[0]} {target[c]:+d}" for c in open_) or "—"
                bot.log(f"🔄 ratio (صافي): قفل {len(close)} {closed:+.4f} | فتح: {fmt}")
                bot.notify(f"⚠️ HIGH RISK — ratio trend (صافي لكل عملة, {'LIVE' if live else 'Paper'})\nاتقفل {len(close)} · اتفتح: {fmt}")
    for sym in state["positions"]:
        if sym not in prices:
            try: prices[sym] = float(ex.fetch_ticker(sym)["last"])
            except Exception: pass
    bot.write_ratio_net_status(state, prices)


def write_ratio_net_status(state, prices):
    """The netted bot's page file: one row per coin with its units, like momentum's (no pairs)."""
    out_dir = bot.CONFIG.get("public_dir")
    if not out_dir: return
    pos = []
    for sym, p in state["positions"].items():
        price = prices.get(sym, p["entry"]); sg = 1 if p["side"] == "long" else -1
        pnl = sg * (price - p["entry"]) * p["qty"]; margin = p["entry"] * p["qty"] / max(1, int(p.get("leverage", 2)))
        pos.append({"symbol": sym.split(":")[0], "id": sym.split("/")[0] + "USDT", "side": p["side"], "units": p.get("units"),
                    "entry": p["entry"], "price": price, "qty": p["qty"], "margin": round(margin, 2), "sl": p["sl"],
                    "pnl": round(pnl, 4), "pnl_pct": round(pnl / margin * 100, 2) if margin else 0, "opened": p["time"]})
    st = state.get("stats", {})
    data = {"updated": datetime.now(timezone.utc).isoformat(), "risk": "high", "mode": "paper" if bot.CONFIG["paper_trading"] else "live",
            "net": True, "rules": bot.RATIO, "leverage": int(bot.CONFIG.get("leverage", 2)), "margin": bot.CONFIG.get("trade_amount_usdt"),
            "started": bot.CONFIG.get("started_at"), "members": [m.split("/")[0] for m in state.get("ratio_members", [])],
            "targets": {c.split("/")[0]: v.get("units") for c, v in (state.get("ratio_net") or {}).items()},
            "stats": {"closed": st.get("trades", 0), "wins": st.get("wins", 0), "losses": st.get("losses", 0),
                      "realized": round(float(st.get("pnl", 0)), 4), "unrealized": round(sum(x["pnl"] for x in pos), 4), "open": len(pos)},
            "positions": pos, "history": [{**h, "pnl": bot._r4(h.get("pnl"))} for h in state.get("history", [])[-300:]][::-1]}
    try:
        name = ratio_public_name(); d = Path(out_dir); tmp = d / f"{name}.json.tmp"
        tmp.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8"); tmp.replace(d / f"{name}.json")
    except Exception as e: bot.log(f"public ratio status: {e}")


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
                      "ranks": pr.get("ranks"), "peak": pr.get("peak")})
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
                         "time": h.get("time"), "opened": h.get("opened"), "ranks": h.get("ranks"), "peak": bot._r4(h.get("peak"))} for h in state.get("history", [])[-300:]][::-1]}
    try:
        name = ratio_public_name(); d = Path(out_dir); tmp = d / f"{name}.json.tmp"
        tmp.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8"); tmp.replace(d / f"{name}.json")
    except Exception as e: bot.log(f"public ratio status: {e}")
