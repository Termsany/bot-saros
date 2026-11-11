"""Telegram messages and trade cards, the paper bots' public status, paper closes.
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


_tg_queue = None

def _tg_text(tok, chat, text):
    import urllib.request
    try:
        body = json.dumps({"chat_id": chat, "text": text, "disable_web_page_preview": True}).encode()
        urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=body,
                               headers={"Content-Type": "application/json"}), timeout=15)
    except Exception as e: print(f"telegram: {e}")

def _tg_card(tok, chat, card):
    """A closed trade's card as a photo (trade_card.py); its caption alone when the image can't be made or sent."""
    import trade_card
    text = trade_card.caption(card)
    try:
        trade_card.send_photo(tok, chat, trade_card.render(card), text)
    except Exception as e:
        print(f"telegram card: {e}"); bot._tg_text(tok, chat, text)
    time.sleep(1)   # Telegram allows about one message a second per chat; a weekly rebalance closes ten at once

def _tg_worker(q):
    while True:
        item = q.get()
        if item[0] == "card": bot._tg_card(*item[1:])
        else: bot._tg_text(*item)

def notify(text):
    """Telegram message from the standalone bot (python bot.py --notify); the backend loop sends its own.
    Sent from one background thread, in order — a slow network (e.g. a host whose IPv6 doesn't work, so every
    connection waits out the IPv6 attempt first) never holds up the trading cycle."""
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
    if not (bot.CONFIG.get("notify") and tok and chat): return
    if bot.CONFIG.get("label"): text = f"[{bot.CONFIG['label']}] {text}"     # a second bot of the same strategy says which
    bot._tg_put((tok, chat, text))

def _tg_put(item):
    global _tg_queue
    if _tg_queue is None:
        import queue
        _tg_queue = queue.Queue()
        threading.Thread(target=bot._tg_worker, args=(_tg_queue,), daemon=True).start()
    _tg_queue.put(item)

def notify_trade(h):
    """One closed trade (a state["history"] row) as a Telegram card: win, loss, stop or target, every strategy."""
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
    if not (bot.CONFIG.get("notify") and tok and chat): return
    try:
        import trade_card
        env = "paper" if bot.CONFIG.get("paper_trading") else ("live" if bot.binance_env() == "live" else "demo")
        card = trade_card.build(h, strategy=bot.CONFIG.get("label") or bot._current_strategy_name(), env=env, leverage=bot.CONFIG.get("leverage", 2))
    except Exception as e:
        bot.log(f"trade card: {e}")
        bot.notify(f"🔒 قفل {h.get('symbol')} — {h.get('reason', '')}\nPnL {float(h.get('pnl') or 0):+.2f}$"); return
    bot._tg_put(("card", tok, chat, card))

def _alert_closed_trades(s):
    """Every row added to the trade history since the last save gets its card. The count is saved with the state, so
    a restart neither repeats nor skips one; the first save after an upgrade starts from the history as it is."""
    hist = s.get("history")
    if not isinstance(hist, list): return
    done = s.get("alerted_closes")
    if not isinstance(done, int) or not 0 <= done <= len(hist): done = len(hist)
    for h in hist[done:]: bot.notify_trade(h)
    s["alerted_closes"] = len(hist)

def write_public_status(state, analyses, symbols_allowed):
    """Read-only snapshot for the bot's public page (deploy/vps/page): trades and results only — no keys, no config secrets."""
    out_dir = bot.CONFIG.get("public_dir")
    if not out_dir: return
    lev = int(bot.CONFIG.get("leverage", 2)); now = datetime.now(timezone.utc)
    positions = []
    for sym, pos in state["positions"].items():
        price = (analyses.get(sym) or {}).get("price") or pos["entry"]
        cs = bot._position_contract_size(pos)
        if cs is None:
            pnl = None
            margin = None
        else:
            funding = bot._funding_pnl(pos)
            fee = bot._fee_rate(pos)
            pnl = futures_net_pnl(pos["entry"], price, pos["qty"], cs, pos.get("side", "long"), fee_rate=fee, funding_pnl=funding) if funding is not None and fee is not None else None
            margin = pos["entry"] * pos["qty"] * cs / max(1, int(pos.get("leverage", lev)))
        positions.append({"symbol": sym.split(":")[0], "side": pos.get("side", "long"), "entry": pos["entry"], "price": price,
                          "qty": pos["qty"], "contract_size": cs, "margin": round(margin, 2) if margin is not None else None, "sl": pos.get("sl"), "pnl": round(pnl, 4) if pnl is not None else None,
                          "pnl_pct": round(pnl / margin * 100, 2) if pnl is not None and margin else None, "opened": pos.get("time"), "rank": pos.get("rank"),
                          "exit_below": ((analyses.get(sym) or {}).get("trend") or {}).get("exit_below") if pos.get("trend") else None,
                          "tp": pos.get("tp")})
    history = [{"symbol": h["symbol"].split(":")[0], "side": h.get("side", "long"), "entry": h.get("entry"), "exit": h.get("exit"), "qty": h.get("qty"),
                "pnl": round(float(h.get("pnl", 0)), 4), "funding_pnl": h.get("funding_pnl"), "reason": h.get("reason", ""), "time": h.get("time"),
                "opened": h.get("opened"), "rank": h.get("rank")} for h in state.get("history", [])[-200:]]
    signals = [{"symbol": sym.split(":")[0], "price": a.get("price"), "on": bool((a.get("trend") or {}).get("on")),
                "in_list": bool(a.get("in_universe", True)), "size": round((a.get("trend") or {}).get("size", 0) * 100)}
               for sym, a in sorted(analyses.items())]
    st = state.get("stats", {})
    unreal = sum(x["pnl"] for x in positions if x["pnl"] is not None)
    data = {"updated": now.isoformat(), "mode": "paper" if bot.CONFIG["paper_trading"] else "live",
            "strategy": ",".join(bot.CONFIG.get("enabled_strategies") or []), "leverage": lev, "margin": bot.CONFIG.get("trade_amount_usdt"),
            "universe_size": bot.CONFIG.get("universe_size"), "universe": [x.split("/")[0] for x in sorted(symbols_allowed or [])],
            "poll_seconds": bot.CONFIG.get("poll_seconds"), "started": bot.CONFIG.get("started_at"),
            "stats": {"closed": st.get("trades", 0), "wins": st.get("wins", 0), "losses": st.get("losses", 0),
                      "realized": round(float(st.get("pnl", 0)), 4), "unrealized": round(unreal, 4), "open": len(positions)},
            "positions": sorted(positions, key=lambda x: x["symbol"]), "history": history[::-1], "signals": signals}
    try:
        d = Path(out_dir); d.mkdir(parents=True, exist_ok=True)
        tmp = d / "status.json.tmp"; tmp.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
        tmp.replace(d / "status.json")   # atomic: the page never reads half a file
    except Exception as e: bot.log(f"public status: {e}")

def listing_markets(ex):
    """[(symbol, listed_ms, age_days)] for Binance crypto USDT perpetuals (no TradFi, no stablecoins)."""
    ex.load_markets(); now = time.time() * 1000; out = []
    for sym, m in ex.markets.items():
        info = m.get("info") or {}
        if not (m.get("swap") and m.get("linear") and m.get("quote") == "USDT" and m.get("active")): continue
        if info.get("contractType") != "PERPETUAL" or m.get("base") in bot.STABLES: continue
        listed = int(info.get("onboardDate") or 0)
        if listed: out.append((sym, listed, (now - listed) / 86_400_000))
    return out

def _r4(x):
    return round(float(x), 4) if x is not None else None

def _paper_close(ex, state, sym, price, reason):
    """Close a paper position with fees and the real funding paid/received since entry (longs pay positive funding)."""
    pos = state["positions"].pop(sym); q = pos["qty"]; sg = 1 if pos["side"] == "long" else -1; fee = 0.0004
    funding = 0.0
    try:
        since = int(datetime.fromisoformat(pos["time"]).timestamp() * 1000)
        funding = sum(float(r["fundingRate"]) for r in ex.fetch_funding_rate_history(sym, since=since, limit=1000)) * q * pos["entry"]
    except Exception as e: bot.log(f"funding {sym}: {e}")
    pnl = sg * (price - pos["entry"]) * q - (pos["entry"] * q + price * q) * fee - sg * funding
    margin = pos["entry"] * q / max(1, int(pos.get("leverage", 2)))
    state["history"].append({"symbol": sym, "side": pos["side"], "entry": pos["entry"], "exit": price, "qty": q, "pnl": pnl,
                             "opened": pos["time"], "ret": round(float(pos.get("ret", 0)) * 100, 1),
                             "pnl_pct": pnl / margin * 100 if margin else 0, "funding": -sg * funding, "reason": reason,
                             "time": datetime.now(timezone.utc).isoformat(), "type": "paper"})
    st = state["stats"]; st["trades"] += 1; st["pnl"] += pnl; st["wins" if pnl > 0 else "losses"] += 1
    return pnl
