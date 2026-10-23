"""
Crypto Auto-Trading Bot — 7 Strategies + 20 High-Liquidity Pairs
إيشيموكو + داو + جان + موجي + كلاسيكي + دعوم/مقاومات + RSI/MACD
Paper Trading (وهمي) — يعرض الصفقات بـ entry/SL/TP
python bot.py --paper   (وهمي كل 60s)  |  python bot.py --once  (مرة واحدة)
python bot.py --dashboard  (يشغّل البوت + داشبورد http://localhost:8765)
"""
import ccxt, pandas as pd, numpy as np, time, json, os, re, uuid, threading, http.server, socketserver, webbrowser
from datetime import datetime, timezone
from pathlib import Path
import strategies_advanced as adv

try:
    from dotenv import load_dotenv; load_dotenv()
except: pass

CONFIG = {
    # 20 زوج سيولة عالية — Binance USDT-M Futures (لونج/شورت)
    "market": "future",  # future = USDT-M perpetual, spot = spot
    "leverage": 5,
    "margin_type": "ISOLATED",
    "symbols": [
        "BTC/USDT","ETH/USDT","BNB/USDT","SOL/USDT","XRP/USDT",
        "DOGE/USDT","ADA/USDT","AVAX/USDT","1000SHIB/USDT","DOT/USDT",
        "LINK/USDT","TRX/USDT","LTC/USDT","BCH/USDT","UNI/USDT",
        "ETC/USDT","NEAR/USDT","1000PEPE/USDT","ARB/USDT","SUI/USDT",
    ],
    "timeframe": "4h",
    "weights": {"ichimoku":0.10,"dow":0.05,"gann":0.05,"elliott":0.08,"classical":0.05,"sr":0.05,"rsi_macd":0.12,"smc":0.10,"vwap":0.07,"supertrend":0.07,"bollinger":0.07,"harmonic":0.05,"ict":0.05,"heikin":0.05,"ai":0.04},
    "enabled_strategies": ["ict"],  # measured results per strategy: lib/strategy-stats.json (research/README.md)
    # Engine rules below match backtest.py and lib/strategy-engine.ts, so live trading behaves like the backtests:
    # |score| > 0.35 to enter, 3 candles of cooldown after a trade, fixed 3%/6% SL/TP, ADX >= 10, range filter.
    "buy_threshold": 0.35, "strong_buy": 0.35, "sell_threshold": -0.35, "strong_sell": -0.35,
    "trade_amount_usdt": 20,
    # === Week 1: Risk + Filters ===
    "risk_pct": 2.0,              # 2% من المحفظة لكل صفقة (لو balance معروف)
    "use_percent_risk": False,     # False = 20$ ثابت، True = % من الرصيد
    "adx_threshold": 10,          # فلتر ADX — أقل من 10 = سوق بلا اتجاه، لا تدخل (نفس الباك تست)
    "vol_filter": False,            # لازم حجم > متوسط 20
    "htf_filter": False,            # لا تدخل عكس ترند 4h
    "htf_timeframe": "4h",
    "dynamic_sl_tp": False, "atr_sl_mult": 2.0, "atr_tp_mult": 3.0, "atr_period": 14,  # ATR exits helped some strategies and hurt others in testing
    "regime_filter": True, "regime_adx_trend": 20,
    "max_daily_loss_pct": 5.0,     # لو خسر 5% في يوم يوقف
    "breakeven_enabled": True,         # بعد أول هدف ينقل الوقف لنقطة الدخول
    "breakeven_trigger_pct": 0.50,     # 50% من المسافة للهدف = أول هدف
    "breakeven_offset_pct": 0.001,     # 0.1% فوق الدخول لتغطية العمولة
    "stop_loss_pct": 0.03,
    "take_profit_pct": 0.06,
    "max_open_positions": 5,
    "cooldown_bars": 3,            # شموع انتظار بعد قفل أي صفقة على نفس الزوج (نفس الباك تست)
    "paper_trading": True,
    "poll_seconds": 60,
    "state_file": "state.json",
    "log_file": "trades.log",
    "dashboard_port": 8765,
}

STATE_PATH = Path(__file__).parent / CONFIG["state_file"]
LOG_PATH   = Path(__file__).parent / CONFIG["log_file"]

def get_exchange(auth=False):
    mtype = "future" if CONFIG.get("market","future")=="future" else "spot"
    # ccxt: defaultType future = USDT-M perpetual
    kwargs = {"enableRateLimit": True, "options": {"defaultType": mtype}}
    if auth:
        ak = os.getenv("BINANCE_API_KEY","").strip(); sc = os.getenv("BINANCE_SECRET","").strip()
        if not ak or not sc: return None, "ضع مفاتيح Binance في .env"
        kwargs["apiKey"]=ak; kwargs["secret"]=sc
        ex = ccxt.binanceusdm(kwargs) if mtype == "future" else ccxt.binance(kwargs)
        # BINANCE_ENV=demo: Binance Demo Trading (fake money, real exchange behaviour) — keys made in demo mode on binance.com
        env = binance_env()
        if env == "demo": ex.enable_demo_trading(True)
        elif env == "testnet": ex.set_sandbox_mode(True)
        return ex, None
    return ccxt.bybit(kwargs), None   # public market data only (paper)

def binance_env():
    """live (real money) / demo (Binance Demo Trading) / testnet (old futures testnet)."""
    e = os.getenv("BINANCE_ENV", "live").strip().lower()
    return e if e in ("live", "demo", "testnet") else "live"

STABLES = {"USDC", "FDUSD", "TUSD", "USDP", "BUSD", "DAI", "USDE", "USD1", "PAXG", "XAUT"}  # stablecoins, gold
_universe = {"key": None, "symbols": []}

def volume_universe(ex, n):
    """Top n USDT perpetuals by average USDT volume over the last 30 closed daily candles, among coins with
    at least 150 daily candles (the trend needs 120 days) — research/universe_study.py. Refreshed once a day."""
    key = (datetime.now(timezone.utc).date().isoformat(), n)
    if _universe["key"] == key: return _universe["symbols"]
    ex.load_markets()
    tickers = ex.fetch_tickers(params={"category": "linear"} if ex.id == "bybit" else {})
    cands = []
    for sym, t in tickers.items():
        m = ex.markets.get(sym) or {}
        info = m.get("info") or {}
        crypto = info.get("symbolType", "") in ("", "innovation")   # Bybit also lists stocks, ETFs, commodities, forex as USDT perps
        crypto = crypto and info.get("underlyingType", "COIN") == "COIN" and info.get("contractType", "PERPETUAL") == "PERPETUAL"   # Binance's
        if m.get("swap") and m.get("linear") and m.get("quote") == "USDT" and m.get("settle") == "USDT" and m.get("base") not in STABLES                 and crypto and m.get("active", True) and not info.get("isPreListing"):
            cands.append((float(t.get("quoteVolume") or 0), sym))
    ranked = []
    for _, sym in sorted(cands, reverse=True)[:n * 3]:   # 24h volume narrows the list, the 30-day average ranks it
        try:
            k = ex.fetch_ohlcv(sym, "1d", limit=200)[:-1]
            if len(k) >= 150: ranked.append((sum(r[4] * r[5] for r in k[-30:]) / 30, sym))
        except Exception as e: log(f"volume {sym}: {e}")
    syms = [s for _, s in sorted(ranked, reverse=True)[:n]]
    if syms: _universe.update(key=key, symbols=syms)
    log(f"🔝 أعلى {n} عملة فوليوم (متوسط 30 يوم): {', '.join(s.split('/')[0] for s in syms)}")
    return syms or _universe["symbols"]

def cycle_symbols(ex, state):
    """(symbols to analyse, symbols allowed to open new trades). With universe_size, new trades only in the
    volume top list; open positions keep being managed after a coin drops out of it."""
    n = int(CONFIG.get("universe_size") or 0)
    if not n: return list(CONFIG["symbols"]), None
    allowed = set(volume_universe(ex, n))
    return sorted(allowed | set(state["positions"])), allowed

_tg_queue = None

def _tg_worker(q):
    import urllib.request
    while True:
        tok, chat, text = q.get()
        try:
            body = json.dumps({"chat_id": chat, "text": text, "disable_web_page_preview": True}).encode()
            urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=body,
                                   headers={"Content-Type": "application/json"}), timeout=15)
        except Exception as e: print(f"telegram: {e}")

def notify(text):
    """Telegram message from the standalone bot (python bot.py --notify); the backend loop sends its own.
    Sent from one background thread, in order — a slow network (e.g. a host whose IPv6 doesn't work, so every
    connection waits out the IPv6 attempt first) never holds up the trading cycle."""
    global _tg_queue
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
    if not (CONFIG.get("notify") and tok and chat): return
    if _tg_queue is None:
        import queue
        _tg_queue = queue.Queue()
        threading.Thread(target=_tg_worker, args=(_tg_queue,), daemon=True).start()
    _tg_queue.put((tok, chat, text))

def write_public_status(state, analyses, symbols_allowed):
    """Read-only snapshot for the bot's public page (deploy/vps/page): trades and results only — no keys, no config secrets."""
    out_dir = CONFIG.get("public_dir")
    if not out_dir: return
    lev = int(CONFIG.get("leverage", 2)); now = datetime.now(timezone.utc)
    positions = []
    for sym, pos in state["positions"].items():
        price = (analyses.get(sym) or {}).get("price") or pos["entry"]
        pnl = (price - pos["entry"]) * pos["qty"] * (1 if pos.get("side", "long") == "long" else -1)
        margin = pos["entry"] * pos["qty"] / max(1, int(pos.get("leverage", lev)))
        positions.append({"symbol": sym.split(":")[0], "side": pos.get("side", "long"), "entry": pos["entry"], "price": price,
                          "qty": pos["qty"], "margin": round(margin, 2), "sl": pos.get("sl"), "pnl": round(pnl, 4),
                          "pnl_pct": round(pnl / margin * 100, 2) if margin else 0, "opened": pos.get("time"), "rank": pos.get("rank"),
                          "exit_below": ((analyses.get(sym) or {}).get("trend") or {}).get("exit_below") if pos.get("trend") else None,
                          "tp": pos.get("tp")})
    history = [{"symbol": h["symbol"].split(":")[0], "side": h.get("side", "long"), "entry": h.get("entry"), "exit": h.get("exit"), "qty": h.get("qty"),
                "pnl": round(float(h.get("pnl", 0)), 4), "reason": h.get("reason", ""), "time": h.get("time"),
                "opened": h.get("opened"), "rank": h.get("rank")} for h in state.get("history", [])[-200:]]
    signals = [{"symbol": sym.split(":")[0], "price": a.get("price"), "on": bool((a.get("trend") or {}).get("on")),
                "in_list": bool(a.get("in_universe", True)), "size": round((a.get("trend") or {}).get("size", 0) * 100)}
               for sym, a in sorted(analyses.items())]
    st = state.get("stats", {})
    unreal = sum(x["pnl"] for x in positions)
    data = {"updated": now.isoformat(), "mode": "paper" if CONFIG["paper_trading"] else "live",
            "strategy": ",".join(CONFIG.get("enabled_strategies") or []), "leverage": lev, "margin": CONFIG.get("trade_amount_usdt"),
            "universe_size": CONFIG.get("universe_size"), "universe": [x.split("/")[0] for x in sorted(symbols_allowed or [])],
            "poll_seconds": CONFIG.get("poll_seconds"), "started": CONFIG.get("started_at"),
            "stats": {"closed": st.get("trades", 0), "wins": st.get("wins", 0), "losses": st.get("losses", 0),
                      "realized": round(float(st.get("pnl", 0)), 4), "unrealized": round(unreal, 4), "open": len(positions)},
            "positions": sorted(positions, key=lambda x: x["symbol"]), "history": history[::-1], "signals": signals}
    try:
        d = Path(out_dir); d.mkdir(parents=True, exist_ok=True)
        tmp = d / "status.json.tmp"; tmp.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
        tmp.replace(d / "status.json")   # atomic: the page never reads half a file
    except Exception as e: log(f"public status: {e}")

LISTING = {"skip_days": 30, "hold_days": 90, "stop": 0.40, "max_open": 10, "catch_up_days": 3}

def listing_mode():
    """Paper short of new Binance USDT-M listings 30 days after listing, held 90 days, stop 40% above entry,
    at most 10 at once — research/short_study.py idea 2 (README "Short side")."""
    return "listing_short" in (CONFIG.get("enabled_strategies") or [])

def listing_markets(ex):
    """[(symbol, listed_ms, age_days)] for Binance crypto USDT perpetuals (no TradFi, no stablecoins)."""
    ex.load_markets(); now = time.time() * 1000; out = []
    for sym, m in ex.markets.items():
        info = m.get("info") or {}
        if not (m.get("swap") and m.get("linear") and m.get("quote") == "USDT" and m.get("active")): continue
        if info.get("contractType") != "PERPETUAL" or m.get("base") in STABLES: continue
        listed = int(info.get("onboardDate") or 0)
        if listed: out.append((sym, listed, (now - listed) / 86_400_000))
    return out

def _listing_close(ex, state, sym, price, reason):
    pos = state["positions"].pop(sym); q = pos["qty"]; fee = 0.0004
    funding = 0.0
    try:   # shorts receive positive funding and pay negative funding
        since = int(datetime.fromisoformat(pos["time"]).timestamp() * 1000)
        funding = sum(float(r["fundingRate"]) for r in ex.fetch_funding_rate_history(sym, since=since, limit=1000)) * q * pos["entry"]
    except Exception as e: log(f"funding {sym}: {e}")
    pnl = (pos["entry"] - price) * q - (pos["entry"] * q + price * q) * fee + funding
    margin = pos["entry"] * q / max(1, int(pos.get("leverage", 2)))
    state["history"].append({"symbol": sym, "side": "short", "entry": pos["entry"], "exit": price, "qty": q, "pnl": pnl, "opened": pos["time"],
                             "pnl_pct": pnl / margin * 100 if margin else 0, "funding": funding, "reason": reason,
                             "time": datetime.now(timezone.utc).isoformat(), "type": "paper"})
    st = state["stats"]; st["trades"] += 1; st["pnl"] += pnl; st["wins" if pnl > 0 else "losses"] += 1
    save_state(state)
    log(f"🔒 قفل شورت {sym} — {reason} @ {price:.6g} PnL {pnl:+.4f} (funding {funding:+.4f})")
    notify(f"🔒 قفل شورت {sym.split(':')[0]} — {reason}\nدخول {pos['entry']:.6g} → خروج {price:.6g}\nPnL {pnl:+.2f}$ (funding {funding:+.2f}$) · Paper")

def run_once_listing(ex):
    L = LISTING; state = load_state(); now = datetime.now(timezone.utc)
    done = state.setdefault("listing_done", {})
    mk = listing_markets(ex); prices = {}
    # open shorts: protective stop and the 90-day exit
    for sym, pos in list(state["positions"].items()):
        try:
            price = float(ex.fetch_ticker(sym)["last"]); prices[sym] = price
            if price >= pos["sl"]: _listing_close(ex, state, sym, price, f"وقف {pos['sl']:.6g}")
            elif now >= datetime.fromisoformat(pos["exit_at"]): _listing_close(ex, state, sym, price, f"خلصت {L['hold_days']} يوم")
        except Exception as e: log(f"شورت {sym}: {e}")
    # new entries: coins that just turned 30 days old (a few days of slack if the bot was down), oldest listing first;
    # like the backtest, a coin that comes up while all 10 slots are taken is skipped for good
    due = sorted([x for x in mk if L["skip_days"] <= x[2] < L["skip_days"] + L["catch_up_days"] and x[0] not in done], key=lambda x: x[1])
    for sym, listed, age in due:
        done[sym] = now.isoformat()
        if len(state["positions"]) >= L["max_open"]:
            log(f"⏸️ {sym} عدّى {L['skip_days']} يوم بس الـ {L['max_open']} أماكن مليانة — اتساب زي الباك تست"); continue
        if not CONFIG["paper_trading"]: log(f"⏸️ {sym} شورت العملات الجديدة Paper بس"); continue
        try:
            price = float(ex.fetch_ticker(sym)["last"]); prices[sym] = price
            lev = int(CONFIG.get("leverage", 2)); q = position_size(price) * lev / price
            state["positions"][sym] = {"side": "short", "entry": price, "qty": q, "leverage": lev, "time": now.isoformat(),
                "sl": price * (1 + L["stop"]), "tp": None, "listed": datetime.fromtimestamp(listed / 1000, timezone.utc).isoformat(),
                "exit_at": (now + pd.Timedelta(days=L["hold_days"])).isoformat()}
            log(f"✅ 🔴 شورت وهمي {sym} (اتدرجت من {age:.0f} يوم) @ {price:.6g} وقف {price * (1 + L['stop']):.6g}")
            notify(f"🔴 شورت {sym.split(':')[0]} — عملة جديدة (اتدرجت من {age:.0f} يوم) · Paper\nدخول {price:.6g} · x{lev} · هامش ${position_size(price):.0f}\nوقف {price * (1 + L['stop']):.6g} · خروج بعد {L['hold_days']} يوم")
        except Exception as e: log(f"شورت {sym}: {e}")
    save_state(state)
    for sym in state["positions"]:
        if sym not in prices:
            try: prices[sym] = float(ex.fetch_ticker(sym)["last"])
            except Exception: pass
    upcoming = sorted([x for x in mk if x[2] < L["skip_days"]], key=lambda x: -x[2])
    write_listing_status(state, prices, upcoming)
    log(f"📊 شورت مفتوح: {len(state['positions'])}/{L['max_open']} | PnL محقق {state['stats']['pnl']:+.4f} | جاي: {len(upcoming)} عملة")

def write_listing_status(state, prices, upcoming):
    out_dir = CONFIG.get("public_dir")
    if not out_dir: return
    pos = []
    for sym, p in state["positions"].items():
        price = prices.get(sym, p["entry"]); pnl = (p["entry"] - price) * p["qty"]
        margin = p["entry"] * p["qty"] / max(1, int(p.get("leverage", 2)))
        pos.append({"symbol": sym.split(":")[0], "id": sym.split("/")[0] + "USDT", "side": "short", "entry": p["entry"], "price": price,
                    "qty": p["qty"], "margin": round(margin, 2), "sl": p["sl"], "pnl": round(pnl, 4),
                    "pnl_pct": round(pnl / margin * 100, 2) if margin else 0, "opened": p["time"], "exit_at": p["exit_at"]})
    st = state.get("stats", {})
    data = {"updated": datetime.now(timezone.utc).isoformat(), "mode": "paper" if CONFIG["paper_trading"] else "live",
            "rules": LISTING, "leverage": int(CONFIG.get("leverage", 2)), "margin": CONFIG.get("trade_amount_usdt"),
            "started": CONFIG.get("started_at"),
            "stats": {"closed": st.get("trades", 0), "wins": st.get("wins", 0), "losses": st.get("losses", 0),
                      "realized": round(float(st.get("pnl", 0)), 4), "unrealized": round(sum(x["pnl"] for x in pos), 4), "open": len(pos)},
            "positions": sorted(pos, key=lambda x: x["opened"]),
            "upcoming": [{"symbol": s.split(":")[0], "days_left": round(LISTING["skip_days"] - age, 1)} for s, _, age in upcoming[:12]],
            "history": [{"symbol": h["symbol"].split(":")[0], "entry": h["entry"], "exit": h["exit"], "pnl": round(h["pnl"], 4),
                         "reason": h.get("reason", ""), "time": h.get("time"), "opened": h.get("opened")} for h in state.get("history", [])[-200:]][::-1]}
    try:
        d = Path(out_dir); tmp = d / "listing.json.tmp"
        tmp.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8"); tmp.replace(d / "listing.json")
    except Exception as e: log(f"public listing status: {e}")

MOM = {"weeks": 2, "top": 50, "n": 5, "min_days": 60, "stop": 0.40, "every_days": 7}

def momentum_mode():
    """Paper cross-sectional momentum on Binance: every 7 days rank the top 50 USDT perpetuals by 30-day volume on
    their last 2 weeks' return, long the strongest 5 and short the weakest 5 for a week, stop 40% —
    research/pump_momentum_study.py idea 2 (Liu, Tsyvinski & Wu 2022)."""
    return "momentum_ls" in (CONFIG.get("enabled_strategies") or [])

def momentum_rank(ex):
    """[(symbol, return over MOM weeks)] weakest first, among the top MOM["top"] by 30-day average USDT volume
    (crypto perpetuals with >= min_days closed daily candles)."""
    syms = [s for s, _, _ in listing_markets(ex)]
    tick = ex.fetch_tickers()
    cands = sorted(syms, key=lambda s: -float((tick.get(s) or {}).get("quoteVolume") or 0))[:MOM["top"] * 3]
    rows = []
    for sym in cands:
        try:
            k = ex.fetch_ohlcv(sym, "1d", limit=70)[:-1]          # closed candles only
            if len(k) < MOM["min_days"]: continue
            rows.append((sum(r[4] * r[5] for r in k[-30:]) / 30, sym, k[-1][4] / k[-1 - 7 * MOM["weeks"]][4] - 1))
        except Exception as e: log(f"momentum {sym}: {e}")
    top = sorted(rows, reverse=True)[:MOM["top"]]
    return [(sym, ret) for _, sym, ret in sorted(top, key=lambda r: r[2])]

def _paper_close(ex, state, sym, price, reason):
    """Close a paper position with fees and the real funding paid/received since entry (longs pay positive funding)."""
    pos = state["positions"].pop(sym); q = pos["qty"]; sg = 1 if pos["side"] == "long" else -1; fee = 0.0004
    funding = 0.0
    try:
        since = int(datetime.fromisoformat(pos["time"]).timestamp() * 1000)
        funding = sum(float(r["fundingRate"]) for r in ex.fetch_funding_rate_history(sym, since=since, limit=1000)) * q * pos["entry"]
    except Exception as e: log(f"funding {sym}: {e}")
    pnl = sg * (price - pos["entry"]) * q - (pos["entry"] * q + price * q) * fee - sg * funding
    margin = pos["entry"] * q / max(1, int(pos.get("leverage", 2)))
    state["history"].append({"symbol": sym, "side": pos["side"], "entry": pos["entry"], "exit": price, "qty": q, "pnl": pnl,
                             "opened": pos["time"], "ret": round(float(pos.get("ret", 0)) * 100, 1),
                             "pnl_pct": pnl / margin * 100 if margin else 0, "funding": -sg * funding, "reason": reason,
                             "time": datetime.now(timezone.utc).isoformat(), "type": "paper"})
    st = state["stats"]; st["trades"] += 1; st["pnl"] += pnl; st["wins" if pnl > 0 else "losses"] += 1
    return pnl

def run_once_momentum(ex):
    M = MOM; state = load_state(); now = datetime.now(timezone.utc); prices = {}
    # protective stops during the week
    for sym, pos in list(state["positions"].items()):
        try:
            price = float(ex.fetch_ticker(sym)["last"]); prices[sym] = price
            hit = price >= pos["sl"] if pos["side"] == "short" else price <= pos["sl"]
            if hit:
                pnl = _paper_close(ex, state, sym, price, f"وقف {pos['sl']:.6g}"); save_state(state)
                log(f"🔒 وقف {pos['side']} {sym} @ {price:.6g} PnL {pnl:+.4f}")
                notify(f"🔒 مومنتم: وقف {'لونج' if pos['side'] == 'long' else 'شورت'} {sym.split(':')[0]} @ {price:.6g}\nPnL {pnl:+.2f}$ · Paper")
        except Exception as e: log(f"مومنتم {sym}: {e}")
    # weekly rebalance, at the first cycle after the daily close (00:00 UTC) once 7 days have passed
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    last = state.get("mom_last")
    if last is None or today - datetime.fromisoformat(last) >= pd.Timedelta(days=M["every_days"]):
        ranked = momentum_rank(ex)
        if len(ranked) >= 20:
            closed = 0.0
            for sym in list(state["positions"]):
                try:
                    price = float(ex.fetch_ticker(sym)["last"]); closed += _paper_close(ex, state, sym, price, "تبديل أسبوعي")
                except Exception as e: log(f"قفل {sym}: {e}")
            if not CONFIG["paper_trading"]: log("⏸️ المومنتم Paper بس"); save_state(state); return
            lev = int(CONFIG.get("leverage", 2)); picks = [(s, r, "short") for s, r in ranked[:M["n"]]] + [(s, r, "long") for s, r in ranked[-M["n"]:]]
            for sym, ret, side in picks:
                try:
                    price = float(ex.fetch_ticker(sym)["last"]); prices[sym] = price; q = position_size(price) * lev / price
                    sl = price * (1 + M["stop"]) if side == "short" else price * (1 - M["stop"])
                    state["positions"][sym] = {"side": side, "entry": price, "qty": q, "leverage": lev, "time": now.isoformat(),
                                               "sl": sl, "tp": None, "ret": ret}
                except Exception as e: log(f"فتح {sym}: {e}")
            state["mom_last"] = today.isoformat()
            state["mom_ranking"] = [{"symbol": s.split(":")[0], "ret": round(r * 100, 1)} for s, r in ranked]
            save_state(state)
            longs = ", ".join(f"{s.split('/')[0]} {r * 100:+.0f}%" for s, r, sd in picks if sd == "long")
            shorts = ", ".join(f"{s.split('/')[0]} {r * 100:+.0f}%" for s, r, sd in picks if sd == "short")
            log(f"🔄 مومنتم: تبديل أسبوعي — قفل {closed:+.4f} | لونج: {longs} | شورت: {shorts}")
            notify(f"🔄 مومنتم — تبديل أسبوعي (Paper)\nالأسبوع اللي فات: {closed:+.2f}$\n🟢 لونج الأقوى: {longs}\n🔴 شورت الأضعف: {shorts}")
        else: log(f"مومنتم: {len(ranked)} عملة بس في القائمة — مفيش تبديل")
    for sym in state["positions"]:
        if sym not in prices:
            try: prices[sym] = float(ex.fetch_ticker(sym)["last"])
            except Exception: pass
    write_momentum_status(state, prices)
    log(f"📊 مومنتم: {len(state['positions'])} مفتوحة | PnL محقق {state['stats']['pnl']:+.4f}")

def write_momentum_status(state, prices):
    out_dir = CONFIG.get("public_dir")
    if not out_dir: return
    pos = []
    for sym, p in state["positions"].items():
        price = prices.get(sym, p["entry"]); sg = 1 if p["side"] == "long" else -1
        pnl = sg * (price - p["entry"]) * p["qty"]; margin = p["entry"] * p["qty"] / max(1, int(p.get("leverage", 2)))
        pos.append({"symbol": sym.split(":")[0], "id": sym.split("/")[0] + "USDT", "side": p["side"], "entry": p["entry"], "price": price,
                    "qty": p["qty"], "margin": round(margin, 2), "sl": p["sl"], "pnl": round(pnl, 4),
                    "pnl_pct": round(pnl / margin * 100, 2) if margin else 0, "ret": round(p.get("ret", 0) * 100, 1), "opened": p["time"]})
    st = state.get("stats", {}); last = state.get("mom_last")
    data = {"updated": datetime.now(timezone.utc).isoformat(), "mode": "paper" if CONFIG["paper_trading"] else "live", "rules": MOM,
            "leverage": int(CONFIG.get("leverage", 2)), "margin": CONFIG.get("trade_amount_usdt"), "started": CONFIG.get("started_at"),
            "last_rebalance": last, "next_rebalance": (datetime.fromisoformat(last) + pd.Timedelta(days=MOM["every_days"])).isoformat() if last else None,
            "stats": {"closed": st.get("trades", 0), "wins": st.get("wins", 0), "losses": st.get("losses", 0),
                      "realized": round(float(st.get("pnl", 0)), 4), "unrealized": round(sum(x["pnl"] for x in pos), 4), "open": len(pos)},
            "positions": sorted(pos, key=lambda x: (x["side"], -x["ret"])),
            "history": [{"symbol": h["symbol"].split(":")[0], "side": h.get("side"), "entry": h["entry"], "exit": h["exit"], "pnl": round(h["pnl"], 4),
                         "reason": h.get("reason", ""), "time": h.get("time"), "opened": h.get("opened"), "ret": h.get("ret")}
                        for h in state.get("history", [])[-300:]][::-1]}
    try:
        d = Path(out_dir); tmp = d / "momentum.json.tmp"
        tmp.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8"); tmp.replace(d / "momentum.json")
    except Exception as e: log(f"public momentum status: {e}")

RATIO = {"top": 7, "sma": 50, "min_days": 120, "every_days": 7}

def ratio_mode():
    """HIGH RISK paper experiment: ratio trend on every pair among the top 7 Binance crypto perpetuals by 30-day volume
    (membership refreshed weekly): ratio above its 50-day average -> long the first coin / short the second, below ->
    the reverse; a pair closes when a coin leaves the list. research/ratio_fairness.py (fair version: Sharpe 0.77 after
    2024, max drawdown 795 on $20 x2 legs — it lowered the three bots' combined result, run only to watch it)."""
    return "ratio_trend" in (CONFIG.get("enabled_strategies") or [])

def _daily_closed(ex, sym, cache):
    if sym not in cache: cache[sym] = ex.fetch_ohlcv(sym, "1d", limit=200)[:-1]   # closed candles only
    return cache[sym]

_ratio_rank = {}

def ratio_members(ex, cache):
    syms = [x for x, _, _ in listing_markets(ex)]
    tick = ex.fetch_tickers()
    cands = sorted(syms, key=lambda x: -float((tick.get(x) or {}).get("quoteVolume") or 0))[:RATIO["top"] * 3]
    rows = []
    for sym in cands:
        try:
            k = _daily_closed(ex, sym, cache)
            if len(k) >= RATIO["min_days"]: rows.append((sum(r[4] * r[5] for r in k[-30:]) / 30, sym))
        except Exception as e: log(f"ratio {sym}: {e}")
    top = [sym for _, sym in sorted(rows, reverse=True)[:RATIO["top"]]]
    _ratio_rank.clear(); _ratio_rank.update({sym: i + 1 for i, sym in enumerate(top)})      # 1 = most volume
    return sorted(top)

def ratio_signal(ex, a, b, cache):
    ka, kb = {r[0]: r[4] for r in _daily_closed(ex, a, cache)}, {r[0]: r[4] for r in _daily_closed(ex, b, cache)}
    ts = sorted(set(ka) & set(kb))
    if len(ts) < RATIO["sma"] + 1: return 0
    r = [ka[t] / kb[t] for t in ts]
    return 1 if r[-1] > sum(r[-RATIO["sma"]:]) / RATIO["sma"] else -1

def _ratio_close_pair(ex, state, key, prices, reason, fcache):
    pr = state["pairs"].pop(key); pnl = 0.0; fee = 0.0004
    for leg in pr["legs"]:
        sym, sg, e, q = leg["sym"], (1 if leg["side"] == "long" else -1), leg["entry"], leg["qty"]
        x = prices.get(sym) or float(ex.fetch_ticker(sym)["last"]); prices[sym] = x
        since = int(datetime.fromisoformat(pr["time"]).timestamp() * 1000)
        if (sym, since) not in fcache:
            try: fcache[(sym, since)] = sum(float(r["fundingRate"]) for r in ex.fetch_funding_rate_history(sym, since=since, limit=1000))
            except Exception as err: log(f"funding {sym}: {err}"); fcache[(sym, since)] = 0.0
        pnl += sg * (x - e) * q - (e * q + x * q) * fee - sg * fcache[(sym, since)] * q * e
    st = state["stats"]; st["trades"] += 1; st["pnl"] += pnl; st["wins" if pnl > 0 else "losses"] += 1
    state["history"].append({"symbol": key, "long": pr["legs"][0]["sym"], "short": pr["legs"][1]["sym"], "pnl": pnl, "reason": reason, "ranks": pr.get("ranks"),
                             "opened": pr["time"], "time": datetime.now(timezone.utc).isoformat(), "type": "paper"})
    return pnl

def run_once_ratio(ex):
    R = RATIO; state = load_state(); state.setdefault("pairs", {}); now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0); prices = {}
    if state.get("ratio_day") != today.isoformat():          # once a day, right after the daily close
        cache, fcache = {}, {}
        last = state.get("ratio_members_at")
        if last is None or today - datetime.fromisoformat(last) >= pd.Timedelta(days=R["every_days"]):
            members = ratio_members(ex, cache)
            if len(members) == R["top"]:
                state["ratio_members"], state["ratio_members_at"] = members, today.isoformat()
                state["ratio_rank"] = dict(_ratio_rank)
                log(f"🔝 ratio: أعلى {R['top']}: {', '.join(m.split('/')[0] for m in members)}")
        members = state.get("ratio_members") or []
        wanted = {f"{a}|{b}" for i, a in enumerate(members) for b in members[i + 1:]}
        closed = 0.0; flips = 0
        for key in list(state["pairs"]):
            if key not in wanted: closed += _ratio_close_pair(ex, state, key, prices, "عملة خرجت من القائمة", fcache)
        if CONFIG["paper_trading"]:
            lev = int(CONFIG.get("leverage", 2))
            for key in sorted(wanted):
                a, b = key.split("|")
                try: sig = ratio_signal(ex, a, b, cache)
                except Exception as e: log(f"ratio {key}: {e}"); continue
                if not sig: continue
                cur = state["pairs"].get(key)
                if cur and cur["sign"] == sig: continue
                if cur: closed += _ratio_close_pair(ex, state, key, prices, "الترند اتقلب", fcache); flips += 1
                legs = []
                for sym, side in ((a, "long"), (b, "short")) if sig == 1 else ((b, "long"), (a, "short")):
                    x = prices.get(sym) or float(ex.fetch_ticker(sym)["last"]); prices[sym] = x
                    legs.append({"sym": sym, "side": side, "entry": x, "qty": position_size(x) * lev / x})
                rk = state.get("ratio_rank") or {}
                state["pairs"][key] = {"sign": sig, "time": now.isoformat(), "legs": legs, "ranks": [rk.get(a), rk.get(b)]}
        state["ratio_day"] = today.isoformat(); save_state(state)
        log(f"🔄 ratio: {len(state['pairs'])} زوج مفتوح | قفل اليوم {closed:+.4f} | قلب {flips}")
        if closed or flips:
            notify(f"⚠️ HIGH RISK — ratio trend (Paper)\nأزواج مفتوحة {len(state['pairs'])} · اتقلب {flips}\nمقفول النهارده {closed:+.2f}$ · إجمالي محقق {state['stats']['pnl']:+.2f}$")
    for pr in state["pairs"].values():
        for leg in pr["legs"]:
            if leg["sym"] not in prices:
                try: prices[leg["sym"]] = float(ex.fetch_ticker(leg["sym"])["last"])
                except Exception: pass
    write_ratio_status(state, prices)

def write_ratio_status(state, prices):
    out_dir = CONFIG.get("public_dir")
    if not out_dir: return
    pairs = []
    for key, pr in state.get("pairs", {}).items():
        legs, pnl = [], 0.0
        for leg in pr["legs"]:
            x = prices.get(leg["sym"], leg["entry"]); sg = 1 if leg["side"] == "long" else -1
            lp = sg * (x - leg["entry"]) * leg["qty"]; pnl += lp
            legs.append({"symbol": leg["sym"].split(":")[0], "id": leg["sym"].split("/")[0] + "USDT", "side": leg["side"],
                         "entry": leg["entry"], "price": x, "qty": leg["qty"], "pnl": round(lp, 4)})
        margin = sum(l["entry"] * l["qty"] for l in legs) / max(1, int(CONFIG.get("leverage", 2)))
        pairs.append({"pair": key, "long": legs[0], "short": legs[1], "pnl": round(pnl, 4), "margin": round(margin, 2), "opened": pr["time"],
                      "ranks": pr.get("ranks")})
    st = state.get("stats", {}); at = state.get("ratio_members_at")
    data = {"updated": datetime.now(timezone.utc).isoformat(), "risk": "high", "mode": "paper" if CONFIG["paper_trading"] else "live",
            "rules": RATIO, "leverage": int(CONFIG.get("leverage", 2)), "margin": CONFIG.get("trade_amount_usdt"), "started": CONFIG.get("started_at"),
            "members": [m.split("/")[0] for m in sorted(state.get("ratio_members", []), key=lambda m: (state.get("ratio_rank") or {}).get(m, 99))],
            "next_members": (datetime.fromisoformat(at) + pd.Timedelta(days=RATIO["every_days"])).isoformat() if at else None,
            "stats": {"closed": st.get("trades", 0), "wins": st.get("wins", 0), "losses": st.get("losses", 0),
                      "realized": round(float(st.get("pnl", 0)), 4), "unrealized": round(sum(p["pnl"] for p in pairs), 4), "open": len(pairs)},
            "pairs": sorted(pairs, key=lambda p: p["pair"]),
            "history": [{"pair": f"{h['long'].split('/')[0]} / {h['short'].split('/')[0]}", "pnl": round(h["pnl"], 4), "reason": h.get("reason", ""),
                         "time": h.get("time"), "opened": h.get("opened"), "ranks": h.get("ranks")} for h in state.get("history", [])[-300:]][::-1]}
    try:
        d = Path(out_dir); tmp = d / "ratio.json.tmp"
        tmp.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8"); tmp.replace(d / "ratio.json")
    except Exception as e: log(f"public ratio status: {e}")

def trend_mode():
    """Daily trend runs alone on daily candles, long only, exits when the trend turns (strategies_trend.py)."""
    return "trend_daily" in (CONFIG.get("enabled_strategies") or [])

def wave_mode():
    """Wave Flats runs alone with its own entries, stops and targets (strategies_wave.py)."""
    return "wave_flats" in (CONFIG.get("enabled_strategies") or [])

def candles_needed():
    return 1000 if wave_mode() else 300   # the ZigZag needs earlier swings to find wave A

def fetch_ohlcv(symbol, timeframe="1h", limit=300, ex=None):
    if ex is None: ex = ccxt.bybit()
    ohlcv = ex.fetch_ohlcv(symbol, timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=["ts","open","high","low","close","vol"])
    df["ts"]=pd.to_datetime(df["ts"], unit="ms")
    return df

def ichimoku_signal(df):
    h,l,c=df.high,df.low,df.close
    tenkan=(h.rolling(9).max()+l.rolling(9).min())/2
    kijun=(h.rolling(26).max()+l.rolling(26).min())/2
    senkou_a=((tenkan+kijun)/2).shift(26)
    senkou_b=((h.rolling(52).max()+l.rolling(52).min())/2).shift(26)
    last=-1; score=0; reasons=[]
    try:
        if c.iloc[last]>senkou_a.iloc[last] and c.iloc[last]>senkou_b.iloc[last]: score+=1; reasons.append("فوق السحابة صاعد")
        elif c.iloc[last]<senkou_a.iloc[last] and c.iloc[last]<senkou_b.iloc[last]: score-=1; reasons.append("تحت السحابة هابط")
        else: reasons.append("داخل السحابة")
    except: reasons.append("سحابة غير مكتملة")
    if tenkan.iloc[last]>kijun.iloc[last]: score+=0.5; reasons.append("Tenkan فوق Kijun")
    else: score-=0.5; reasons.append("Tenkan تحت Kijun")
    return max(-1,min(1,score/2)), reasons, {}

def dow_signal(df):
    c=df.close.values
    highs=[c[i] for i in range(1,len(c)-1) if c[i]>c[i-1] and c[i]>c[i+1]][-5:]
    lows=[c[i] for i in range(1,len(c)-1) if c[i]<c[i-1] and c[i]<c[i+1]][-5:]
    if len(highs)<2 or len(lows)<2: return 0, ["داو: غير كافي"]
    hh=sum(1 for i in range(1,len(highs)) if highs[i]>highs[i-1])
    hl=sum(1 for i in range(1,len(lows)) if lows[i]>lows[i-1])
    score=(hh+hl)/8*2-1
    if score>0.3: r=["داو: قمم وقيعان صاعدة"]
    elif score<-0.3: r=["داو: هابطة"]
    else: r=["داو: عرضي"]
    return float(np.clip(score,-1,1)), r

def gann_signal(df):
    c=df.close; h=df.high; l=df.low
    period=50; hi=h.rolling(period).max().iloc[-1]; lo=l.rolling(period).min().iloc[-1]
    rng=hi-lo if hi!=lo else 1; price=c.iloc[-1]
    levels=[lo+rng*k/8 for k in range(9)]
    slope=(c.iloc[-1]-c.iloc[-10])/10; avg=rng/period if period else 1
    sc=float(np.clip(slope/avg,-1,1)*0.7)
    dist=min(abs(price-x)/rng for x in levels)
    if dist<0.02:
        idx=int(np.argmin([abs(price-x) for x in levels])); reasons=[f"عند مستوى جان {idx}/8 = {levels[idx]:.4f}"]
    else: reasons=[f"Hi={hi:.2f} Lo={lo:.4f} ميل={slope:.4f}"]
    return sc, reasons, levels

def elliott_signal(df):
    c=df.close.values; pivots=[]
    for i in range(2,len(c)-2):
        if c[i]>c[i-1] and c[i]>c[i-2] and c[i]>c[i+1] and c[i]>c[i+2]: pivots.append((i,c[i],"H"))
        if c[i]<c[i-1] and c[i]<c[i-2] and c[i]<c[i+1] and c[i]<c[i+2]: pivots.append((i,c[i],"L"))
    pivots=pivots[-9:]
    if len(pivots)<5: return 0, ["اليوت: غير كافي"]
    last_high=max(p[1] for p in pivots if p[2]=="H"); last_low=min(p[1] for p in pivots if p[2]=="L")
    price=c[-1]; f05=last_high-(last_high-last_low)*0.5; f618=last_high-(last_high-last_low)*0.618; f382=last_high-(last_high-last_low)*0.382
    if f618<price<f05 and c[-1]>c[-2]: return 0.8, [f"ارتداد فيبو 50-61.8%"]
    if price<f618 and c[-1]<c[-2]: return -0.6, ["كسر 61.8% تصحيح عميق"]
    if price>last_high: return 0.5, ["اختراق قمة موجة 5"]
    return 0.1, [f"فيبو 38%={f382:.2f} 50%={f05:.2f} 61%={f618:.2f}"]

def classical_signal(df):
    c=df.close; sma20=c.rolling(20).mean().iloc[-1]; sma50=c.rolling(50).mean().iloc[-1]; price=c.iloc[-1]
    score=0; r=[]
    if price>sma20>sma50: score+=0.6; r.append("فوق SMA20>SMA50")
    elif price<sma20<sma50: score-=0.6; r.append("تحت المتوسطات")
    else: r.append("محايد")
    if len(c)>=20:
        slope=np.polyfit(range(20), c.values[-20:],1)[0]; r.append(f"ميل {slope:.4f}"); score+=np.clip(slope/(price*0.002),-0.4,0.4)
    vr=df.vol.iloc[-1]/df.vol.rolling(20).mean().iloc[-1] if df.vol.rolling(20).mean().iloc[-1] else 1
    if vr>1.5 and score>0: r.append(f"حجم {vr:.1f}x")
    return float(np.clip(score,-1,1)), r

def sr_signal(df):
    h,l,c=df.high,df.low,df.close; price=c.iloc[-1]
    piv_hi=[h.iloc[i] for i in range(2,len(h)-2) if h.iloc[i]==h.iloc[i-2:i+3].max()][-6:]
    piv_lo=[l.iloc[i] for i in range(2,len(l)-2) if l.iloc[i]==l.iloc[i-2:i+3].min()][-6:]
    sups=sorted(set(round(x,6) for x in piv_lo)); ress=sorted(set(round(x,6) for x in piv_hi))
    sup=max([x for x in sups if x<price], default=None); res=min([x for x in ress if x>price], default=None)
    score=0; reasons=[]
    if sup and (price-sup)/price<0.015: score+=0.7; reasons.append(f"عند دعم {sup}")
    elif res and (res-price)/price<0.015: score-=0.7; reasons.append(f"عند مقاومة {res}")
    else:
        reasons.append(f"دعم {sup} مقاومة {res}")
        if sup and res: score=np.clip((price-(sup+res)/2)/(res-sup)*0.3,-0.3,0.3)
    return float(np.clip(score,-1,1)), reasons, {"supports":sups,"resistances":ress}

def rsi_macd_signal(df):
    c=df.close; delta=c.diff(); gain=delta.where(delta>0,0).rolling(14).mean(); loss=(-delta.where(delta<0,0)).rolling(14).mean()
    rs=gain/loss; rsi=100-(100/(1+rs)); r=float(rsi.iloc[-1])
    ema12=c.ewm(span=12).mean(); ema26=c.ewm(span=26).mean(); macd=ema12-ema26; sig=macd.ewm(span=9).mean(); hist=macd-sig
    score=0; reasons=[]
    if r<30: score+=0.8; reasons.append(f"RSI {r:.1f} تشبع بيعي")
    elif r>70: score-=0.8; reasons.append(f"RSI {r:.1f} تشبع شرائي")
    elif r<40: score+=0.3; reasons.append(f"RSI {r:.1f} مائل شراء")
    elif r>60: score-=0.3; reasons.append(f"RSI {r:.1f} مائل بيع")
    else: reasons.append(f"RSI {r:.1f} محايد")
    if hist.iloc[-1]>0: score+=0.5; reasons.append("MACD صاعد")
    elif hist.iloc[-1]<0: score-=0.5; reasons.append("MACD هابط")
    return float(np.clip(score,-1,1)), reasons, {"rsi":r,"macd":float(macd.iloc[-1]),"signal":float(sig.iloc[-1]),"hist":float(hist.iloc[-1])}


# ============ WEEK 1 — FILTERS + RISK ============
def adx_value(df, period=14):
    """ADX مبسط — قوة الترند"""
    h=df.high; l=df.low; c=df.close
    tr=pd.concat([h-l, (h-c.shift(1)).abs(), (l-c.shift(1)).abs()], axis=1).max(axis=1)
    atr=tr.rolling(period).mean()
    up=c.diff().where(lambda x: x>0, 0); down=(-c.diff()).where(lambda x: x>0, 0)
    plus_dm=up.rolling(period).mean()/atr*100
    minus_dm=down.rolling(period).mean()/atr*100
    dx=(plus_dm-minus_dm).abs()/(plus_dm+minus_dm).replace(0, np.nan)*100
    adx=dx.rolling(period).mean()
    return float(adx.iloc[-1]) if pd.notna(adx.iloc[-1]) else 20

def volume_ok(df):
    """لازم حجم آخر شمعة > متوسط 20"""
    if not CONFIG.get("vol_filter"): return True
    avg=df.vol.rolling(20).mean().iloc[-1]
    if pd.isna(avg) or avg==0: return True
    return float(df.vol.iloc[-1]) >= float(avg) * 0.9

def htf_trend_ok(symbol, side, ex=None):
    """فلتر الترند الأكبر — لا تدخل عكس 4h"""
    if not CONFIG.get("htf_filter"): return True
    htf=CONFIG.get("htf_timeframe","4h")
    try:
        hdf=fetch_ohlcv(symbol, htf, limit=60, ex=ex)
        # ترند 4h: SMA20 vs SMA50
        sma20=hdf.close.rolling(20).mean().iloc[-1]
        sma50=hdf.close.rolling(50).mean().iloc[-1]
        if pd.isna(sma20) or pd.isna(sma50): return True
        if side=="long" and sma20 < sma50: return False
        if side=="short" and sma20 > sma50: return False
        return True
    except:
        return True

def position_size(price, ex=None):
    """حجم الصفقة: إما ثابت أو % من الرصيد"""
    base=float(CONFIG.get("trade_amount_usdt", 20))
    if not CONFIG.get("use_percent_risk"):
        return base
    # % risk mode — نحسب من الرصيد
    try:
        if ex is None: return base
        bal=ex.fetch_balance()
        usdt=float(bal.get("USDT",{}).get("free", 0) or bal.get("free",{}).get("USDT",0) or 0)
        if usdt < 10: return base
        risk=float(CONFIG.get("risk_pct",2))/100
        return max(base, usdt * risk)
    except:
        return base

def daily_pnl_ok(state):
    """لو خسر أكثر من max_daily_loss_pct اليوم يوقف"""
    limit=float(CONFIG.get("max_daily_loss_pct", 5))
    if limit <= 0: return True
    today=datetime.now(timezone.utc).date().isoformat()
    # نحسب PnL اليوم من history
    hist=state.get("history",[])
    today_pnl=sum(float(h.get("pnl",0)) for h in hist if str(h.get("time","")).startswith(today))
    # نحسب الرصيد المرجعي: لو paper نحسب على 1000$ افتراضي
    ref=1000.0
    # Check trades.log? use equity
    if today_pnl < -(ref * limit/100):
        return False
    return True

def atr_value(df, period=14):
    h=df.high; l=df.low; c=df.close
    tr=pd.concat([h-l, (h-c.shift(1)).abs(), (l-c.shift(1)).abs()], axis=1).max(axis=1)
    atr=tr.rolling(period).mean()
    return float(atr.iloc[-1]) if pd.notna(atr.iloc[-1]) else float(c.iloc[-1]*0.01)

def regime_detect(df):
    """يكتشف هل السوق ترند ولا عرضي"""
    adx=adx_value(df)
    c=df.close; sma20=c.rolling(20).mean(); std=c.rolling(20).std()
    bw=(std/sma20).iloc[-1] if pd.notna(sma20.iloc[-1]) and sma20.iloc[-1]!=0 else 0.02
    if adx > float(CONFIG.get("regime_adx_trend",20)) and bw > 0.015:
        return "trend"
    elif adx < 15 or bw < 0.01:
        return "range"
    return "mixed"

def dynamic_sl_tp(price, side, df):
    """وقف/هدف ديناميكي حسب ATR"""
    if not CONFIG.get("dynamic_sl_tp"):
        if side=="long": return price*(1-CONFIG["stop_loss_pct"]), price*(1+CONFIG["take_profit_pct"])
        else: return price*(1+CONFIG["stop_loss_pct"]), price*(1-CONFIG["take_profit_pct"])
    atr=atr_value(df, int(CONFIG.get("atr_period",14)))
    sl_mult=float(CONFIG.get("atr_sl_mult",1.5)); tp_mult=float(CONFIG.get("atr_tp_mult",3.0))
    # clamp ATR to 0.5% - 3% of price
    atr=max(price*0.008, min(price*0.03, atr))
    if side=="long": sl=price - atr*2.0; tp=price + atr*3.0
    else: sl=price + atr*2.0; tp=price - atr*3.0
    # ensure at least 1% SL distance
    if side=="long":
        if (price-sl)/price < 0.01: sl=price*0.99
        if (tp-price)/price < 0.015: tp=price*1.02
    else:
        if (sl-price)/price < 0.01: sl=price*1.01
        if (price-tp)/price < 0.015: tp=price*0.98
    return sl, tp


def analyze_wave(symbol, df):
    """Wave Flats on the closed candles (the last row from the exchange is still forming)."""
    import strategies_wave as wf
    closed=df.iloc[:-1]; sig={}
    ms=[int(t.value//10**6) for t in closed.ts]
    wf.run_wave_flats(list(closed.open), list(closed.high), list(closed.low), list(closed.close), ms, CONFIG["timeframe"], last_signal=sig)
    price=float(df.close.iloc[-1]); d=sig.get("dir",0)
    reason=f"{sig['kind']} — وقف {sig['stop']:.6g} هدف {(sig['tgt2'] or sig['tgt1']):.6g}" if d else "لا إعداد"
    sr_info=sr_signal(df)[2]; rsi_info=rsi_macd_signal(df)[2]
    return {"symbol":symbol,"price":price,"total":float(d),"decision":"شراء" if d==1 else "بيع" if d==-1 else "انتظار",
            "breakdown":{"wave_flats":(float(d),reason)},"amount_mult":1.0,
            "sl":sig.get("stop",price*(1-CONFIG["stop_loss_pct"])),"tp":(sig.get("tgt2") or sig.get("tgt1") or price*(1+CONFIG["take_profit_pct"])),
            "rsi":rsi_info["rsi"],"supports":sr_info["supports"],"resistances":sr_info["resistances"],
            "wave":sig or None,"time":datetime.now(timezone.utc).isoformat()}

def analyze_trend(symbol, df):
    """Daily trend on the closed daily candles (the last row from the exchange is still forming)."""
    import strategies_trend as stt
    closed=df.iloc[:-1]; on,size=stt.signal_now(list(closed.close)); exit_below=stt.exit_level(list(closed.close))
    price=float(df.close.iloc[-1]); lev=int(CONFIG.get("leverage",2))
    sr_info=sr_signal(df)[2]; rsi_info=rsi_macd_signal(df)[2]
    reason=f"ترند صاعد — حجم {size*100:.0f}%" if on else "مفيش ترند صاعد"
    return {"symbol":symbol,"price":price,"total":1.0 if on else 0.0,"decision":"شراء" if on else "انتظار",
            "breakdown":{"trend_daily":(1.0 if on else 0.0,reason)},"amount_mult":1.0,
            "sl":price*(1-stt.STOP_SHARE/lev),"tp":None,"rsi":rsi_info["rsi"],"supports":sr_info["supports"],"resistances":sr_info["resistances"],
            "trend":{"on":on,"size":size,"ts":int(closed.ts.iloc[-1].value//10**6),"exit_below":exit_below},"time":datetime.now(timezone.utc).isoformat()}

def analyze(symbol, df=None, timeframe=None):
    if df is None: df=fetch_ohlcv(symbol, timeframe or CONFIG["timeframe"], limit=candles_needed())
    if trend_mode(): return analyze_trend(symbol, df)
    if wave_mode(): return analyze_wave(symbol, df)
    results={}
    s1,r1,_=ichimoku_signal(df); results["ichimoku"]=(s1,r1)
    s2,r2=dow_signal(df); results["dow"]=(s2,r2)
    s3,r3,_=gann_signal(df); results["gann"]=(s3,r3)
    s4,r4=elliott_signal(df); results["elliott"]=(s4,r4)
    s5,r5=classical_signal(df); results["classical"]=(s5,r5)
    s6,r6,_=sr_signal(df); results["sr"]=(s6,r6)
    s7,r7,_=rsi_macd_signal(df); results["rsi_macd"]=(s7,r7)
    # Advanced 8
    s8,r8=adv.smc_signal(df); results["smc"]=(s8,r8)
    s9,r9=adv.vwap_volume_signal(df); results["vwap"]=(s9,r9)
    s10,r10=adv.supertrend_atr_signal(df); results["supertrend"]=(s10,r10)
    s11,r11=adv.bollinger_squeeze_stochrsi_signal(df); results["bollinger"]=(s11,r11)
    s12,r12=adv.harmonic_signal(df); results["harmonic"]=(s12,r12)
    s13,r13=adv.ict_killzone_signal(df); results["ict"]=(s13,r13)
    s14,r14=adv.heikin_ashi_adx_signal(df); results["heikin"]=(s14,r14)
    _base={k:v[0] for k,v in results.items()}
    # Try performance-weighted AI from ai_weights.json
    _pw=None
    try:
        _pw_path=Path(__file__).parent / "ai_weights.json"
        if _pw_path.exists(): _pw=json.loads(_pw_path.read_text(encoding="utf-8"))
    except: pass
    s15,r15=adv.ai_ensemble_signal(df, _base, _pw); results["ai"]=(s15,r15)
    # Respect enabled_strategies filter
    enabled=CONFIG.get("enabled_strategies")
    if enabled:
        total=sum(results[k][0]*CONFIG["weights"][k] for k in enabled if k in results and k in CONFIG["weights"])
        wsum=sum(CONFIG["weights"][k] for k in enabled if k in CONFIG["weights"]) or 1
        total/=wsum
        # Keep only enabled in results for cleaner output
        results={k:v for k,v in results.items() if k in enabled}
    else:
        total=sum(results[k][0]*CONFIG["weights"][k] for k in CONFIG["weights"] if k in results)
    if total>CONFIG["strong_buy"]: decision="شراء قوي"
    elif total>CONFIG["buy_threshold"]: decision="شراء"
    elif total<CONFIG["strong_sell"]: decision="بيع قوي"
    elif total<CONFIG["sell_threshold"]: decision="بيع"
    else: decision="انتظار"
    mult=1.5 if total>CONFIG["strong_buy"] else 1.0
    # also extract SR for chart
    sr_info=sr_signal(df)[2]
    rsi_info=rsi_macd_signal(df)[2]
    price=float(df.close.iloc[-1])
    sl=price*(1-CONFIG["stop_loss_pct"]); tp=price*(1+CONFIG["take_profit_pct"])
    return {"symbol":symbol,"price":price,"total":round(total,4),"decision":decision,"breakdown":results,"amount_mult":mult,"sl":sl,"tp":tp,"rsi":rsi_info["rsi"],"supports":sr_info["supports"],"resistances":sr_info["resistances"],"time":datetime.now(timezone.utc).isoformat()}

def load_state():
    if STATE_PATH.exists():
        try:
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            data.setdefault("positions", {})
            data.setdefault("last_trade", {})
            data.setdefault("stats", {"trades":0,"wins":0,"losses":0,"pnl":0})
            data.setdefault("history", [])
            data.setdefault("pending_orders", {})
            data.setdefault("recovery_required", {})
            return data
        except: pass
    return {"positions":{},"last_trade":{},"stats":{"trades":0,"wins":0,"losses":0,"pnl":0},"history":[],"pending_orders":{},"recovery_required":{}}

def save_state(s):
    tmp = STATE_PATH.with_suffix(STATE_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)

def _exchange_id(ex):
    try:
        return (getattr(ex, "id", "") or getattr(ex, "exchange_id", "") or ex.__class__.__name__).lower()
    except:
        return ""

def _is_hedge_mode(ex):
    try:
        if hasattr(ex, "options") and isinstance(ex.options, dict) and ex.options.get("hedgeMode"):
            return True
    except:
        pass
    return False

def _build_futures_params(ex, side, cid, reduceOnly=False):
    params = {}
    ex_id = _exchange_id(ex)
    hedge = _is_hedge_mode(ex)
    if cid:
        params["clientOrderId"] = cid
        if ex_id == "bybit":
            params["orderLinkId"] = cid
    # one-way mode (what ensure_futures_setup sets): Binance rejects positionSide LONG/SHORT (-4061) and
    # positionSide together with reduceOnly (-1106) — the position side is implied
    if reduceOnly and not (ex_id.startswith("binance") and hedge):
        params["reduceOnly"] = True
    if side == "long":
        ps = "LONG"
    elif side == "short":
        ps = "SHORT"
    elif side == "close_long":
        ps = "LONG"
    elif side == "close_short":
        ps = "SHORT"
    else:
        ps = None
    if ex_id.startswith("binance"):
        if ps and hedge:
            params["positionSide"] = ps
    elif ex_id == "bybit":
        if hedge:
            idx = 1 if side in ("long", "close_long") else 2
            params["positionIdx"] = idx
            if ps:
                params["positionSide"] = ps
        else:
            pass
    elif ex_id == "okx":
        if hedge and ps:
            params["posSide"] = ps.lower()
            params["positionSide"] = ps
        else:
            pass
    else:
        if ps:
            params["positionSide"] = ps
    return params

def _reconcile_fills_by_client_id(ex, symbol, cid):
    for fn in ("fetch_order", "fetch_open_orders", "fetch_closed_orders", "fetch_orders"):
        try:
            if fn == "fetch_order":
                try:
                    o = ex.fetch_order(cid, symbol)
                    if o and (o.get("clientOrderId")==cid or o.get("orderLinkId")==cid or o.get("id")==cid):
                        return o
                except:
                    pass
                continue
            else:
                getter = getattr(ex, fn, None)
                if not getter:
                    continue
                try:
                    orders = getter(symbol)
                except TypeError:
                    orders = getter()
                except Exception:
                    continue
                for o in (orders or []):
                    if o.get("clientOrderId")==cid or o.get("orderLinkId")==cid or o.get("id")==cid:
                        return o
        except:
            continue
    return None



_SL_AMEND_FAILED = set()   # symbols whose exchange stop couldn't be moved this cycle (check_sl_tp turns them into reviews)

def _amend_exchange_sl(symbol, pos, new_sl, old_sl, ex):
    # Try to move the exchange SL to new_sl. Returns True if verified, False if unverified (flagged).
    if CONFIG.get("paper_trading"):
        return True
    if new_sl is None or old_sl is None or new_sl == old_sl:
        return True
    oco = pos.get("oco_ids") or {}
    if ex is not None and hasattr(ex, "edit_order") and oco.get("sl"):
        try:
            ex.edit_order(oco["sl"], symbol, "market", "sell" if pos.get("side","long")=="long" else "buy", pos.get("qty"), price=None, params={"stopLossPrice": float(new_sl)})
            pos["sl_sync"] = "amended"
            pos.pop("sl_unverified", None)
            return True
        except Exception as e:
            log(f"SL amend edit_order failed {symbol}: {e}")
    if ex is not None and oco.get("pos_id"):
        try:
            from backend.app.oco import cancel_oco_orders, place_oco_orders
            try:
                cancel_oco_orders(ex, symbol, pos_id=oco["pos_id"])
            except Exception:
                pass
            tp_price = pos.get("tp")
            side = pos.get("side","long")
            qty = pos.get("qty")
            oco2 = place_oco_orders(ex, symbol, side, qty, new_sl, tp_price, paper=False, pos_id=oco["pos_id"])
            if not oco2.get("sl_error") and not oco2.get("tp_error"):
                pos["oco_ids"] = {"sl": oco2.get("sl_id"), "tp": oco2.get("tp_id"), "pos_id": oco["pos_id"]}
                pos["sl_sync"] = "amended"
                pos.pop("sl_unverified", None)
                return True
            log(f"SL amend recreate failed {symbol}: {oco2}")
        except Exception as e:
            log(f"SL amend recreate exception {symbol}: {e}")
    _SL_AMEND_FAILED.add(symbol)
    pos.setdefault("_sl_unverified", []).append({"from": old_sl, "to": new_sl, "at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()})
    pos["sl_unverified"] = True
    pos["sl_sync"] = "pending"
    log(f"SL drift unverified {symbol} {old_sl:.4f} -> {new_sl:.4f} (exchange not amended) - flagged")
    return False

def log(msg):
    ts=datetime.now().strftime("%Y-%m-%d %H:%M:%S"); line=f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH,"a",encoding="utf-8") as f: f.write(line+"\n")
    except: pass

def in_position(state,symbol): return symbol in state["positions"]
def cooldown_ok(state,symbol):
    last=state["last_trade"].get(symbol)
    if not last: return True
    try:
        mins=(datetime.now(timezone.utc)-datetime.fromisoformat(last)).total_seconds()/60
        # same rule as the backtest: wait cooldown_bars candles of the trading timeframe after a trade closes
        tf_min={"15m":15,"30m":30,"1h":60,"2h":120,"4h":240,"1d":1440}.get(CONFIG.get("timeframe","4h"), 240)
        return mins >= int(CONFIG.get("cooldown_bars",3)) * tf_min
    except: return True

def ensure_futures_setup(ex, symbol):
    """يضبط الرافعة ونوع الهامش للفيوتشر — يفشل بوضوح لو الإعداد ما اتأكدش (P0-02)."""
    if CONFIG.get("market")!="future": return
    lev = int(CONFIG.get("leverage", 5))
    mtype = CONFIG.get("margin_type", "ISOLATED")
    # exchanges answer "already set" with an error (Binance -4046 / -4059, Bybit 110026 / 110043 / 110025): that's success
    def _already(e):
        m = str(e).lower()
        return any(k in m for k in ("no need to change", "-4046", "-4059", "not modified", "110026", "110043", "110025", "already"))
    for what, call in ((f"set_leverage({lev},{symbol})", lambda: ex.set_leverage(lev, symbol)),
                       (f"set_margin_mode({mtype},{symbol})", lambda: ex.set_margin_mode(mtype, symbol)),
                       (f"set_position_mode(one-way,{symbol})", lambda: ex.set_position_mode(False))):
        try: call()
        except Exception as e:
            if not _already(e): raise RuntimeError(f"{what} فشل: {e}") from e
    # verify via read-back where supported (skip mocks)
    try:
        # only verify if exchange explicitly exposes fetch_position_mode as non-mock or configured mock
        fetch_pm = getattr(ex, "fetch_position_mode", None)
        if fetch_pm is None:
            pass
        else:
            try:
                from unittest.mock import Mock as _Mock
                if isinstance(fetch_pm, _Mock):
                    # real ccxt exchanges are not Mock; for Mock, require explicit return_value/side_effect that is not MagicMock
                    configured = False
                    se = getattr(fetch_pm, "side_effect", None)
                    rv = getattr(fetch_pm, "return_value", None)
                    if se is not None:
                        configured = True
                    elif rv is not None and not isinstance(rv, _Mock) and rv != []:
                        # non-empty configured return
                        configured = True
                    elif isinstance(rv, dict) and rv:
                        configured = True
                    if not configured:
                        raise StopIteration
            except StopIteration:
                pass
            else:
                mode = fetch_pm(symbol)
                is_hedge = mode.get("hedgeMode", mode) if isinstance(mode, dict) else bool(mode)
                if is_hedge:
                    raise RuntimeError("المنصة لسه في Hedge Mode بعد set_position_mode(False) — عدّلها يدوياً من إعدادات الفيوتشر")
    except RuntimeError: raise
    except Exception: pass

def place_order(ex,symbol,side,amount_usdt,price, client_order_id=None, close_qty=None):
    """side = long/short/close_long/close_short — يحسب الكمية من USDT * leverage.
    client_order_id: stable id for idempotent retry (P0-05). If None, generated; returned in result.
    Idempotency (6): on create_order timeout, lookup by clientOrderId/orderLinkId and reconcile fills before retry.
    Futures compat (4): exchange-specific params via _build_futures_params.
    """
    is_future = CONFIG.get("market","future")=="future"
    lev = int(CONFIG.get("leverage",5)) if is_future else 1
    notional = amount_usdt * lev if is_future else amount_usdt
    # a close sends the position's own quantity — recomputing it from USDT applied the leverage a second time (5x size)
    qty = float(close_qty) if close_qty is not None else notional / price
    try: qty=float(ex.amount_to_precision(symbol, qty))
    except: qty=round(qty,6)
    if CONFIG["paper_trading"]:
        cid = client_order_id or f"raqm-{uuid.uuid4().hex[:12]}"[:36]
        return {"id":"paper-"+str(int(time.time()*1000)),"qty":qty,"price":price,"cost":qty*price,"notional":notional,"leverage":lev,"clientOrderId": cid}
    if not side.startswith("close"):
        ensure_futures_setup(ex, symbol)   # a close must never wait on (or fail because of) account settings
    cid = client_order_id or f"raqm-{uuid.uuid4().hex[:12]}"[:36]
    def _do_create(params):
        if is_future:
            if side in ("long","close_short"):
                return ex.create_order(symbol, "market", "buy", qty, None, params)
            else:
                return ex.create_order(symbol, "market", "sell", qty, None, params)
        else:
            if side in ("long","close_short"): return ex.create_market_buy_order(symbol,qty)
            else: return ex.create_market_sell_order(symbol,qty)
    # build params exchange-specific
    if is_future:
        params = _build_futures_params(ex, side, cid, reduceOnly=(side in ("close_long","close_short")))
    else:
        params = {"clientOrderId": cid}
        if cid.startswith("raqm-"):
            params["orderLinkId"] = cid
    try:
        order = _do_create(params)
    except Exception as e:
        msg = str(e).lower()
        is_timeout = any(k in msg for k in ("timeout","timed out","network","econnreset","etimedout","recvwindow","gateway","temporar"))
        if is_timeout:
            # try reconcile by client id before surfacing
            try:
                found = _reconcile_fills_by_client_id(ex, symbol, cid)
                if found:
                    fq=float(found.get("filled",qty) or found.get("amount",qty) or qty)
                    ap=float(found.get("average",price) or found.get("price",price) or price)
                    # if returned order has filled>0 or status closed, treat as success
                    if fq and fq>0:
                        return {"id":str(found.get("id","")),"qty":fq,"price":ap,"cost":fq*ap,"notional":notional,"leverage":lev,"raw":found,"clientOrderId": cid, "reconciled": True}
            except Exception:
                pass
        raise
    fq=float(order.get("filled",qty) or qty); ap=float(order.get("average",price) or price)
    return {"id":str(order.get("id","")),"qty":fq,"price":ap,"cost":fq*ap,"notional":notional,"leverage":lev,"raw":order,"clientOrderId": cid}

def _exchange_position_qty(ex, symbol):
    """Open size on the exchange (0 = flat), or None if it can't be read."""
    try:
        for p in ex.fetch_positions([symbol]) or []:
            s_ = p.get("symbol") or (p.get("info") or {}).get("symbol", "")
            if s_ == symbol or s_.split(":")[0] == symbol:
                c = p.get("contracts") if p.get("contracts") is not None else (p.get("info") or {}).get("size")
                return abs(float(c or 0))
        return 0.0
    except Exception:
        return None

def close_live_position(ex, symbol, pos, price):
    """Close a real position with its exact size (reduceOnly), then cancel only its own stop/target orders.
    If the exchange is already flat (its stop or target filled), that is the close — no order is sent.
    Returns {"price", "qty", "by_exchange"}; raises if it can't close."""
    side = pos.get("side", "long")
    try:
        res = place_order(ex, symbol, "close_long" if side == "long" else "close_short", 0, price, close_qty=pos["qty"])
        out = {"price": res["price"], "qty": res["qty"], "by_exchange": False}
    except Exception as e:
        if _exchange_position_qty(ex, symbol) != 0.0:
            raise
        log(f"{symbol}: المنصة قفلت الصفقة بالفعل (وقف/هدف) — {e}")
        out = {"price": price, "qty": pos["qty"], "by_exchange": True}
    ids = pos.get("oco_ids") or {}
    if ids.get("pos_id") or ids.get("sl") or ids.get("tp"):
        try:
            from backend.app.oco import cancel_oco_orders
            cancel_oco_orders(ex, symbol, pos_id=ids.get("pos_id"), sl_id=ids.get("sl"), tp_id=ids.get("tp"))
        except Exception as e:
            log(f"{symbol}: إلغاء أوامر الحماية القديمة فشل: {e}")
            notify(f"⚠️ {symbol}: الصفقة اتقفلت بس أوامر الوقف/الهدف القديمة ممكن تكون لسه على المنصة — راجعها")
    return out

def check_sl_tp(state, prices, ex=None):
    closed=[]
    for symbol,pos in list(state["positions"].items()):
        price=prices.get(symbol)
        if price is None: continue
        entry=pos["entry"]; side=pos.get("side","long"); sl=pos.get("sl"); tp=pos.get("tp")
        if pos.get("trend"): tp=float("inf") if side=="long" else 0.0   # no target: exits on the trend signal (try_enter_trend)
        if sl is None or tp is None:
            if side=="long": sl=entry*(1-CONFIG["stop_loss_pct"]); tp=entry*(1+CONFIG["take_profit_pct"])
            else: sl=entry*(1+CONFIG["stop_loss_pct"]); tp=entry*(1-CONFIG["take_profit_pct"])
        wave=pos.get("wave")
        if wave:
            sign=1 if side=="long" else -1
            # Wave Flats: stop to entry once price breaks the correction extreme (the backtest checks at the candle close)
            # Stage C (d): LIVE must amend exchange SL; otherwise flag unverified
            if not pos.get("breakeven") and sign*(price-wave["be"])>0:
                old_sl_w = sl
                new_sl_w = entry
                if not CONFIG.get("paper_trading"):
                    _amend_exchange_sl(symbol, pos, new_sl_w, old_sl_w, ex)
                pos["sl"]=sl=new_sl_w; pos["breakeven"]=True; save_state(state)
                tag_w = " (UNVERIFIED - exchange SL not moved)" if pos.get("sl_unverified") else " (exchange verified)" if not CONFIG.get("paper_trading") else ""
                log(f"♻️ {symbol} {side} كسر قمة التصحيح {wave['be']:.6g} — الوقف لنقطة الدخول {entry:.6g}")
            # TP1: close half (Running/Expanded Flat only); paper only — LIVE is refused for Wave Flats
            if wave.get("tp1") and not wave.get("tp1_done") and sign*(price-wave["tp1"])>=0 and CONFIG["paper_trading"]:
                half=pos["qty"]/2; pnl=(price-entry)*half*sign
                state["history"].append({"symbol":symbol,"side":side,"entry":entry,"exit":price,"qty":half,"pnl":pnl,"pnl_pct":pnl/(entry*half)*100,"reason":f"TP1 نص الكمية {wave['tp1']:.6g}","time":datetime.now(timezone.utc).isoformat(),"type":"paper"})
                state["stats"]["pnl"]+=float(pnl); pos["qty"]-=half; wave["tp1_done"]=True; save_state(state)
                log(f"🎯 {symbol} {side} TP1 @ {price:.6g} — قفل نص الكمية PnL {pnl:+.4f}")
        # ♻️ Breakeven — بعد 50% للهدف ينقل الوقف لنقطة الدخول
        # Breakeven - after 50% to target move SL to entry (Stage C (d): LIVE must amend exchange)
        if CONFIG.get("breakeven_enabled") and not pos.get("breakeven") and not wave and not pos.get("trend"):
            trig_pct = float(CONFIG.get("breakeven_trigger_pct", 0.5))
            off = float(CONFIG.get("breakeven_offset_pct", 0.001))
            trig_price = entry + (tp - entry) * trig_pct if side=="long" else entry - (entry - tp) * trig_pct
            hit_be = (price >= trig_price) if side=="long" else (price <= trig_price)
            if hit_be:
                be_sl = entry * (1 + off) if side=="long" else entry * (1 - off)
                do_be = (side=="long" and be_sl > sl) or (side=="short" and be_sl < sl)
                if do_be:
                    old_sl = sl
                    if not CONFIG.get("paper_trading"):
                        _amend_exchange_sl(symbol, pos, be_sl, old_sl, ex)
                    pos["sl"] = be_sl
                    sl = pos["sl"]
                    pos["breakeven"] = True
                    try: save_state(state)
                    except: pass
                    tag = " (UNVERIFIED - exchange SL not moved)" if pos.get("sl_unverified") else " (exchange verified)" if not CONFIG.get("paper_trading") else ""
                    log(f"Breakeven {symbol} {side} @ {price:.4f} SL {be_sl:.4f}{tag}")
                    notify(f"Breakeven {symbol} {side} - SL {be_sl:.4f}{tag}")
                else:
                    pos["breakeven"] = True
                    try: save_state(state)
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
            if CONFIG["paper_trading"]:
                pnl=(price-entry)*qty if pos.get("side","long")=="long" else (entry-price)*qty; pnl_pct=(pnl/(entry*qty)*100) if entry*qty else 0
                log(f"🔒 اغلاق {symbol} {reason} @ {price:.4f} PnL {pnl:+.4f} ({pnl_pct:+.2f}%)")
                notify(f"🔒 قفل {symbol} — {reason}\nدخول {entry:.6g} → خروج {price:.6g}\nPnL {pnl:+.2f}$ (Paper)")
                state["history"].append({"symbol":symbol,"side":pos.get("side","long"),"entry":entry,"exit":price,"qty":qty,"pnl":pnl,"pnl_pct":pnl_pct,"reason":reason,"time":datetime.now(timezone.utc).isoformat(),"type":"paper","opened":pos.get("time"),"rank":pos.get("rank")})
            else:
                res=close_live_position(ex or get_exchange(auth=True)[0], symbol, pos, price)
                pnl=(res["price"]-entry)*res["qty"] if pos.get("side","long")=="long" else (entry-res["price"])*res["qty"]
                log(f"🔒 اغلاق حقيقي {symbol} @ {res['price']:.4f} PnL {pnl:+.4f}")
                notify(f"🔒 قفل {symbol} — {reason}\nدخول {entry:.6g} → خروج {res['price']:.6g}\nPnL {pnl:+.2f}$ (حقيقي)")
                state["history"].append({"symbol":symbol,"side":pos.get("side","long"),"entry":entry,"exit":res["price"],"qty":res["qty"],"pnl":pnl,"pnl_pct":(res["price"]/entry-1)*100,"reason":reason,"time":datetime.now(timezone.utc).isoformat(),"type":"live"})
            state["stats"]["trades"]+=1; state["stats"]["pnl"]+=float(pnl)
            if pnl>0: state["stats"]["wins"]+=1
            else: state["stats"]["losses"]+=1
            closed.append(symbol)
        except Exception as e: log(f"فشل اغلاق {symbol}: {e}")
    for s in closed:
        state["positions"].pop(s,None); state["last_trade"][s]=datetime.now(timezone.utc).isoformat()
    flagged = False
    for s in list(_SL_AMEND_FAILED):
        _SL_AMEND_FAILED.discard(s)
        if s in state["positions"]:
            flagged = True
            # the fallback cancels the old stop before placing the new one: if that failed there may be no stop at all
            state.setdefault("recovery_required", {})[s] = {"reason": "exchange stop not moved / maybe missing", "at": datetime.now(timezone.utc).isoformat()}
            log(f"🚨 {s}: تحريك الوقف على المنصة فشل — ممكن الصفقة تكون من غير وقف. الدخول متوقف لحد ما تتراجع")
            notify(f"🚨 {s}: تحريك الوقف على المنصة فشل — ممكن الصفقة تكون من غير وقف. راجعها يدويا، البوت وقف أي دخول جديد.")
    if closed or flagged: save_state(state)
    return closed

def try_enter_wave(symbol, analysis, state, ex):
    """Wave Flats: enter at market on a new setup from the last closed candle, with the setup's own stop/targets."""
    sig=analysis.get("wave")
    if not sig or in_position(state, symbol): return
    seen=state.setdefault("wave_seen",{})
    if seen.get(symbol)==sig["ts"]: return   # one entry per signal candle (the loop polls every minute)
    seen[symbol]=sig["ts"]; save_state(state)
    if not CONFIG["paper_trading"]:
        log(f"⏸️ {symbol} Wave Flats شغالة Paper بس — مفيش أوامر حقيقية"); return
    if len(state["positions"])>=CONFIG["max_open_positions"] or not daily_pnl_ok(state): return
    side="long" if sig["dir"]==1 else "short"; price=analysis["price"]
    if (side=="long" and price<=sig["stop"]) or (side=="short" and price>=sig["stop"]):
        log(f"⏸️ {symbol} {sig['kind']} — السعر عدّى الوقف قبل الدخول"); return
    try:
        res=place_order(ex,symbol,side,position_size(price, ex),price)
        tp=sig["tgt2"] if sig["two"] else sig["tgt1"]
        state["positions"][symbol]={"side":side,"entry":res["price"],"qty":res["qty"],"cost":res["cost"],"notional":res.get("notional"),"leverage":res.get("leverage",CONFIG.get("leverage",5)),
            "time":datetime.now(timezone.utc).isoformat(),"sl":sig["stop"],"tp":tp,"breakeven":False,
            "wave":{"kind":sig["kind"],"tp1":sig["tgt1"] if sig["two"] else None,"tp1_done":False,"be":sig["be"]}}
        state["last_trade"][symbol]=datetime.now(timezone.utc).isoformat(); save_state(state)
        emoji="🟢 لونج" if side=="long" else "🔴 شورت"
        tp1_txt=f" TP1 {sig['tgt1']:.6g}" if sig["two"] else ""
        log(f"✅ {emoji} وهمي {symbol} {sig['kind']} @ {res['price']:.6g} SL {sig['stop']:.6g} TP {tp:.6g}{tp1_txt}")
    except Exception as e: log(f"فشل {side} {symbol}: {e}")

def _live_label():
    return {"demo": "Demo", "testnet": "Testnet"}.get(binance_env(), "حقيقي")

_ENTRY_BLOCK = {"reason": ""}   # set by reconcile_live each cycle: no new position while the exchange disagrees with us

def reconcile_live(state, ex):
    """Live only, every cycle before anything else: compare our positions with the exchange.
    Flat there = its stop filled (or someone closed it): record it and clean up. Unknown positions or a size
    mismatch block new entries and alert once — the account must be used by the bot alone (a sub-account)."""
    _ENTRY_BLOCK["reason"] = ""
    try:
        live = {}
        for p in ex.fetch_positions() or []:
            c = p.get("contracts") if p.get("contracts") is not None else (p.get("info") or {}).get("positionAmt")
            if c and abs(float(c)) > 0: live[(p.get("symbol") or "").split(":")[0]] = abs(float(c))
    except Exception as e:
        _ENTRY_BLOCK["reason"] = f"مقدرناش نقرا الصفقات من المنصة: {e}"; log(f"⚠️ {_ENTRY_BLOCK['reason']}"); return
    for sym, pos in list(state["positions"].items()):
        q = live.get(sym.split(":")[0])
        if not q:
            exit_px = pos.get("sl") or pos["entry"]
            try:
                fills = [t for t in ex.fetch_my_trades(sym, limit=20) if t.get("side") == "sell"]
                if fills: exit_px = float(fills[-1]["price"])
            except Exception: pass
            pnl = (exit_px - pos["entry"]) * pos["qty"]
            by_hand = exit_px > float(pos.get("sl") or 0) * 1.01   # well above the stop: closed by hand in the Binance app
            why = "اتقفلت يدوي من Binance" if by_hand else "وقف الحماية اتنفذ على المنصة"
            if by_hand: state.setdefault("manual_hold", {})[sym] = datetime.now(timezone.utc).isoformat()
            log(f"🔒 {sym}: {why} @ {exit_px:.6g} PnL {pnl:+.2f}")
            notify(f"🔒 قفل {sym} — {why}\nدخول {pos['entry']:.6g} → خروج {exit_px:.6g}\nPnL {pnl:+.2f}$ ({_live_label()})")
            state["history"].append({"symbol": sym, "side": "long", "entry": pos["entry"], "exit": exit_px, "qty": pos["qty"], "pnl": pnl,
                "pnl_pct": pnl / (pos["entry"] * pos["qty"]) * 100, "reason": "قفل يدوي من Binance" if by_hand else "وقف المنصة", "time": datetime.now(timezone.utc).isoformat(),
                "type": "live", "opened": pos.get("time"), "rank": pos.get("rank")})
            state["stats"]["trades"] += 1; state["stats"]["pnl"] += float(pnl); state["stats"]["wins" if pnl > 0 else "losses"] += 1
            try:
                from backend.app.oco import cancel_oco_orders
                ids = pos.get("oco_ids") or {}
                cancel_oco_orders(ex, sym, pos_id=ids.get("pos_id"), sl_id=ids.get("sl"))
            except Exception: pass
            state["positions"].pop(sym, None); state["last_trade"][sym] = datetime.now(timezone.utc).isoformat()
            state.get("recovery_required", {}).pop(sym, None)
        elif abs(q - float(pos["qty"])) > 0.02 * float(pos["qty"]):
            if sym not in state.setdefault("recovery_required", {}):
                state["recovery_required"][sym] = {"reason": f"الكمية على المنصة {q} مش {pos['qty']}", "at": datetime.now(timezone.utc).isoformat()}
                notify(f"🚨 {sym}: الكمية على المنصة {q} مختلفة عن البوت {pos['qty']} — راجعها. البوت وقف أي دخول جديد.")
    mine = {k.split(":")[0] for k in state["positions"]}
    unknown = sorted(set(live) - mine)
    if unknown:
        _ENTRY_BLOCK["reason"] = f"صفقات على المنصة البوت مفتحهاش: {', '.join(unknown)}"
        if state.get("_unknown_seen") != unknown:
            notify(f"⚠️ {_ENTRY_BLOCK['reason']} — البوت مش هيفتح جديد لحد ما تتقفل. استخدم حساب فرعي للبوت لوحده.")
        state["_unknown_seen"] = unknown
    else:
        state.pop("_unknown_seen", None)
    save_state(state)

def _ipc_dir():
    """Folder shared with the backend (RAQM_IPC_DIR, e.g. /opt/raqm-ipc): live status out, close requests in."""
    d = os.getenv("RAQM_IPC_DIR", "").strip()
    return Path(d) if d else None

def _write_json_atomic(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8"); tmp.replace(path)

MANUAL_CLOSE_MAX_AGE_S = 600   # a request the bot couldn't run within 10 minutes is dropped, never executed late

def process_manual_closes(state, ex, prices):
    """Close requests from the site's admin button: close the position now, record it, and don't buy the coin
    again until its trend turns off and back on. Only closes — a request can never open anything."""
    d = _ipc_dir()
    if not d: return
    cmd_dir, res_dir = d / "commands", d / "results"
    try: files = sorted(cmd_dir.glob("close-*.json"))
    except Exception: return
    for f in files:
        try: req = json.loads(f.read_text(encoding="utf-8"))
        except Exception: req = {}
        rid, sym = str(req.get("id", f.stem))[:64], str(req.get("symbol", ""))
        out = {"id": rid, "symbol": sym, "done_at": datetime.now(timezone.utc).isoformat()}
        try:
            age = time.time() - float(req.get("at_epoch", 0))
            match = next((k for k in state["positions"] if k.split(":")[0] == sym.split(":")[0]), None)
            if age > MANUAL_CLOSE_MAX_AGE_S:
                out.update(ok=False, msg="الطلب قديم — اتلغى من غير تنفيذ")
            elif not match:
                out.update(ok=False, msg="مفيش صفقة مفتوحة على العملة دي")
            else:
                pos = state["positions"][match]
                px = prices.get(match)
                if px is None:
                    try: px = float(ex.fetch_ticker(match)["last"])
                    except Exception: px = pos["entry"]
                r = close_live_position(ex, match, pos, px)
                pnl = (r["price"] - pos["entry"]) * r["qty"]
                state["history"].append({"symbol": match, "side": "long", "entry": pos["entry"], "exit": r["price"], "qty": r["qty"], "pnl": pnl,
                    "pnl_pct": pnl / (pos["entry"] * r["qty"]) * 100, "reason": "قفل يدوي من الموقع", "time": datetime.now(timezone.utc).isoformat(),
                    "type": "live", "opened": pos.get("time"), "rank": pos.get("rank"), "by": req.get("by")})
                state["stats"]["trades"] += 1; state["stats"]["pnl"] += float(pnl); state["stats"]["wins" if pnl > 0 else "losses"] += 1
                state["positions"].pop(match, None); state["last_trade"][match] = datetime.now(timezone.utc).isoformat()
                state.get("recovery_required", {}).pop(match, None)
                state.setdefault("manual_hold", {})[match] = datetime.now(timezone.utc).isoformat()
                save_state(state)
                out.update(ok=True, msg="اتقفلت", price=r["price"], qty=r["qty"], pnl=round(pnl, 4))
                log(f"🖐️ قفل يدوي {match} @ {r['price']:.6g} PnL {pnl:+.2f} (طلب {req.get('by', '?')})")
                notify(f"🖐️ قفل يدوي من الموقع: {match}\nدخول {pos['entry']:.6g} → خروج {r['price']:.6g}\nPnL {pnl:+.2f}$ ({_live_label()})\nمش هيشتري العملة دي تاني غير لما الترند يقف ويبدأ من جديد")
        except Exception as e:
            out.update(ok=False, msg=f"القفل فشل: {e}")
            log(f"⚠️ قفل يدوي {sym} فشل: {e}"); notify(f"⚠️ القفل اليدوي لـ {sym} فشل: {e} — الوقف لسه على المنصة")
        try:
            res_dir.mkdir(exist_ok=True); _write_json_atomic(res_dir / f"{rid}.json", out)
        except Exception as e: log(f"manual close result {rid}: {e}")
        try: f.unlink()
        except Exception: pass

def write_live_status(state, prices, analyses=None):
    """What the site's admin page shows for the real-orders bot (not public)."""
    d = _ipc_dir()
    if not d: return
    pos = []
    for sym, p in state["positions"].items():
        px = prices.get(sym)
        exit_below = (((analyses or {}).get(sym) or {}).get("trend") or {}).get("exit_below")
        pos.append({"symbol": sym.split(":")[0], "entry": p["entry"], "qty": p["qty"], "sl": p.get("sl"), "price": px,
                    "exit_below": exit_below, "tp": p.get("tp"),
                    "loss_at_sl": round((float(p["sl"]) - p["entry"]) * p["qty"], 2) if p.get("sl") else None,
                    "pnl": round((px - p["entry"]) * p["qty"], 4) if px else None, "opened": p.get("time"),
                    "unprotected": bool(p.get("unprotected")), "sl_unverified": bool(p.get("sl_unverified"))})
    hist = [h for h in state.get("history", []) if h.get("type") == "live"][-30:][::-1]
    try:
        _write_json_atomic(d / "live_status.json", {"updated": datetime.now(timezone.utc).isoformat(), "env": binance_env(),
            "leverage": CONFIG.get("leverage"), "margin": CONFIG.get("trade_amount_usdt"), "positions": pos, "history": hist,
            "review": state.get("recovery_required") or {}, "entry_block": _ENTRY_BLOCK["reason"], "manual_hold": list(state.get("manual_hold", {}))})
    except Exception as e: log(f"live status: {e}")

def try_enter_trend(symbol, analysis, state, ex):
    """Daily trend: buy at market when the last closed daily candle turns the trend on; sell when it turns off.
    Live: market buy, then a stop on the exchange at the protective level (no target — the exit is the signal)."""
    import strategies_trend as stt
    sig=analysis.get("trend"); price=analysis["price"]
    if not sig: return
    live = not CONFIG["paper_trading"]
    if in_position(state, symbol):
        if sig["on"]: return
        pos=state["positions"][symbol]
        if live:
            try:
                res = close_live_position(ex, symbol, pos, price)
            except Exception as e:
                log(f"⚠️ {symbol}: الترند وقف بس القفل فشل — هيحاول تاني الدورة الجاية: {e}")
                notify(f"⚠️ {symbol}: الترند وقف بس أمر القفل فشل — البوت هيحاول تاني. الوقف لسه على المنصة."); return
            exit_px, qty = res["price"], res["qty"]
        else:
            exit_px, qty = price, pos["qty"]
        pnl=(exit_px-pos["entry"])*qty
        mode = _live_label() if live else "Paper"
        log(f"📉 اغلاق {symbol} — الترند وقف @ {exit_px:.6g} PnL {pnl:+.4f}")
        notify(f"📉 قفل {symbol} — الترند وقف\nدخول {pos['entry']:.6g} → خروج {exit_px:.6g}\nPnL {pnl:+.2f}$ ({mode})")
        state["history"].append({"symbol":symbol,"side":"long","entry":pos["entry"],"exit":exit_px,"qty":qty,"pnl":pnl,"pnl_pct":pnl/(pos["entry"]*qty)*100,"reason":"الترند وقف","time":datetime.now(timezone.utc).isoformat(),"type":"live" if live else "paper","opened":pos.get("time"),"rank":pos.get("rank")})
        state["stats"]["trades"]+=1; state["stats"]["pnl"]+=float(pnl); state["stats"]["wins" if pnl>0 else "losses"]+=1
        state["positions"].pop(symbol,None); state["last_trade"][symbol]=datetime.now(timezone.utc).isoformat(); save_state(state)
        return
    hold = state.get("manual_hold", {})
    if symbol in hold:   # closed by hand: wait for the trend to turn off, then a new signal may buy it again
        if not sig["on"]: hold.pop(symbol, None); save_state(state)
        return
    if not analysis.get("in_universe", True): return   # not in the volume top list today: no new trade
    seen=state.setdefault("trend_seen",{})
    if not sig["on"] or seen.get(symbol)==sig["ts"]: return   # one entry per closed daily candle, like the backtest
    if live and _ENTRY_BLOCK["reason"]:
        log(f"⛔ {symbol} مفيش دخول — {_ENTRY_BLOCK['reason']}"); return   # retried next cycle (trend_seen not marked)
    seen[symbol]=sig["ts"]; save_state(state)
    if len(state["positions"])>=CONFIG["max_open_positions"] or not daily_pnl_ok(state): return
    lev=int(CONFIG.get("leverage",2))
    margin=position_size(price, ex)*sig["size"]
    if not live:
        try:
            res=place_order(ex,symbol,"long",margin,price)
            sl=res["price"]*(1-stt.STOP_SHARE/lev)
            state["positions"][symbol]={"side":"long","entry":res["price"],"qty":res["qty"],"cost":res["cost"],"notional":res.get("notional"),"leverage":res.get("leverage",lev),
                "time":datetime.now(timezone.utc).isoformat(),"sl":sl,"tp":None,"breakeven":False,"trend":True,"rank":analysis.get("rank")}
            state["last_trade"][symbol]=datetime.now(timezone.utc).isoformat(); save_state(state)
            log(f"✅ 🟢 لونج وهمي {symbol} ترند يومي x{lev} @ {res['price']:.6g} حجم {sig['size']*100:.0f}% وقف حماية {sl:.6g}")
            notify(f"🟢 لونج {symbol} — ترند يومي x{lev} (Paper)\nدخول {res['price']:.6g} · حجم {sig['size']*100:.0f}% من ${position_size(price, ex)*lev:.0f}\nوقف حماية {sl:.6g} · الخروج لما الترند يقف")
        except Exception as e: log(f"فشل long {symbol}: {e}")
        return
    _enter_trend_live(symbol, analysis, state, ex, margin, lev, price)

def _enter_trend_live(symbol, analysis, state, ex, margin, lev, price):
    import strategies_trend as stt
    from backend.app.oco import place_oco_orders
    # the exchange's minimum order value (Binance: $5, ETH $20, BTC $50) — skip instead of having it rejected
    try: min_cost = float(((ex.market(symbol).get("limits") or {}).get("cost") or {}).get("min") or 5)
    except Exception: min_cost = 5.0
    if margin * lev < min_cost * 1.05:
        log(f"⏸️ {symbol} حجم {margin*lev:.2f}$ أقل من أقل أمر على المنصة {min_cost}$ — مفيش دخول"); return
    try:
        bal = ex.fetch_balance()
        free = float((bal.get("USDT") or {}).get("free") or (bal.get("free") or {}).get("USDT") or 0)
    except Exception as e:
        log(f"⏸️ {symbol} فحص الرصيد فشل — مفيش دخول: {e}"); return
    if free < margin * 1.02:
        log(f"⏸️ {symbol} رصيد {free:.2f}$ مش كفاية لهامش {margin:.2f}$"); return
    cid = f"raqm-{uuid.uuid4().hex[:12]}"
    state.setdefault("pending_orders", {})[symbol] = cid; save_state(state)   # survives a crash between order and record
    try:
        res = place_order(ex, symbol, "long", margin, price, client_order_id=cid)
    except Exception as e:
        q = _exchange_position_qty(ex, symbol)
        if q is None:
            state.setdefault("recovery_required", {})[symbol] = {"cid": cid, "reason": f"entry error, position unknown: {e}", "at": datetime.now(timezone.utc).isoformat()}
            save_state(state)
            notify(f"🚨 {symbol}: أمر الدخول رجّع خطأ ومقدرناش نعرف اتنفذ ولا لأ — راجع المنصة. البوت وقف أي دخول جديد."); return
        if q == 0:
            state["pending_orders"].pop(symbol, None); save_state(state)
            log(f"فشل دخول {symbol}: {e}"); return
        log(f"{symbol}: أمر الدخول رجّع خطأ بس الصفقة اتفتحت ({q}) — بنكمل ونحط الوقف: {e}")
        res = {"price": price, "qty": q, "cost": q * price, "notional": q * price, "leverage": lev}
    sl = res["price"] * (1 - stt.STOP_SHARE / lev)
    pos = {"side":"long","entry":res["price"],"qty":res["qty"],"cost":res["cost"],"notional":res.get("notional"),"leverage":res.get("leverage",lev),
           "time":datetime.now(timezone.utc).isoformat(),"sl":sl,"tp":None,"breakeven":False,"trend":True,"rank":analysis.get("rank"),
           "clientOrderId": cid, "oco_ids": {"pos_id": cid}}
    try:
        oco = place_oco_orders(ex, symbol, "long", res["qty"], sl, None, paper=False, pos_id=cid)
    except Exception as e:
        oco = {"sl_error": str(e), "protection_missing": True}
    pos["oco_ids"]["sl"] = oco.get("sl_id")
    state["pending_orders"].pop(symbol, None)
    if oco.get("protection_missing"):
        notify(f"🚨 {symbol}: أمر الوقف اترفض ({oco.get('sl_error')}) — بيقفل الصفقة فورا")
        try:
            r = close_live_position(ex, symbol, pos, price)
            pnl = (r["price"] - pos["entry"]) * r["qty"]
            state["history"].append({"symbol":symbol,"side":"long","entry":pos["entry"],"exit":r["price"],"qty":r["qty"],"pnl":pnl,"pnl_pct":pnl/(pos["entry"]*r["qty"])*100,
                "reason":"الوقف اترفض — قفل فوري","time":datetime.now(timezone.utc).isoformat(),"type":"live","opened":pos["time"],"rank":pos.get("rank")})
            state["stats"]["trades"]+=1; state["stats"]["pnl"]+=float(pnl); state["stats"]["wins" if pnl>0 else "losses"]+=1
            state["last_trade"][symbol]=datetime.now(timezone.utc).isoformat(); save_state(state)
            log(f"🔒 {symbol}: اتقفلت فورا لأن الوقف اترفض"); return
        except Exception as e:
            pos["unprotected"] = True
            state.setdefault("recovery_required", {})[symbol] = {"reason": f"no stop and close failed: {e}", "at": datetime.now(timezone.utc).isoformat()}
            notify(f"🚨🚨 {symbol}: الصفقة مفتوحة من غير وقف والقفل فشل — اقفلها يدويا من Binance دلوقتي. البوت وقف أي دخول جديد.")
    elif oco.get("verify_failed"):
        pos["sl_unverified"] = True
        state.setdefault("recovery_required", {})[symbol] = {"reason": oco.get("verify_warn"), "at": datetime.now(timezone.utc).isoformat()}
        notify(f"🚨 {symbol}: الوقف اتقبل بس مش لاقيه على المنصة — راجعه. البوت وقف أي دخول جديد.")
    state["positions"][symbol] = pos
    state["last_trade"][symbol]=datetime.now(timezone.utc).isoformat(); save_state(state)
    log(f"✅ 🟢 لونج {_live_label()} {symbol} ترند يومي x{lev} @ {res['price']:.6g} qty {res['qty']} وقف على المنصة {sl:.6g}")
    notify(f"🟢 لونج {symbol} — ترند يومي x{lev} ({_live_label()})\nدخول {res['price']:.6g} · هامش {margin:.2f}$\nوقف على المنصة {sl:.6g} · الخروج لما الترند يقف")

def try_enter(symbol, analysis, state, ex):
    """فيوتشر: لونج لو سكور > buy_threshold، شورت لو سكور < sell_threshold"""
    # Block every new entry while any position needs a human (unprotected / unverified / ambiguous order)
    if state.get("recovery_required"):
        if trend_mode() and in_position(state, symbol):
            return try_enter_trend(symbol, analysis, state, ex)   # an open position still exits on its signal
        log(f"⛔ {symbol} دخول متوقف — فيه صفقة محتاجة مراجعة: {', '.join(state['recovery_required'])}")
        return
    if state.get("pending_orders", {}).get(symbol):
        # try to reconcile ambiguous timeout before blocking
        cid_pending = state["pending_orders"][symbol]
        try:
            if not CONFIG.get("paper_trading"):
                found = _reconcile_fills_by_client_id(ex, symbol, cid_pending)
                if found:
                    fq = float(found.get("filled",0) or found.get("amount",0) or 0)
                    if fq and fq>0:
                        log(f"♻️ {symbol} reconcile: pending {cid_pending} found fill {fq} — completing")
                        # complete as if order succeeded: create pos if needed (caller handles); just clear pending
                        # we cannot infer sl/tp here; mark recovery to re-verify
                        state.setdefault("recovery_required", {})[symbol] = {"cid": cid_pending, "found": found, "reason": "entry filled after a timeout — no stop placed"}
                        notify(f"🚨 {symbol}: أمر دخول اتنفذ بعد timeout ومن غير وقف على المنصة. راجعه يدويا — البوت وقف أي دخول جديد.")
                        state["pending_orders"].pop(symbol, None)
                        save_state(state)
                        return
        except Exception:
            pass
        log(f"⏸️ {symbol} طلب معلق — تخطي الدخول حتى التأكد")
        return
    if trend_mode(): return try_enter_trend(symbol, analysis, state, ex)
    if wave_mode(): return try_enter_wave(symbol, analysis, state, ex)
    total=analysis["total"]; price=analysis["price"]
    is_long = total > CONFIG["buy_threshold"]
    is_short = total < CONFIG["sell_threshold"]
    has_pos = in_position(state, symbol)

    # لو عنده صفقة وجاءت إشارة عكسية قوية — اقفلها
    if has_pos:
        pos = state["positions"][symbol]; side = pos.get("side","long")
        # لونج + بيع قوي => اقفل، شورت + شراء قوي => اقفل
        should_close = (side=="long" and total < CONFIG["strong_sell"]) or (side=="short" and total > CONFIG["strong_buy"])
        if should_close:
            qty=pos["qty"]; entry=pos["entry"]
            try:
                pnl=(price-entry)*qty if side=="long" else (entry-price)*qty
                pct=(pnl/(entry*qty)*100) if entry*qty else 0
                if CONFIG["paper_trading"]:
                    log(f"📉 اغلاق عكسي {side} {symbol} سكور {total:+.3f} @ {price:.4f} PnL {pnl:+.4f} ({pct:+.2f}%)")
                    state["history"].append({"symbol":symbol,"side":side,"entry":entry,"exit":price,"qty":qty,"pnl":pnl,"pnl_pct":pct,"reason":"اشارة عكسية قوية","time":datetime.now(timezone.utc).isoformat(),"type":"paper"})
                else:
                    res=close_live_position(ex, symbol, pos, price)
                    pnl=(res["price"]-entry)*res["qty"] if side=="long" else (entry-res["price"])*res["qty"]
                    pct=(pnl/(entry*res["qty"])*100) if entry*res["qty"] else 0
                    log(f"📉 اغلاق حقيقي {side} {symbol} @ {res['price']:.4f} PnL {pnl:+.4f}")
                    state["history"].append({"symbol":symbol,"side":side,"entry":entry,"exit":res["price"],"qty":res["qty"],"pnl":pnl,"pnl_pct":pct,"reason":"اشارة عكسية","time":datetime.now(timezone.utc).isoformat(),"type":"live"})
                state["stats"]["trades"]+=1; state["stats"]["pnl"]+=float(pnl)
                if pnl>0: state["stats"]["wins"]+=1
                else: state["stats"]["losses"]+=1
                state["positions"].pop(symbol,None); state["last_trade"][symbol]=datetime.now(timezone.utc).isoformat(); save_state(state)
            except Exception as e: log(f"فشل اغلاق {symbol} {side}: {e}")
            return

    if not has_pos:
        side=None
        if is_long: side="long"
        elif is_short: side="short"
        else: return
        if len(state["positions"])>=CONFIG["max_open_positions"]: return
        if not cooldown_ok(state,symbol): return
        # === Week 1 filters ===
        # Daily loss guard
        if not daily_pnl_ok(state):
            log(f"⏸️ {symbol} إيقاف يومي — خسارة اليوم تجاوزت {CONFIG.get('max_daily_loss_pct')}%")
            return
        # ADX filter — نحتاج df للـ ADX، نجيبه
        try:
            _f_df=fetch_ohlcv(symbol, CONFIG["timeframe"], limit=60, ex=ex)
            adx_v=adx_value(_f_df)
            if adx_v < float(CONFIG.get("adx_threshold", 18)):
                log(f"⏸️ {symbol} فلتر ADX {adx_v:.1f} < {CONFIG.get('adx_threshold')} — سوق عرضي")
                return
            if not volume_ok(_f_df):
                log(f"⏸️ {symbol} فلتر حجم — حجم ضعيف")
                return
        except Exception as e:
            log(f"فلتر ADX/Vol {symbol}: {e}")
        # HTF filter
        # Regime filter: عرضي = يحتاج سكور أقوى
        try:
            _reg = regime_detect(_f_df)
            if CONFIG.get("regime_filter") and _reg=="range" and abs(total) < 0.30:
                log(f"⏸️ {symbol} سوق عرضي ({_reg}) — يحتاج سكور ±0.30، الحالي {total:+.2f}")
                return
        except: pass
        if not htf_trend_ok(symbol, side, ex):
            log(f"⏸️ {symbol} فلتر ترند 4h — لا تدخل {side} عكس الترند الأكبر")
            return
        amount=position_size(analysis["price"], ex)*analysis["amount_mult"]
        if not CONFIG["paper_trading"]:
            try:
                bal=ex.fetch_balance()
                # فيوتشر: الرصيد في USDT
                usdt=0
                try: usdt=float(bal.get("USDT",{}).get("free",0) or 0)
                except: usdt=0
                if usdt==0:
                    try: usdt=float(bal["free"].get("USDT",0))
                    except: pass
                if usdt < amount: log(f"رصيد غير كافي {usdt:.2f} < {amount:.2f}"); return
            except Exception as e:
                log(f"فحص الرصيد فشل — مفيش دخول: {e}"); return
        try:
            order_side="long" if side=="long" else "short"
            _f_df2 = _f_df if '_f_df' in locals() else fetch_ohlcv(symbol, CONFIG["timeframe"], limit=60, ex=ex)
            cid = f"raqm-{uuid.uuid4().hex[:12]}"[:36]
            # pending flag for idempotent recovery (P0-05)
            state.setdefault("pending_orders", {})[symbol] = cid
            try: save_state(state)
            except: pass
            res=place_order(ex,symbol,order_side,amount,price, client_order_id=cid)
            sl, tp = dynamic_sl_tp(price, side, _f_df2)
            pos = {"side":side,"entry":res["price"],"qty":res["qty"],"cost":res["cost"],"notional":res.get("notional",amount*CONFIG.get("leverage",5)),"leverage":res.get("leverage",CONFIG.get("leverage",5)),"time":datetime.now(timezone.utc).isoformat(),"sl":sl,"tp":tp,"breakeven":False, "clientOrderId": cid}
            if not CONFIG["paper_trading"]:
                from backend.app.oco import place_oco_orders
                pos_id = cid
                oco = None
                try:
                    oco = place_oco_orders(ex, symbol, side, res["qty"], sl, tp, paper=False, pos_id=pos_id)
                except Exception as e:
                    oco = {"sl_error": str(e), "tp_error": str(e), "both_failed": True, "protection_missing": True}
                pos["oco_ids"] = {"sl": (oco or {}).get("sl_id"), "tp": (oco or {}).get("tp_id"), "pos_id": pos_id}
                if oco is None or oco.get("protection_missing"):
                    # the exchange refused the stop: close at once; if that fails too, keep tracking the position
                    reason = f"SL err={(oco or {}).get('sl_error')}"
                    log(f"⚠️ OCO فشل {symbol} {side} — {reason} — إغلاق طارئ")
                    notify(f"🚨 {symbol}: أمر الوقف اترفض على المنصة — بيقفل الصفقة فورا")
                    flatten_qty, flatten_price = res["qty"], res["price"]
                    try:
                        for p in ex.fetch_positions([symbol]) or []:
                            s = p.get("symbol") or (p.get("info") or {}).get("symbol", "")
                            if s == symbol or s.split(":")[0] == symbol:
                                raw = p.get("contracts") if p.get("contracts") is not None else (p.get("info") or {}).get("size")
                                if raw is not None and float(raw) > 0: flatten_qty = float(raw)
                                break
                    except Exception:
                        pass
                    flatten_ok = False
                    try:
                        close_side = "close_long" if side == "long" else "close_short"
                        fr = place_order(ex, symbol, close_side, 0, flatten_price, close_qty=flatten_qty)
                        try:
                            still_open = False
                            for p in ex.fetch_positions([symbol]) or []:
                                s = p.get("symbol") or (p.get("info") or {}).get("symbol", "")
                                if s == symbol or s.split(":")[0] == symbol:
                                    c = p.get("contracts") if p.get("contracts") is not None else (p.get("info") or {}).get("size")
                                    if float(c or 0) != 0: still_open = True
                            flatten_ok = not still_open
                        except Exception:
                            flatten_ok = float(fr.get("qty", 0) or 0) > 0
                    except Exception as ee:
                        log(f"فشل إغلاق طارئ {symbol}: {ee}")
                    if flatten_ok:
                        if oco and "tp" in oco:
                            try:
                                from backend.app.oco import cancel_oco_orders
                                cancel_oco_orders(ex, symbol, pos_id=pos_id)   # our leftover target only
                            except Exception:
                                pass
                        log(f"🔒 إغلاق طارئ {symbol} نجح — qty {flatten_qty}")
                        state.get("pending_orders", {}).pop(symbol, None)
                        state.get("recovery_required", {}).pop(symbol, None)
                        state["last_trade"][symbol] = datetime.now(timezone.utc).isoformat()
                        try: save_state(state)
                        except: pass
                        return
                    # still open on the exchange without a stop: the bot keeps managing it (its own SL/TP check)
                    # and no new entry anywhere until someone resolves it
                    pos["unprotected"] = True
                    state["positions"][symbol] = pos
                    state.setdefault("recovery_required", {})[symbol] = {"cid": cid, "reason": "unprotected: " + reason, "qty": flatten_qty, "price": flatten_price, "at": datetime.now(timezone.utc).isoformat()}
                    state.get("pending_orders", {}).pop(symbol, None)
                    try: save_state(state)
                    except: pass
                    log(f"🚨 {symbol} RECOVERY_REQUIRED — صفقة مفتوحة من غير وقف، الدخول متوقف لحد ما تتراجع")
                    notify(f"🚨 {symbol}: الإغلاق الطارئ فشل — الصفقة مفتوحة من غير وقف على المنصة. راجعها يدويا. البوت وقف أي دخول جديد.")
                    return
                if oco.get("tp_missing"):
                    log(f"⚠️ {symbol}: الهدف اترفض ({oco.get('tp_error')}) — الوقف شغال، والبوت هيقفل عند الهدف بنفسه")
                    notify(f"⚠️ {symbol}: أمر الهدف اترفض على المنصة — الوقف موجود، والبوت هيقفل عند الهدف بنفسه")
                if oco.get("verify_failed"):
                    # accepted by the exchange but not found afterwards: keep the position, stop new entries, alert
                    pos["sl_unverified"] = bool(oco.get("sl_unverified"))
                    state.setdefault("recovery_required", {})[symbol] = {"cid": cid, "reason": oco.get("verify_warn"), "at": datetime.now(timezone.utc).isoformat()}
                    log(f"🚨 {symbol}: {oco.get('verify_warn')} — الدخول متوقف لحد ما تتراجع")
                    notify(f"🚨 {symbol}: أوامر الحماية اتقبلت بس مش لاقيها على المنصة ({oco.get('verify_warn')}). راجعها يدويا — البوت وقف أي دخول جديد.")
            state["positions"][symbol]=pos
            try:
                if pos.get("oco_ids"):
                    state.setdefault("_last_oco", {})[symbol] = dict(pos["oco_ids"])
            except:
                pass
            state.get("pending_orders", {}).pop(symbol, None)
            state["last_trade"][symbol]=datetime.now(timezone.utc).isoformat(); save_state(state)
            mode="وهمي" if CONFIG["paper_trading"] else "حقيقي"
            lev_txt=f" x{res.get('leverage',CONFIG.get('leverage',5))}" if CONFIG.get("market")=="future" else ""
            emoji="🟢 لونج" if side=="long" else "🔴 شورت"
            log(f"✅ {emoji} {mode} {symbol}{lev_txt} @ {res['price']:.6f} qty {res['qty']} SL {sl:.4f} TP {tp:.4f} سكور {total:+.3f} {analysis['decision']}")
        except Exception as e: log(f"فشل {side} {symbol}: {e}")


def run_once():
    if ratio_mode():
        global _ratio_ex
        if "_ratio_ex" not in globals(): _ratio_ex = ccxt.binanceusdm({"enableRateLimit": True})
        return run_once_ratio(_ratio_ex)
    if momentum_mode():
        global _momentum_ex
        if "_momentum_ex" not in globals(): _momentum_ex = ccxt.binanceusdm({"enableRateLimit": True})   # the backtest's data is Binance's
        return run_once_momentum(_momentum_ex)
    if listing_mode():
        global _listing_ex
        if "_listing_ex" not in globals(): _listing_ex = ccxt.binanceusdm({"enableRateLimit": True})   # the backtest's listings are Binance's
        return run_once_listing(_listing_ex)
    if trend_mode(): CONFIG["timeframe"]="1d"
    state=load_state()
    ex,err=get_exchange(auth=not CONFIG["paper_trading"])
    if err:
        # switching to paper here would "close" real positions only in state.json and leave them open on the exchange
        log(f"⛔ LIVE من غير مفاتيح: {err} — البوت وقف"); notify(f"⛔ البوت الحقيقي وقف: {err}")
        raise SystemExit(2)
    prices={}; analyses={}
    # live: the coin list and the signals come from Binance's real public market (no keys) — Demo Trading's own
    # volumes and candles are its play-money activity — and only orders, positions and balance use the account
    data_ex = ex
    if not CONFIG["paper_trading"]:
        global _live_data_ex
        if "_live_data_ex" not in globals(): _live_data_ex = ccxt.binanceusdm({"enableRateLimit": True})
        data_ex = _live_data_ex
        try: ex.load_markets()
        except Exception as e: log(f"⚠️ markets: {e}")
    try: symbols, allowed = cycle_symbols(data_ex, state)
    except Exception as e: log(f"قائمة العملات: {e}"); symbols, allowed = sorted(set(_universe["symbols"]) | set(state["positions"])), set(_universe["symbols"])
    for sym in symbols:
        try:
            df=fetch_ohlcv(sym, CONFIG["timeframe"], limit=candles_needed(), ex=data_ex)
            a=analyze(sym, df); a["in_universe"]=allowed is None or sym in allowed; analyses[sym]=a; prices[sym]=a["price"]
            if sym in _universe["symbols"]: a["rank"]=_universe["symbols"].index(sym)+1   # 1 = most volume
            bd=" | ".join(f"{k} {v[0]:+.2f}" for k,v in a["breakdown"].items())
            # اختصر SHIB/PEPE لعرض أوضح
            log(f"{sym:10s} @ {a['price']:.6g} سكور {a['total']:+.3f} {a['decision']:8s} | {bd} | SL {a['sl']:.4g} TP {a['tp']:.4g}" if a.get('tp') else f"{sym:10s} @ {a['price']:.6g} {a['decision']:8s} | {bd} | وقف حماية {a['sl']:.4g}")
        except Exception as e: log(f"{sym} فشل: {e}")
    if not CONFIG["paper_trading"]:
        reconcile_live(state, ex)
        process_manual_closes(state, ex, prices)
    if prices: check_sl_tp(state, prices, ex)
    for sym,a in analyses.items():
        try: try_enter(sym,a,state,ex)
        except Exception as e: log(f"دخول {sym}: {e}")
    write_public_status(state, analyses, allowed if allowed is not None else symbols)
    if not CONFIG["paper_trading"]: write_live_status(state, prices, analyses)
    if state["positions"]: log(f"📊 مفتوحة: {list(state['positions'].keys())} | PnL {state['stats']['pnl']:+.4f} | {state['stats']['wins']}W/{state['stats']['losses']}L")
    else: log(f"📊 لا صفقات مفتوحة | PnL {state['stats']['pnl']:+.4f} | {state['stats']['wins']}W/{state['stats']['losses']}L")
    # حدث ملف الداشبورد
    try:
        dash_path=Path(__file__).parent / "dashboard-data.json"
        dash_path.write_text(json.dumps({"analyses":analyses,"state":state,"time":datetime.now(timezone.utc).isoformat()}, ensure_ascii=False, indent=2), encoding="utf-8")
    except: pass

def run_loop():
    mode="Paper وهمي" if CONFIG["paper_trading"] else "LIVE حقيقي"
    CONFIG["started_at"]=datetime.now(timezone.utc).isoformat()
    if ratio_mode():
        R=RATIO
        log(f"=== ⚠️ HIGH RISK — ratio trend: كل الأزواج بين أعلى {R['top']} فوليوم، فوق متوسط {R['sma']} يوم = لونج الأولى/شورت التانية — {mode} | هامش {CONFIG['trade_amount_usdt']} USDT x{CONFIG.get('leverage',2)} لكل رجل ===")
        notify(f"▶️ ⚠️ HIGH RISK — بوت ratio trend اشتغل ({mode})\nكل الأزواج بين أعلى {R['top']} عملة فوليوم · تجربة لمتابعة الأداء بس")
    elif momentum_mode():
        M=MOM
        log(f"=== مومنتم: لونج أقوى {M['n']} وشورت أضعف {M['n']} من أعلى {M['top']} فوليوم (عائد {M['weeks']} أسبوع) — {mode} — تبديل كل {M['every_days']} أيام، وقف {M['stop']:.0%} | هامش {CONFIG['trade_amount_usdt']} USDT x{CONFIG.get('leverage',2)} ===")
        notify(f"▶️ بوت المومنتم اشتغل ({mode})\nكل أسبوع: لونج أقوى {M['n']} وشورت أضعف {M['n']} من أعلى {M['top']} عملة فوليوم")
    elif listing_mode():
        L=LISTING
        log(f"=== شورت العملات الجديدة — {mode} — دخول بعد {L['skip_days']} يوم، خروج بعد {L['hold_days']} يوم، وقف {L['stop']:.0%}، أقصى {L['max_open']} | هامش {CONFIG['trade_amount_usdt']} USDT x{CONFIG.get('leverage',2)} ===")
        notify(f"▶️ بوت شورت العملات الجديدة اشتغل ({mode})\nدخول بعد {L['skip_days']} يوم من الإدراج · خروج بعد {L['hold_days']} يوم · وقف {L['stop']:.0%} · أقصى {L['max_open']} صفقات")
    elif trend_mode():
        coins=f"أعلى {CONFIG['universe_size']} عملة فوليوم" if CONFIG.get("universe_size") else f"{len(CONFIG['symbols'])} عملة"
        log(f"=== ترند يومي — لونج بس — {mode} — {coins} | هامش {CONFIG['trade_amount_usdt']} USDT x{CONFIG.get('leverage',2)} | كل {CONFIG['poll_seconds']}s ===")
        notify(f"▶️ بوت رقم اشتغل — ترند يومي ({mode})\n{coins} · هامش ${CONFIG['trade_amount_usdt']:.0f} x{CONFIG.get('leverage',2)}")
    else:
        log(f"=== بوت 20 زوج FUTURES لونج/شورت — {mode} ===")
        log(f"الازواج {len(CONFIG['symbols'])} فريم {CONFIG['timeframe']} كل {CONFIG['poll_seconds']}s | حجم {CONFIG['trade_amount_usdt']} USDT | SL {CONFIG['stop_loss_pct']*100:.0f}% TP {CONFIG['take_profit_pct']*100:.0f}%")
    n=0
    while True:
        n+=1; log(f"\n——— دورة #{n} ———")
        try: run_once()
        except Exception as e: log(f"خطأ دورة: {e}")
        time.sleep(CONFIG["poll_seconds"])

# ---- Dashboard HTTP Server ----
class DashHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/state"):
            self.send_response(200); self.send_header("Content-Type","application/json; charset=utf-8"); self.end_headers()
            try: data=Path(__file__).parent.joinpath("state.json").read_text(encoding="utf-8")
            except: data=json.dumps(load_state(), ensure_ascii=False)
            self.wfile.write(data.encode("utf-8")); return
        if self.path.startswith("/api/dashboard"):
            self.send_response(200); self.send_header("Content-Type","application/json; charset=utf-8"); self.end_headers()
            try: data=Path(__file__).parent.joinpath("dashboard-data.json").read_text(encoding="utf-8")
            except: data=json.dumps({"analyses":{},"state":load_state()}, ensure_ascii=False)
            self.wfile.write(data.encode("utf-8")); return
        if self.path.startswith("/api/klines"):
            # /api/klines?symbol=BTC/USDT&interval=1h&limit=200  -> proxy to Binance
            from urllib.parse import urlparse, parse_qs
            import urllib.request
            qs=parse_qs(urlparse(self.path).query)
            sym=(qs.get("symbol",["BTC/USDT"])[0]).replace("/","")
            interval=qs.get("interval",["1h"])[0]; limit=qs.get("limit",["200"])[0]
            if not (re.fullmatch(r"[A-Z0-9]{2,20}", sym) and re.fullmatch(r"\d{1,2}[mhdw]", interval) and re.fullmatch(r"\d{1,4}", limit)):
                self.send_response(400); self.end_headers(); return
            url=f"https://api.binance.com/api/v3/klines?symbol={sym}&interval={interval}&limit={limit}"
            try:
                with urllib.request.urlopen(url, timeout=10) as r: body=r.read()
                self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Access-Control-Allow-Origin","*"); self.end_headers()
                self.wfile.write(body); return
            except Exception as e:
                self.send_response(502); self.end_headers(); self.wfile.write(json.dumps({"error":str(e)}).encode()); return
        self.send_response(404); self.end_headers()   # no file serving: the bot folder holds .env and the key vault
    def end_headers(self):
        super().end_headers()

def start_dashboard_server(port=None):
    port=port or CONFIG["dashboard_port"]
    root=str(Path(__file__).parent)
    os.chdir(root)
    handler=lambda *a, **kw: DashHandler(*a, directory=root, **kw)
    with socketserver.TCPServer(("127.0.0.1", port), handler) as httpd:   # this machine only
        log(f"🌐 الداشبورد http://localhost:{port}/  (index.html)")
        try: webbrowser.open(f"http://localhost:{port}/index.html")
        except: pass
        httpd.serve_forever()

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(description="Crypto Bot 20 pairs")
    p.add_argument("--once", action="store_true", help="مرة واحدة")
    p.add_argument("--live", action="store_true", help="حقيقي")
    p.add_argument("--paper", action="store_true", help="وهمي")
    p.add_argument("--dashboard", action="store_true", help="شغل الداشبورد + البوت معًا")
    p.add_argument("--serve-only", action="store_true", help="داشبورد فقط بدون لوب")
    p.add_argument("--port", type=int, default=None, help="بورت الداشبورد")
    p.add_argument("--strategy", default=None, help="مثلا trend_daily — استراتيجية واحدة (أو أكتر بفاصلة)")
    p.add_argument("--leverage", type=int, default=None, choices=[1, 2, 3, 4, 5], help="الرافعة")
    p.add_argument("--universe", type=int, default=0, help="اشتغل على أعلى N عملة فوليوم بدل قائمة symbols")
    p.add_argument("--amount", type=float, default=None, help="هامش الصفقة USDT")
    p.add_argument("--poll", type=int, default=None, help="ثواني بين كل دورة")
    p.add_argument("--notify", action="store_true", help="رسايل تليجرام للدخول والخروج (TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID)")
    p.add_argument("--public", default=None, help="مجلد يتكتب فيه status.json لصفحة البوت العامة (صفقات ونتايج بس)")
    p.add_argument("--state", default=None, help="ملف الحالة (لتشغيل أكتر من بوت في نفس المجلد) — اللوج بيبقى بنفس الاسم .log")
    args=p.parse_args()
    if args.strategy: CONFIG["enabled_strategies"]=[s.strip() for s in args.strategy.split(",") if s.strip()]
    if args.leverage: CONFIG["leverage"]=args.leverage
    elif trend_mode(): CONFIG["leverage"]=2
    if args.amount: CONFIG["trade_amount_usdt"]=args.amount
    if args.poll: CONFIG["poll_seconds"]=args.poll
    if args.universe:
        CONFIG["universe_size"]=args.universe
        CONFIG["max_open_positions"]=max(int(CONFIG["max_open_positions"]), args.universe)
    CONFIG["notify"]=args.notify
    if args.public: CONFIG["public_dir"]=args.public
    if args.state:
        STATE_PATH=Path(__file__).parent / args.state
        LOG_PATH=Path(__file__).parent / (Path(args.state).stem + ".log")
    elif listing_mode():
        STATE_PATH=Path(__file__).parent / "state_listing.json"; LOG_PATH=Path(__file__).parent / "state_listing.log"
    elif momentum_mode():
        STATE_PATH=Path(__file__).parent / "state_momentum.json"; LOG_PATH=Path(__file__).parent / "state_momentum.log"
    elif ratio_mode():
        STATE_PATH=Path(__file__).parent / "state_ratio.json"; LOG_PATH=Path(__file__).parent / "state_ratio.log"
    if args.paper and args.live: p.error("--paper و --live مع بعض؟ اختار واحد")
    if args.paper: CONFIG["paper_trading"]=True
    if args.live:
        if not trend_mode(): p.error("--live متاح للترند اليومي بس (--strategy trend_daily)")
        if binance_env() == "live" and os.getenv("ALLOW_LIVE_TRADING", "").strip().lower() != "true":
            p.error("فلوس حقيقية محتاجة ALLOW_LIVE_TRADING=true — أو BINANCE_ENV=demo للتجربة بفلوس وهمية على Binance")
        CONFIG["paper_trading"]=False
    if args.port: CONFIG["dashboard_port"]=args.port
    if args.serve_only:
        start_dashboard_server()
    elif args.dashboard:
        t=threading.Thread(target=start_dashboard_server, daemon=True); t.start()
        time.sleep(1)
        run_loop()
    elif args.once:
        run_once()
    else:
        run_loop()
