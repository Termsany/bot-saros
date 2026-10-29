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
from backend.app.execution_safety import AmbiguousFill, authoritative_position_state, futures_net_pnl, linear_contracts_from_margin, normalize_filled_contracts
from backend.app import risk_manager as riskmgr
from backend.app.multi_leg_execution import MultiLegExecutionEngine
from backend.app import live_activation

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
RISK_PATH  = Path(__file__).parent / "risk_state.json"   # shared Central Risk Manager ledger across ALL strategy processes
ACTIVATION_PATH = Path(__file__).parent / "live_activation.sqlite3"

# These strategies route real orders through the same proven primitives (place_order + OCO stop/TP,
# risk_manager.pre_trade_gate/register_open_risk, reconcile_live, close_live_position/check_sl_tp):
# single-leg ones via _single_leg_live_entry/_single_leg_live_exit (or try_enter_trend for trend_daily),
# multi-leg ones via the durable basket engine (_phase2_live_basket). --live is gated on this list,
# not on a single hardcoded strategy name. All seven passed end to end on Binance Demo (PR #16, scripts/demo_e2e.py).
LIVE_READY_STRATEGIES = {"trend_daily", "vol_breakout", "rsi2_pullback",
                          "trend_breakout", "listing_short", "momentum_ls", "ratio_trend"}
# Dropped by the owner on 2026-10-29: refused by --strategy, paper or live. "ict" is the default indicator
# ensemble — the dashboard's paper loop still uses it, it just can't be run as a bot of its own.
RETIRED_STRATEGIES = {"ict", "wave_flats"}

# Crude correlation grouping for the correlated-risk cap: nearly every altcoin trades as
# BTC-beta, so "majors" vs "alts" is the conservative default until a real correlation
# matrix is computed. Override via CONFIG["correlation_groups"] = {symbol: group}.
_CORRELATION_MAJORS = {"BTC/USDT", "ETH/USDT"}


def _correlation_group(symbol):
    override = (CONFIG.get("correlation_groups") or {}).get(symbol)
    if override:
        return override
    base = symbol.split(":")[0]
    return "majors" if base in _CORRELATION_MAJORS else "alts"


def _current_strategy_name():
    if trend_mode(): return "trend_daily"
    if wave_mode(): return "wave_flats"
    if listing_mode(): return "listing_short"
    if momentum_mode(): return "momentum_ls"
    if ratio_mode(): return "ratio_trend"
    if breakout_mode(): return "vol_breakout"
    if rsi2_mode(): return "rsi2_pullback"
    if tbreak_mode(): return "trend_breakout"
    enabled = CONFIG.get("enabled_strategies") or []
    return enabled[0] if enabled else "default"


def _live_activation_gate(strategy):
    if binance_env() != "live":
        return True, None
    account = os.getenv("BINANCE_LIVE_ACCOUNT", "").strip()
    return live_activation.live_activation_allowed(ACTIVATION_PATH, strategy=strategy, account=account)


def _fetch_equity_usdt(ex):
    """Best-effort USDT account equity (free + used margin); None means unavailable —
    callers must fail closed on None, never substitute a guessed figure."""
    try:
        bal = ex.fetch_balance()
        usdt = bal.get("USDT") or {}
        total = usdt.get("total")
        if total is None:
            free = float(usdt.get("free") or (bal.get("free") or {}).get("USDT") or 0)
            used = float(usdt.get("used") or (bal.get("used") or {}).get("USDT") or 0)
            total = free + used
        total = float(total)
        return total if total > 0 else None
    except Exception:
        return None


def _estimate_trade_risk_usdt(margin_usdt, leverage, entry_price, sl_price):
    """Worst-case loss to the stop for a new position, used by the pre-trade risk gate.
    Returns None (fail closed) if the stop price is unknown — an entry with no stop has
    unbounded risk and must never pass the gate."""
    try:
        if sl_price is None or entry_price is None or float(entry_price) <= 0:
            return None
        notional = float(margin_usdt) * max(1, int(leverage or 1))
        base_qty = notional / float(entry_price)
        return abs(float(entry_price) - float(sl_price)) * base_qty
    except (TypeError, ValueError):
        return None

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
        if ex.id != "bybit":   # Binance: coins only (it also lists index / TradFi perpetuals); Bybit says contractType "LinearPerpetual"
            crypto = crypto and info.get("underlyingType", "COIN") == "COIN" and info.get("contractType", "PERPETUAL") == "PERPETUAL"
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

def _resolve_live_symbol(ex, symbol):
    """CONFIG['symbols'] (trend_daily/wave_flats/ict's fixed list) is written in the bare 'BTC/USDT'
    form; Binance USDT-M futures' real ccxt market key is 'BTC/USDT:USDT'. ex.market()/create_order()
    require the exact key and raise 'does not have market symbol' on the bare form — only fetch_ohlcv
    tolerates it. The volume-ranked strategies (vol_breakout/rsi2_pullback/trend_breakout/momentum_ls/
    ratio_trend/listing_short) build their symbol lists FROM ex.fetch_tickers()/ex.markets already, so
    they're unaffected; this only matters for the fixed-list strategies' live path."""
    if symbol in ex.markets: return symbol
    quote = symbol.split("/")[-1] if "/" in symbol else ""
    resolved = f"{symbol}:{quote}"
    return resolved if resolved in ex.markets else symbol

def _resolve_live_symbols(ex, symbols, allowed):
    if not symbols: return symbols, allowed
    resolved = [_resolve_live_symbol(ex, s) for s in symbols]
    resolved_allowed = None if allowed is None else {_resolve_live_symbol(ex, s) for s in allowed}
    return resolved, resolved_allowed

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
        cs = _position_contract_size(pos)
        if cs is None:
            pnl = None
            margin = None
        else:
            funding = _funding_pnl(pos)
            fee = _fee_rate(pos)
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
    return pnl

def run_once_listing(ex):
    L = LISTING; state = load_state(); now = datetime.now(timezone.utc)
    if not CONFIG["paper_trading"]:
        reconcile_live(state, ex)
        if _ENTRY_BLOCK.get("reason"):
            save_state(state); return
    process_paper_closes(state, ex, "listing")
    done = state.setdefault("listing_done", {})
    mk = listing_markets(ex); prices = {}
    # open shorts: protective stop and the 90-day exit
    for sym, pos in list(state["positions"].items()):
        try:
            price = float(ex.fetch_ticker(sym)["last"]); prices[sym] = price
            reason = f"وقف {pos['sl']:.6g}" if price >= pos["sl"] else f"خلصت {L['hold_days']} يوم" if now >= datetime.fromisoformat(pos["exit_at"]) else None
            if reason:
                if CONFIG["paper_trading"]:
                    _listing_close(ex, state, sym, price, reason)
                else:
                    leg = {"symbol": sym, "side": "close_short", "action": "exit", "position": pos, "price": price, "order": 0,
                           "risk_usdt": 0, "notional_usdt": 0, "correlation_group": _correlation_group(sym)}
                    result = _phase2_live_basket(ex, state, "listing_short", f"listing-exit:{sym}", [leg], reserve=False)
                    if result and result.get("status") == "filled": state["history"].append({"symbol": sym, "side": "short", "entry": pos["entry"], "exit": price, "qty": pos["qty"], "pnl": 0.0, "reason": reason, "time": now.isoformat(), "type": "live"})
        except Exception as e: log(f"شورت {sym}: {e}")
    # new entries: coins that just turned 30 days old (a few days of slack if the bot was down), oldest listing first;
    # like the backtest, a coin that comes up while all 10 slots are taken is skipped for good
    due = sorted([x for x in mk if L["skip_days"] <= x[2] < L["skip_days"] + L["catch_up_days"] and x[0] not in done], key=lambda x: x[1])
    for sym, listed, age in due:
        done[sym] = now.isoformat()
        if len(state["positions"]) >= L["max_open"]:
            log(f"⏸️ {sym} عدّى {L['skip_days']} يوم بس الـ {L['max_open']} أماكن مليانة — اتساب زي الباك تست"); continue
        if not CONFIG["paper_trading"]:
            try:
                price = float(ex.fetch_ticker(sym)["last"]); prices[sym] = price
            except Exception as e:
                log(f"شورت {sym}: {e}"); continue
            leg = _phase2_leg(sym, "short", position_size(price), price, price * (1 + L["stop"]), None, "listing_short",
                               extra={"listed": datetime.fromtimestamp(listed / 1000, timezone.utc).isoformat(), "exit_at": (now + pd.Timedelta(days=L["hold_days"])).isoformat()})
            result = _phase2_live_basket(ex, state, "listing_short", f"listing-entry:{sym}", [leg])
            if result and result.get("status") == "filled": done[sym] = now.isoformat()
            continue

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
    if not CONFIG["paper_trading"]:
        reconcile_live(state, ex)
        if _ENTRY_BLOCK.get("reason"):
            save_state(state); return
    process_paper_closes(state, ex, "momentum")
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
            lev = int(CONFIG.get("leverage", 2)); picks = [(s, r, "short") for s, r in ranked[:M["n"]]] + [(s, r, "long") for s, r in ranked[-M["n"]:]]
            if not CONFIG["paper_trading"]:
                exits = []
                for sym in sorted(state["positions"]):
                    px = float(ex.fetch_ticker(sym)["last"]); pos = state["positions"][sym]
                    exits.append({"symbol": sym, "side": "close_" + pos["side"], "action": "exit", "position": pos, "price": px, "order": 0,
                                  "risk_usdt": 0, "notional_usdt": 0, "correlation_group": _correlation_group(sym)})
                if exits:
                    closed_result = _phase2_live_basket(ex, state, "momentum_ls", "momentum-rebalance-exit", exits, reserve=False)
                    if not closed_result or closed_result.get("status") != "filled":
                        save_state(state); return
                entries = []
                for sym, ret, side in picks:
                    px = float(ex.fetch_ticker(sym)["last"]); prices[sym] = px
                    stop = px * (1 + M["stop"]) if side == "short" else px * (1 - M["stop"])
                    entries.append(_phase2_leg(sym, side, position_size(px), px, stop, None, "momentum_ls", extra={"ret": ret}))
                result = _phase2_live_basket(ex, state, "momentum_ls", "momentum-rebalance-entry", entries)
                if result and result.get("status") == "filled":
                    state["mom_last"] = today.isoformat(); state["mom_ranking"] = [{"symbol": s.split(":")[0], "ret": round(r * 100, 1)} for s, r in ranked]; save_state(state)
                return
            for sym in list(state["positions"]):
                try:
                    price = float(ex.fetch_ticker(sym)["last"]); closed += _paper_close(ex, state, sym, price, "تبديل أسبوعي")
                except Exception as e: log(f"قفل {sym}: {e}")
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
    if not CONFIG["paper_trading"]:
        reconcile_live(state, ex)
        if _ENTRY_BLOCK.get("reason"):
            save_state(state); return
    process_paper_closes(state, ex, "ratio")
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
            if CONFIG["paper_trading"] and key not in wanted: closed += _ratio_close_pair(ex, state, key, prices, "عملة خرجت من القائمة", fcache)
        if not CONFIG["paper_trading"]:
            # Live pairs are always opened and closed through one durable basket intent.
            exits = []
            for key, pair in list(state["pairs"].items()):
                if key not in wanted:
                    for leg in pair["legs"]:
                        exits.append({"symbol": leg["sym"], "side": "close_" + leg["side"], "action": "exit", "position": state["positions"].get(leg["sym"], leg),
                                      "price": float(ex.fetch_ticker(leg["sym"])["last"]), "order": len(exits), "risk_usdt": 0, "notional_usdt": 0,
                                      "correlation_group": _correlation_group(leg["sym"])})
            if exits:
                result = _phase2_live_basket(ex, state, "ratio_trend", "ratio-rebalance-exit", exits, reserve=False)
                if not result or result.get("status") != "filled":
                    save_state(state); return
                for key in list(state["pairs"]):
                    if key not in wanted: state["pairs"].pop(key, None)
            for key in sorted(wanted):
                a, b = key.split("|")
                try: sig = ratio_signal(ex, a, b, cache)
                except Exception as e: log(f"ratio {key}: {e}"); continue
                cur = state["pairs"].get(key)
                if not sig or (cur and cur["sign"] == sig): continue
                if cur:
                    legs_out = []
                    for leg in cur["legs"]:
                        legs_out.append({"symbol": leg["sym"], "side": "close_" + leg["side"], "action": "exit", "position": state["positions"].get(leg["sym"], leg),
                                         "price": float(ex.fetch_ticker(leg["sym"])["last"]), "order": len(legs_out), "risk_usdt": 0, "notional_usdt": 0,
                                         "correlation_group": _correlation_group(leg["sym"])})
                    result = _phase2_live_basket(ex, state, "ratio_trend", f"ratio-flip-exit:{key}", legs_out, reserve=False)
                    if not result or result.get("status") != "filled": save_state(state); return
                    state["pairs"].pop(key, None)
                ordered = ((a, "long"), (b, "short")) if sig == 1 else ((b, "long"), (a, "short"))
                new_legs = []
                for i, (sym, side) in enumerate(ordered):
                    px = float(ex.fetch_ticker(sym)["last"]); prices[sym] = px
                    new_legs.append(_phase2_leg(sym, side, position_size(px), px, px * (1 - 0.40) if side == "long" else px * (1 + 0.40), None, "ratio_trend", i))
                result = _phase2_live_basket(ex, state, "ratio_trend", f"ratio-entry:{key}", new_legs)
                if not result or result.get("status") != "filled": continue
                state["pairs"][key] = {"sign": sig, "time": now.isoformat(), "legs": [{"sym": l["symbol"], "side": l["side"], "entry": state["positions"][l["symbol"]]["entry"], "qty": state["positions"][l["symbol"]]["qty"]} for l in new_legs], "ranks": [(state.get("ratio_rank") or {}).get(a), (state.get("ratio_rank") or {}).get(b)]}
            state["ratio_day"] = today.isoformat(); save_state(state); return
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

def position_size(price, ex=None, stop_price=None):
    """Return quote margin; percent-risk mode targets configured worst-case stop loss."""
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
        if stop_price is None or float(stop_price) <= 0 or float(price) <= 0:
            return base
        stop_pct=abs(float(price)-float(stop_price))/float(price)
        if stop_pct <= 0:
            return base
        lev=max(1, int(CONFIG.get("leverage", 1)))
        return (usdt * risk) / (stop_pct * lev)
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
            if not CONFIG.get("paper_trading"):
                for symbol, pos in data["positions"].items():
                    # contract_size_verified and entry_fee_rate are set at ENTRY time (every live entry
                    # path writes them) — missing them means genuinely pre-verification legacy state.
                    # funding_verified is deliberately close-only (set exclusively by
                    # _refresh_funding_evidence when a position is closed, never at entry) — requiring
                    # it here would flag every freshly-opened, perfectly healthy live position as
                    # needing recovery on every single restart, for any of the 9 strategies. PnL
                    # accounting still fails closed on missing funding evidence at close time via
                    # _funding_pnl(required=True); this load-time gate must not duplicate that check.
                    if pos.get("type") == "paper" or pos.get("contract_size_verified") is not True or pos.get("entry_fee_rate") is None:
                        data["recovery_required"].setdefault(symbol, {"reason": "legacy live position lacks verified contract or fee metadata", "at": datetime.now(timezone.utc).isoformat()})
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

def _fetch_order_by_cid(ex, cid, symbol):
    """Look an order up by OUR client id. Binance needs origClientOrderId for that — without it ccxt sends the id as the
    exchange's orderId and never finds the order. (Exchanges / test fakes without params fall back to the plain call.)"""
    try:
        return ex.fetch_order(cid, symbol, {"origClientOrderId": cid})
    except TypeError:
        return ex.fetch_order(cid, symbol)


def _reconcile_fills_by_client_id(ex, symbol, cid):
    for fn in ("fetch_order", "fetch_open_orders", "fetch_closed_orders", "fetch_orders"):
        try:
            if fn == "fetch_order":
                try:
                    o = _fetch_order_by_cid(ex, cid, symbol)
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


def _persist_sl_recovery(state, symbol, pos, reason, *, status="recovery"):
    """Put the position's protective-order ownership and recovery reason into the state object,
    then cross a real durable persistence boundary. The caller must treat any exception as a hard
    stop: no old-stop cancellation or further protection mutation is safe until this succeeds."""
    if state is None:
        raise RuntimeError("SL replacement requires a state object for durable recovery")
    state.setdefault("positions", {})[symbol] = pos
    state.setdefault("recovery_required", {})[symbol] = {
        "reason": str(reason), "sl_sync": status,
        "oco_ids": dict(pos.get("oco_ids") or {}),
        "at": datetime.now(timezone.utc).isoformat(),
    }
    state.setdefault("_entry_block", {})["reason"] = "SL replacement recovery required"
    _ENTRY_BLOCK["reason"] = "SL replacement recovery required"
    save_state(state)


def _persist_sl_boundary(state, symbol, pos):
    """Persist ownership before cancellation. No persistence means no destructive next step."""
    if state is None:
        raise RuntimeError("SL replacement persistence boundary is unavailable")
    state.setdefault("positions", {})[symbol] = pos
    save_state(state)


def _mark_sl_recovery(state, symbol, pos, reason, *, status="recovery"):
    pos["sl_unverified"] = True
    pos["sl_sync"] = status
    _SL_AMEND_FAILED.add(symbol)
    try:
        _persist_sl_recovery(state, symbol, pos, reason, status=status)
    except Exception as persist_error:
        # Keep the complete ownership graph in memory and block changes even if the disk write itself
        # failed; the caller's state object remains the recovery handoff for the next retry.
        _ENTRY_BLOCK["reason"] = "SL replacement persistence failed; manual recovery required"
        log(f"SL recovery persistence failed {symbol}: {persist_error}")
    return False


def _retain_unverified_replacement(state, symbol, pos, replacement_id, reason, ex):
    """Persist an unverified replacement before trying to clean it up. If cleanup is ambiguous,
    keep its id in restart-safe recovery tracking rather than orphaning the live order."""
    if replacement_id:
        pos.setdefault("oco_ids", {})["sl_pending_cleanup"] = {
            "id": replacement_id, "pos_id": (pos.get("oco_ids") or {}).get("pos_id"),
            "role": "sl", "side": pos.get("side", "long"), "status": "pending_cleanup",
            "since": datetime.now(timezone.utc).isoformat(),
        }
    try:
        _persist_sl_recovery(state, symbol, pos, reason, status="pending_cleanup")
    except Exception:
        return _mark_sl_recovery(state, symbol, pos, reason, status="pending_cleanup")
    if replacement_id:
        try:
            from backend.app.oco import cancel_oco_orders
            cancelled = cancel_oco_orders(ex, symbol, sl_id=replacement_id)
        except Exception:
            cancelled = False
        if cancelled is False:
            return _mark_sl_recovery(state, symbol, pos, reason, status="pending_cleanup")
        pos["oco_ids"].pop("sl_pending_cleanup", None)
        try:
            state.setdefault("recovery_required", {}).pop(symbol, None)
            save_state(state)
        except Exception:
            return _mark_sl_recovery(state, symbol, pos, reason, status="pending_cleanup")
    return _mark_sl_recovery(state, symbol, pos, reason, status="recovery")


def _amend_exchange_sl(symbol, pos, new_sl, old_sl, ex, state=None):
    # Try to move the exchange SL to new_sl. Returns True if verified and durably tracked,
    # False if protection/recovery must remain blocked. state is required for replacement mode.
    if CONFIG.get("paper_trading"):
        return True
    if new_sl is None or old_sl is None or new_sl == old_sl:
        return True
    oco = pos.get("oco_ids") or {}
    if ex is not None and hasattr(ex, "edit_order") and oco.get("sl"):
        try:
            edited = ex.edit_order(oco["sl"], symbol, "market", "sell" if pos.get("side","long")=="long" else "buy", pos.get("qty"), price=None, params={"stopLossPrice": float(new_sl)})
            oid = (edited or {}).get("id") or oco["sl"]
            verified = ex.fetch_order(oid, symbol)
            info = verified.get("info") or {}
            actual_trigger = verified.get("stopLossPrice") or verified.get("triggerPrice") or info.get("stopLossPrice") or info.get("triggerPrice")
            if (verified.get("status") or "open") not in ("open", "new") or actual_trigger is None or abs(float(actual_trigger) - float(new_sl)) > max(1e-8, abs(float(new_sl)) * 1e-8):
                raise RuntimeError("exchange returned an unverified stop amendment")
            pos["sl_sync"] = "amended"
            pos.pop("sl_unverified", None)
            return True
        except Exception as e:
            log(f"SL amend edit_order failed {symbol}: {e}")
    if ex is not None and oco.get("pos_id"):
        try:
            from backend.app.oco import cancel_oco_orders, place_oco_orders
            # Old protection remains active until the replacement is verified.
            side = pos.get("side","long")
            qty = pos.get("qty")
            close_side = "sell" if side == "long" else "buy"
            # A replacement cannot safely be created without a state object that can durably own it.
            if state is None:
                raise RuntimeError("replacement SL requires durable state persistence")
            replacement_id = f"{oco['pos_id']}-amend-{uuid.uuid4().hex[:8]}"
            oco2 = place_oco_orders(ex, symbol, side, qty, new_sl, None, paper=False, pos_id=replacement_id)
            replacement_sl_id = oco2.get("sl_id") if isinstance(oco2, dict) else None
            if not replacement_sl_id:
                raise RuntimeError("replacement stop was not accepted by the exchange")
            if oco2.get("sl_error") or oco2.get("sl_unverified") or oco2.get("verify_failed"):
                return _retain_unverified_replacement(state, symbol, pos, replacement_sl_id,
                    "replacement stop exchange readback was incomplete", ex)
            ok, why = _verify_protective_stop(ex, symbol, oco2.get("sl"), new_sl, close_side, qty)
            if not ok:
                return _retain_unverified_replacement(state, symbol, pos, replacement_sl_id,
                    f"replacement stop failed authoritative field verification: {why}", ex)
            old_sl_id = oco.get("sl")
            # Cross the durable ownership boundary BEFORE touching the old stop. If this write fails,
            # no cancellation is attempted and both live protections remain active.
            pos["oco_ids"] = {"sl": replacement_sl_id, "tp": oco.get("tp"), "pos_id": oco.get("pos_id")}
            if old_sl_id and old_sl_id != replacement_sl_id:
                pos["oco_ids"]["sl_pending_cancel"] = {
                    "id": old_sl_id, "pos_id": oco.get("pos_id"), "role": "sl", "side": side,
                    "status": "pending_cancel", "since": datetime.now(timezone.utc).isoformat(),
                }
            try:
                _persist_sl_boundary(state, symbol, pos)
            except Exception as persist_error:
                return _mark_sl_recovery(state, symbol, pos,
                    f"replacement SL ownership persistence failed before old-stop cancellation: {persist_error}",
                    status="awaiting_persistence")
            if old_sl_id:
                cancelled = cancel_oco_orders(ex, symbol, sl_id=old_sl_id)
                if cancelled is False:
                    # Both ids were durably recorded before this attempt; keep the old pending id.
                    pos["sl_unverified"] = True
                    pos["sl_sync"] = "pending_cancel"
                    try:
                        _persist_sl_recovery(state, symbol, pos, "old SL cancellation is ambiguous", status="pending_cancel")
                    except Exception:
                        pass
                    return False
                pos["oco_ids"].pop("sl_pending_cancel", None)
                try:
                    _persist_sl_boundary(state, symbol, pos)
                except Exception as persist_error:
                    # The old stop is already confirmed absent, but durable state still retains the
                    # conservative pending id from the previous boundary until this write succeeds.
                    pos["oco_ids"]["sl_pending_cancel"] = {"id": old_sl_id, "pos_id": oco.get("pos_id"),
                        "role": "sl", "side": side, "status": "cancelled_unpersisted", "since": datetime.now(timezone.utc).isoformat()}
                    return _mark_sl_recovery(state, symbol, pos,
                        f"replacement SL final persistence failed: {persist_error}", status="awaiting_persistence")
            pos["sl_sync"] = "amended"
            pos.pop("sl_unverified", None)
            return True
        except Exception as e:
            log(f"SL amend recreate exception {symbol}: {e}")
    _SL_AMEND_FAILED.add(symbol)
    pos.setdefault("_sl_unverified", []).append({"from": old_sl, "to": new_sl, "at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()})
    pos["sl_unverified"] = True
    pos["sl_sync"] = "pending"
    log(f"SL drift unverified {symbol} {old_sl:.4f} -> {new_sl:.4f} (exchange not amended) - flagged")
    return False


def _active_protective_readback(ex, symbol, oid, cid):
    """Find an authoritative active representation in unified or provider-specific open-order views."""
    views = []
    fetch_open = getattr(ex, "fetch_open_orders", None)
    if callable(fetch_open):
        views.extend([("plain", lambda: fetch_open(symbol)),
                      ("trigger", lambda: fetch_open(symbol, None, None, {"trigger": True})),
                      ("stop", lambda: fetch_open(symbol, None, None, {"stop": True}))])
    for name in ("fetch_open_algo_orders", "fetch_open_conditional_orders", "fetch_open_trigger_orders"):
        fn = getattr(ex, name, None)
        if callable(fn):
            views.append((name, lambda fn=fn: fn(symbol)))
    saw_inconclusive = False
    for view, fetch in views:
        try:
            rows = fetch()
        except Exception:
            saw_inconclusive = True
            continue
        if not isinstance(rows, list):
            saw_inconclusive = True
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            info = row.get("info") or {}
            row_id = row.get("id") or info.get("orderId") or info.get("orderID")
            row_cid = row.get("clientOrderId") or row.get("orderLinkId") or info.get("clientOrderId") or info.get("orderLinkId")
            if row_id == oid or (cid and row_cid == cid):
                return row, None
    return None, "active protective-order readback was inconclusive" if saw_inconclusive else "replacement is not present in any active protective-order view"


def _verify_protective_stop(ex, symbol, order_obj, expected_trigger, close_side, expected_qty):
    """Require authoritative exchange readback of every protective field; create-order data alone is
    never sufficient. Binance hedge mode additionally requires the correct positionSide."""
    if not isinstance(order_obj, dict) or not order_obj.get("id"):
        return False, "replacement stop has no authoritative exchange id"
    oid = order_obj["id"]
    cid = order_obj.get("clientOrderId") or order_obj.get("orderLinkId")
    candidate = None
    fetch_error = None
    try:
        fetched = ex.fetch_order(oid, symbol)
        if isinstance(fetched, dict) and fetched.get("id") == oid:
            candidate = fetched
        else:
            fetch_error = "authoritative replacement readback is missing or mismatched"
    except Exception as exc:
        fetch_error = f"authoritative replacement readback failed: {exc}"
    status = None if candidate is None else (candidate.get("status") or (candidate.get("info") or {}).get("status"))
    active_statuses = {"open", "new", "active", "pending", "untriggered", "trigger_pending"}
    terminal_statuses = {"canceled", "cancelled", "closed", "expired", "rejected", "rejected_by_exchange", "failed"}
    if candidate is None or status is None or str(status).lower() not in active_statuses:
        active, active_error = _active_protective_readback(ex, symbol, oid, cid)
        if active is None:
            if status is not None and str(status).lower() in terminal_statuses:
                return False, f"replacement stop is not active (status={status})"
            return False, active_error or fetch_error or f"replacement stop status is not active (status={status})"
        candidate = active
        status = candidate.get("status") or (candidate.get("info") or {}).get("status")
        if status is not None and str(status).lower() not in active_statuses:
            return False, f"active-order endpoint returned non-active status={status}"
    if status is None:
        return False, "replacement stop has no authoritative active status"
    if str(status).lower() in terminal_statuses or str(status).lower() not in active_statuses:
        return False, f"replacement stop is not active (status={status})"
    info = candidate.get("info") or {}
    trigger = candidate.get("stopLossPrice") or candidate.get("triggerPrice") or info.get("stopLossPrice") or info.get("triggerPrice")
    if trigger is None:
        return False, "no authoritative trigger price"
    try:
        if abs(float(trigger) - float(expected_trigger)) > max(1e-8, abs(float(expected_trigger)) * 1e-6):
            return False, f"trigger price mismatch (got {trigger}, expected {expected_trigger})"
    except (TypeError, ValueError):
        return False, "authoritative trigger price is not numeric"
    order_side = candidate.get("side") or info.get("side")
    if order_side is None or str(order_side).lower() != close_side:
        return False, f"protective side missing or mismatch (got {order_side}, expected {close_side})"
    reduce_only = candidate.get("reduceOnly")
    if reduce_only is None:
        reduce_only = info.get("reduceOnly")
    if reduce_only is not True and str(reduce_only).lower() != "true":
        return False, "authoritative reduceOnly evidence is missing or false"
    amount = candidate.get("amount")
    if amount is None:
        amount = info.get("origQty") or info.get("qty")
    if amount is None:
        return False, "authoritative covered quantity is missing"
    try:
        if float(amount) + 1e-9 < float(expected_qty):
            return False, f"replacement stop covers {amount}, less than remaining qty {expected_qty}"
    except (TypeError, ValueError):
        return False, "authoritative covered quantity is not numeric"
    if str(getattr(ex, "id", "")).lower().startswith("binance") and bool(getattr(ex, "options", {}).get("hedgeMode")):
        expected_position_side = "LONG" if close_side == "sell" else "SHORT"
        position_side = candidate.get("positionSide") or info.get("positionSide")
        if position_side is None or str(position_side).upper() != expected_position_side:
            return False, f"Binance hedge positionSide missing or mismatch (got {position_side}, expected {expected_position_side})"
    return True, None


def _cancel_all_protective_orders(ex, symbol, pos):
    """Cancel and verify absence of every protective order tracked for this position: the current
    sl/tp plus any unresolved replacement left over from a prior SL amendment. Only reports success
    once every tracked id is confirmed gone; a pending replacement id is preserved on failure so the
    next reconcile/close attempt retries it instead of silently losing track of it."""
    from backend.app.oco import cancel_oco_orders
    ids = pos.get("oco_ids") or {}
    ok = True
    if ids.get("pos_id") or ids.get("sl") or ids.get("tp"):
        if cancel_oco_orders(ex, symbol, pos_id=ids.get("pos_id"), sl_id=ids.get("sl"), tp_id=ids.get("tp")) is False:
            ok = False
    pending = ids.get("sl_pending_cancel")
    if pending and pending.get("id"):
        if cancel_oco_orders(ex, symbol, sl_id=pending["id"]) is False:
            ok = False
        else:
            ids.pop("sl_pending_cancel", None)
    pending_cleanup = ids.get("sl_pending_cleanup")
    if pending_cleanup and pending_cleanup.get("id"):
        if cancel_oco_orders(ex, symbol, sl_id=pending_cleanup["id"]) is False:
            ok = False
        else:
            ids.pop("sl_pending_cleanup", None)
    return ok

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

def _configured_hedge_mode(ex, symbol):
    """Read back the account's actual position mode via ex.fetch_position_mode(), if the exchange
    double exposes a genuinely configured one (skip bare Mock() doubles with no configured response —
    real ccxt exchanges are never unittest.mock.Mock instances). Returns None when unknown/unreadable."""
    fetch_pm = getattr(ex, "fetch_position_mode", None)
    if fetch_pm is None:
        return None
    from unittest.mock import Mock as _Mock
    if isinstance(fetch_pm, _Mock):
        configured = False
        se = getattr(fetch_pm, "side_effect", None)
        rv = getattr(fetch_pm, "return_value", None)
        if se is not None:
            configured = True
        elif rv is not None and not isinstance(rv, _Mock) and rv != []:
            configured = True
        elif isinstance(rv, dict) and rv:
            configured = True
        if not configured:
            return None
    try:
        mode = fetch_pm(symbol)
    except Exception:
        return None
    # ccxt's unified fetchPositionMode schema key is 'hedged' (confirmed live: {'info': {...},
    # 'hedged': False}) — NOT 'hedgeMode'. Default to False (assume one-way) if the key is ever
    # genuinely absent, never default to "whole dict truthy" which was always True.
    return mode.get("hedged", False) if isinstance(mode, dict) else bool(mode)


def ensure_futures_setup(ex, symbol):
    """يضبط الرافعة ونوع الهامش للفيوتشر — يفشل بوضوح لو الإعداد ما اتأكدش (P0-02)."""
    if CONFIG.get("market")!="future": return
    lev = int(CONFIG.get("leverage", 5))
    mtype = CONFIG.get("margin_type", "ISOLATED")
    # exchanges answer "already set" with an error (Binance -4046 / -4059, Bybit 110026 / 110043 / 110025): that's success
    def _already(e):
        m = str(e).lower()
        return any(k in m for k in ("no need to change", "-4046", "-4059", "not modified", "110026", "110043", "110025", "already"))
    # set_position_mode is an ACCOUNT-WIDE setting, not per-symbol — calling it unconditionally on
    # every entry attempt means Binance rejects it with -4067 "Position side cannot be changed if
    # there exists open orders" as SOON as any other symbol has an open position/order, permanently
    # blocking every subsequent entry for the rest of the account's life. -4067 isn't in the
    # "already set" tolerance list (it's a genuine rejection, not a no-op), so it used to raise and
    # trip recovery_required on a perfectly fine, already-correctly-configured account — discovered
    # live on Binance Demo Trading right after a real first entry succeeded. Skip the call entirely
    # once we already know (via read-back) the account is in the desired mode.
    already_one_way = _configured_hedge_mode(ex, symbol) is False
    calls = [(f"set_leverage({lev},{symbol})", lambda: ex.set_leverage(lev, symbol)),
             (f"set_margin_mode({mtype},{symbol})", lambda: ex.set_margin_mode(mtype, symbol))]
    if not already_one_way:
        calls.append((f"set_position_mode(one-way,{symbol})", lambda: ex.set_position_mode(False)))
    for what, call in calls:
        try: call()
        except Exception as e:
            if not _already(e): raise RuntimeError(f"{what} فشل: {e}") from e
    # verify via read-back where supported (skip mocks)
    is_hedge = _configured_hedge_mode(ex, symbol)
    if is_hedge:
        raise RuntimeError("المنصة لسه في Hedge Mode بعد set_position_mode(False) — عدّلها يدوياً من إعدادات الفيوتشر")

def _funding_pnl(pos, required=False):
    """Return only funding data explicitly marked authoritative for live accounting."""
    if pos.get("type") == "paper":
        return 0.0
    if pos.get("funding_verified") is not True:
        if required:
            raise RuntimeError("funding evidence unavailable for live PnL")
        return None
    try:
        return float(pos.get("funding_pnl"))
    except (TypeError, ValueError):
        if required:
            raise RuntimeError("funding evidence malformed for live PnL")
        return None


def _fee_rate(pos, required=False):
    if pos.get("type") == "paper":
        return float(pos.get("fee_rate", 0.0004))
    if pos.get("fee_verified") is not True:
        if required:
            raise RuntimeError("fee evidence unavailable for live PnL")
        return None
    try:
        return float(pos["fee_rate"])
    except (KeyError, TypeError, ValueError):
        if required:
            raise RuntimeError("fee evidence malformed for live PnL")
        return None


def _refresh_fee_evidence(ex, symbol, pos, close_order=None):
    """Require explicit entry and close fee evidence from exchange/order records."""
    raw = pos.get("entry_fee_rate")
    close_rate = None
    if close_order:
        close_rate = _order_fee_rate(close_order, close_order.get("average") or close_order.get("price"), close_order.get("filled"), pos.get("contract_size"))
    entry_notional = float(pos.get("entry", 0)) * float(pos.get("qty", 0)) * float(pos.get("contract_size", 1))
    close_price = float(close_order.get("average") or close_order.get("price")) if close_order else 0.0
    close_qty = float(close_order.get("filled") or close_order.get("amount") or 0) if close_order else 0.0
    close_notional = close_price * close_qty * float(pos.get("contract_size", 1))
    close_cost = float((close_order.get("fee") or {}).get("cost", 0) or 0) if close_order else 0.0
    entry_cost = pos.get("entry_fee_cost")
    if entry_cost is None:
        entry_cost = float(raw) * entry_notional
    if close_rate is None or entry_notional <= 0 or close_notional <= 0 or entry_cost < 0 or close_cost <= 0:
        raise RuntimeError("entry or close fee evidence unavailable for live accounting")
    pos["fee_rate"] = (float(entry_cost) + close_cost) / (entry_notional + close_notional)
    pos["fee_verified"] = True
    return pos["fee_rate"]


def _refresh_funding_evidence(ex, symbol, pos):
    """Load authoritative funding cashflows; never infer them as zero."""
    for method_name in ("fetch_funding_history",):
        fn = getattr(ex, method_name, None)
        if not callable(fn) or not (method_name in dir(type(ex)) or method_name in getattr(ex, "__dict__", {})):
            continue
        try:
            since = None
            if pos.get("time"):
                since = int(datetime.fromisoformat(pos["time"]).timestamp() * 1000)
            rows = fn(symbol, since=since)
            if not isinstance(rows, list):
                continue
            total = sum(float(r.get("amount", r.get("cost", 0)) or 0) for r in rows if isinstance(r, dict))
            pos["funding_pnl"] = total
            pos["funding_verified"] = True
            return total
        except Exception:
            continue
    raise RuntimeError("funding history unavailable for live accounting")


def _position_contract_size(pos):
    value = pos.get("contract_size")
    return float(value) if pos.get("contract_size_verified") is True and value is not None and float(value) > 0 else (1.0 if pos.get("type") == "paper" else None)



def _contract_meta(ex, symbol):
    """Return explicit linear-contract metadata; reject inverse/unknown semantics."""
    try:
        market = ex.market(symbol)
    except Exception as exc:
        raise RuntimeError(f"market metadata unavailable for {symbol}: {exc}") from exc
    if not isinstance(market, dict) or not market.get("contract") or market.get("linear") is not True:
        raise RuntimeError(f"incomplete or non-linear futures contract metadata for {symbol}")
    if market.get("inverse"):
        raise RuntimeError(f"inverse contract is unsupported for {symbol}")
    contract_size = float(market.get("contractSize") or 0)
    if contract_size <= 0:
        raise RuntimeError(f"invalid contractSize for {symbol}")
    return {"contract": True, "contract_size": contract_size, "contract_size_verified": True, "inverse": False}


FILL_LOOKUP_WAITS = (0.0, 0.5, 1.0, 2.0)   # seconds between tries: fills normally show at once


def _fill_from_trades(ex, symbol, order):
    """Binance (seen on Demo) answers a market order with no average price and no fee, and fetch_order has no fee
    either; the fills of that order have both. Without them a close priced the trade at the *requested* price and
    the fee check failed (float(None)), so every live exit ended in recovery. Returns the order with filled /
    average / fee taken from its own fills (several partial fills summed, price volume-weighted); unchanged if it
    already has them or the fills can't be read — the fee checks downstream still fail closed."""
    if not isinstance(order, dict) or not order.get("id"):
        return order
    if order.get("average") and (order.get("fee") or {}).get("cost") is not None:
        return order
    for wait in FILL_LOOKUP_WAITS:
        if wait: time.sleep(wait)
        try:
            rows = ex.fetch_my_trades(symbol, params={"orderId": order["id"]})
        except Exception:
            continue
        if not isinstance(rows, list):
            return order                                   # not a fill list: nothing to read, don't wait on it
        rows = [t for t in rows if isinstance(t, dict) and str(t.get("order", order["id"])) == str(order["id"])]
        qty = sum(float(t.get("amount") or 0) for t in rows)
        if qty <= 0:
            continue
        fees = [t.get("fee") or {} for t in rows]
        out = dict(order)
        out["filled"] = qty
        out["average"] = sum(float(t.get("amount") or 0) * float(t.get("price") or 0) for t in rows) / qty
        if all(f.get("cost") is not None for f in fees):
            out["fee"] = {"cost": sum(float(f["cost"]) for f in fees), "currency": fees[0].get("currency")}
        return out
    return order


def _order_fee_rate(order, price, contracts, contract_size):
    fee = (order or {}).get("fee") or {}
    cost = fee.get("cost")
    if cost is None and isinstance((order or {}).get("fees"), list):
        cost = sum(float(x.get("cost", 0) or 0) for x in order["fees"] if isinstance(x, dict))
    try:
        notional = float(price) * float(contracts) * float(contract_size)
        return float(cost) / notional if cost is not None and notional > 0 else None
    except (TypeError, ValueError):
        return None


def place_order(ex,symbol,side,amount_usdt,price, client_order_id=None, close_qty=None):
    """side = long/short/close_long/close_short — يحسب الكمية من USDT * leverage.
    client_order_id: stable id for idempotent retry (P0-05). If None, generated; returned in result.
    Idempotency (6): on create_order timeout, lookup by clientOrderId/orderLinkId and reconcile fills before retry.
    Futures compat (4): exchange-specific params via _build_futures_params.
    """
    is_future = CONFIG.get("market","future")=="future"
    lev = int(CONFIG.get("leverage",5)) if is_future else 1
    meta = _contract_meta(ex, symbol) if is_future and not CONFIG["paper_trading"] else {"contract": False, "contract_size": 1.0, "inverse": False}
    notional = amount_usdt * lev if is_future else amount_usdt
    if close_qty is not None:
        qty = float(close_qty)
    elif is_future and meta["contract"]:
        qty = linear_contracts_from_margin(amount_usdt, lev, price, meta["contract_size"])
    else:
        qty = notional / price
    try: qty=float(ex.amount_to_precision(symbol, qty))
    except: qty=round(qty,6)
    if CONFIG["paper_trading"]:
        cid = client_order_id or f"raqm-{uuid.uuid4().hex[:12]}"[:36]
        return {"id":"paper-"+str(int(time.time()*1000)),"qty":qty,"price":price,"cost":qty*price,"notional":notional,"leverage":lev,"contract_size":meta.get("contract_size", 1.0),"contract_size_verified":meta.get("contract_size_verified", False),"clientOrderId": cid}
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
                    found = _fill_from_trades(ex, symbol, found)
                    fq=normalize_filled_contracts(found)
                    ap=float(found.get("average",price) or found.get("price",price) or price)
                    return {"id":str(found.get("id","")),"qty":fq,"price":ap,"cost":fq*ap,"notional":notional,"leverage":lev,"contract_size":meta.get("contract_size", 1.0),"contract_size_verified":meta.get("contract_size_verified", False),"entry_fee_rate":_order_fee_rate(found, ap, fq, meta.get("contract_size", 1.0)),"entry_fee_cost":float((found.get("fee") or {}).get("cost", 0) or 0),"clientOrderId": cid, "reconciled": True}
            except Exception:
                pass
        raise
    order = _fill_from_trades(ex, symbol, order)
    fq=normalize_filled_contracts(order)
    ap=float(order.get("average",price) or order.get("price",price) or price)
    return {"id":str(order.get("id","")),"qty":fq,"price":ap,"cost":fq*ap,"notional":notional,"leverage":lev,"contract_size":meta.get("contract_size", 1.0),"contract_size_verified":meta.get("contract_size_verified", False),"entry_fee_rate":_order_fee_rate(order, ap, fq, meta.get("contract_size", 1.0)),"entry_fee_cost":float((order.get("fee") or {}).get("cost", 0) or 0),"raw":order,"clientOrderId": cid}

def _exchange_position_qty(ex, symbol, *, side=None, position_idx=None):
    """Return authoritative matching position contracts; None means inconclusive."""
    try:
        positions = ex.fetch_positions([symbol])
        if position_idx is None and side in ("long", "short") and bool(getattr(ex, "options", {}).get("hedgeMode")):
            position_idx = 1 if side == "long" else 2
        status = authoritative_position_state(positions, symbol, position_idx=position_idx, side=side)
        if status == "inconclusive":
            return None
        if status == "flat":
            return 0.0
        wanted = symbol.split(":")[0]
        for position in positions:
            actual = position.get("symbol") or (position.get("info") or {}).get("symbol")
            if not isinstance(actual, str) or actual.split(":")[0] != wanted:
                continue
            info = position.get("info") or {}
            actual_idx = position.get("positionIdx", info.get("positionIdx"))
            actual_side = str(position.get("side", info.get("positionSide", ""))).lower()
            if position_idx is not None and str(actual_idx) != str(position_idx):
                continue
            if side and actual_side not in ("", side, "buy" if side == "long" else "sell", "long" if side == "long" else "short"):
                continue
            raw = position.get("contracts")
            if raw is None:
                raw = info.get("size")
            return abs(float(raw))
        return None
    except Exception:
        return None

def _close_failure(reason, *, by_exchange=False):
    return {"price": None, "qty": 0.0, "contract_size": None, "by_exchange": by_exchange, "accounting_verified": False, "recovery_required": True, "error": str(reason)}

def _release_position_risk(symbol, pos):
    """Best-effort Central Risk Manager release — never let a ledger write failure block
    an already-confirmed close; log and move on."""
    try:
        riskmgr.release_open_risk(RISK_PATH, strategy=pos.get("strategy") or _current_strategy_name(), symbol=symbol)
    except Exception as e:
        log(f"risk ledger release failed {symbol}: {e}")

ENTRY_RECHECK_S = 2.0   # pause before the second flat reading after an entry error


def _entry_order_outcome(ex, symbol, cid):
    """What the exchange says about our entry order, by its client id: "not_filled" (cancelled / rejected / expired
    with nothing filled), "not_found" (Binance -2013: it never reached the book), "filled" (some quantity), or
    "unknown" (still open, odd answer, or the lookup itself failed)."""
    try:
        o = _fetch_order_by_cid(ex, cid, symbol)
    except Exception as e:
        if isinstance(e, getattr(ccxt, "OrderNotFound", ())) or "-2013" in str(e) or "Order does not exist" in str(e):
            return "not_found"
        return "unknown"
    if not isinstance(o, dict) or (o.get("clientOrderId") not in (None, cid) and o.get("id") != cid):
        return "unknown"
    try: filled = float(o.get("filled") or 0)
    except (TypeError, ValueError): return "unknown"
    if filled > 0: return "filled"
    return "not_filled" if str(o.get("status") or "").lower() in ("canceled", "cancelled", "rejected", "expired") else "unknown"


def _entry_failed_flat(ex, symbol, cid, side=None):
    """After an entry order raised: is it proven that nothing was opened? Same standard as the close path, which never
    trusts a flat position reading without fill evidence — here: flat, the order itself confirmed unfilled, and flat
    again a moment later. Anything short of that is recovery (the reservation stays, new entries stop)."""
    if _exchange_position_qty(ex, symbol, side=side) != 0.0:
        return False, "position not proven flat"
    outcome = _entry_order_outcome(ex, symbol, cid)
    if outcome not in ("not_filled", "not_found"):
        return False, f"entry order outcome {outcome}"
    if ENTRY_RECHECK_S: time.sleep(ENTRY_RECHECK_S)
    if _exchange_position_qty(ex, symbol, side=side) != 0.0:
        return False, "position appeared on the second reading"
    return True, outcome


def _authoritative_close_fill(ex, symbol, pos):
    """Require exchange trade evidence before treating an already-flat position as closed."""
    try:
        since = int(datetime.fromisoformat(pos["time"]).timestamp() * 1000)
        close_side = "sell" if pos.get("side", "long") == "long" else "buy"
        rows = [t for t in ex.fetch_my_trades(symbol, since=since, limit=100)
                if t.get("side") == close_side]
        valid = []
        for row in rows:
            qty = float(row.get("filled", row.get("amount", 0)) or 0)
            px = float(row.get("average") or row.get("price") or 0)
            if qty > 0 and px > 0:
                valid.append((qty, px, row))
        total = sum(x[0] for x in valid)
        if total + 1e-9 < float(pos.get("qty", 0)):
            return None
        return {"qty": total, "price": sum(q * p for q, p, _ in valid) / total,
                "raw": {"filled": total, "price": sum(q * p for q, p, _ in valid) / total,
                        "fee": {"cost": sum(float((r.get("fee") or {}).get("cost", 0) or 0) for _, _, r in valid)}}}
    except Exception:
        return None


def close_live_position(ex, symbol, pos, price):
    """Close exact authoritative contracts and verify an authoritative flat readback."""
    side = pos.get("side", "long")
    exchange_qty = _exchange_position_qty(ex, symbol, side=side, position_idx=pos.get("position_idx"))
    if exchange_qty is None:
        return _close_failure(f"cannot confirm current exchange position for {symbol}")
    if exchange_qty == 0:
        evidence = _authoritative_close_fill(ex, symbol, pos)
        if evidence is None:
            return _close_failure(f"exchange is flat but authoritative close fill is missing for {symbol}", by_exchange=True)
        if _cancel_all_protective_orders(ex, symbol, pos) is False:
            return _close_failure(f"protective cleanup is unconfirmed for {symbol}", by_exchange=True)
        try:
            _refresh_fee_evidence(ex, symbol, pos, evidence.get("raw"))
            _refresh_funding_evidence(ex, symbol, pos)
        except Exception as e:
            return _close_failure(e, by_exchange=True)
        return {"price": evidence["price"], "qty": evidence["qty"], "authoritative_qty": evidence["qty"], "authoritative_fill_qty": evidence["qty"], "contract_size": pos.get("contract_size"), "by_exchange": True, "accounting_verified": True, "recovery_required": False, "error": None}
    try:
        res = place_order(ex, symbol, "close_long" if side == "long" else "close_short", 0, price, close_qty=exchange_qty)
    except Exception as e:
        remaining = _exchange_position_qty(ex, symbol, side=side, position_idx=pos.get("position_idx"))
        if remaining == 0:
            evidence = _authoritative_close_fill(ex, symbol, pos)
            if evidence is None:
                return _close_failure(f"close errored and no authoritative fill proves closure for {symbol}", by_exchange=True)
            log(f"{symbol}: المنصة قفلت الصفقة بالفعل (وقف/هدف) — {e}")
            try:
                _refresh_fee_evidence(ex, symbol, pos, evidence.get("raw")); _refresh_funding_evidence(ex, symbol, pos)
            except Exception as evidence_error:
                return _close_failure(evidence_error, by_exchange=True)
            return {"price": evidence["price"], "qty": evidence["qty"], "authoritative_qty": evidence["qty"], "authoritative_fill_qty": evidence["qty"], "contract_size": pos.get("contract_size"), "by_exchange": True, "accounting_verified": True, "recovery_required": False, "error": None}
        return _close_failure(e)
    if float(res.get("qty", 0) or 0) <= 0 or float(res.get("qty", 0)) + 1e-9 < float(exchange_qty):
        return _close_failure("close fill is partial or unverified; recovery required")
    remaining = _exchange_position_qty(ex, symbol, side=side, position_idx=pos.get("position_idx"))
    if remaining is None or remaining != 0:
        return _close_failure(f"close accepted but flat state is unconfirmed for {symbol}; remaining={remaining}")
    ids = pos.get("oco_ids") or {}
    if ids.get("pos_id") or ids.get("sl") or ids.get("tp") or ids.get("sl_pending_cancel") or ids.get("sl_pending_cleanup"):
        if _cancel_all_protective_orders(ex, symbol, pos) is False:
            return _close_failure(f"protective cleanup is unconfirmed for {symbol}")
    try:
        _refresh_fee_evidence(ex, symbol, pos, res.get("raw"))
        _refresh_funding_evidence(ex, symbol, pos)
    except Exception as e:
        return _close_failure(e)
    return {"price": res["price"], "qty": res["qty"], "authoritative_qty": exchange_qty, "authoritative_fill_qty": res["qty"], "contract_size": res.get("contract_size", pos.get("contract_size")), "by_exchange": False, "accounting_verified": True, "recovery_required": False, "error": None}

def _require_verified_close(result):
    if not isinstance(result, dict) or result.get("accounting_verified") is not True:
        raise RuntimeError((result or {}).get("error", "live close accounting is unverified"))
    return result

def check_sl_tp(state, prices, ex=None):
    closed=[]; closed_positions={}
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
                    if not _amend_exchange_sl(symbol, pos, new_sl_w, old_sl_w, ex, state):
                        pos["sl_unverified"] = True
                        pos["sl_sync"] = pos.get("sl_sync", "recovery")
                        continue
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
                        if not _amend_exchange_sl(symbol, pos, be_sl, old_sl, ex, state):
                            pos["sl_unverified"] = True
                            pos["sl_sync"] = pos.get("sl_sync", "recovery")
                            continue
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
                _require_verified_close(res)
                cs = _position_contract_size(pos)
                if cs is None:
                    raise RuntimeError("missing contract_size for live PnL")
                pnl = futures_net_pnl(entry, res["price"], res["qty"], cs, pos.get("side", "long"), fee_rate=_fee_rate(pos, required=True), funding_pnl=_funding_pnl(pos, required=True))
                log(f"🔒 اغلاق حقيقي {symbol} @ {res['price']:.4f} PnL {pnl:+.4f}")
                notify(f"🔒 قفل {symbol} — {reason}\nدخول {entry:.6g} → خروج {res['price']:.6g}\nPnL {pnl:+.2f}$ (حقيقي)")
                state["history"].append({"symbol":symbol,"side":pos.get("side","long"),"entry":entry,"exit":res["price"],"qty":res["qty"],"pnl":pnl,"pnl_pct":(res["price"]/entry-1)*100,"reason":reason,"time":datetime.now(timezone.utc).isoformat(),"type":"live"})
            state["stats"]["trades"]+=1; state["stats"]["pnl"]+=float(pnl)
            if pnl>0: state["stats"]["wins"]+=1
            else: state["stats"]["losses"]+=1
            closed.append(symbol); closed_positions[symbol] = pos
        except Exception as e:
            if not CONFIG["paper_trading"]:
                state.setdefault("recovery_required", {})[symbol] = {"reason": f"live close accounting or protective cleanup unconfirmed: {e}", "at": datetime.now(timezone.utc).isoformat()}
                _ENTRY_BLOCK["reason"] = "live close requires recovery"
                save_state(state)
            log(f"فشل اغلاق {symbol}: {e}")
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
    if closed or flagged:
        save_state(state)
        if not CONFIG["paper_trading"]:
            for s, pos in closed_positions.items(): _release_position_risk(s, pos)

    return closed

def try_enter_wave(symbol, analysis, state, ex):
    """Wave Flats: enter at market on a new setup from the last closed candle, with the setup's own stop/targets."""
    sig=analysis.get("wave")
    if not sig or in_position(state, symbol): return
    seen=state.setdefault("wave_seen",{})
    if seen.get(symbol)==sig["ts"]: return   # one entry per signal candle (the loop polls every minute)
    seen[symbol]=sig["ts"]; save_state(state)
    side="long" if sig["dir"]==1 else "short"; price=analysis["price"]
    tp=sig["tgt2"] if sig["two"] else sig["tgt1"]
    if len(state["positions"])>=CONFIG["max_open_positions"] or not daily_pnl_ok(state): return
    if (side=="long" and price<=sig["stop"]) or (side=="short" and price>=sig["stop"]):
        log(f"⏸️ {symbol} {sig['kind']} — السعر عدّى الوقف قبل الدخول"); return
    if not CONFIG["paper_trading"]:
        pos = _single_leg_live_entry(ex, state, symbol, side, position_size(price, ex, stop_price=sig["stop"]),
            price, sig["stop"], tp, "wave_flats", {"wave": {"kind": sig["kind"], "tp1": sig["tgt1"] if sig["two"] else None,
            "tp1_done": False, "be": sig["be"]}})
        if pos:
            state["last_trade"][symbol]=datetime.now(timezone.utc).isoformat(); save_state(state)
        return
    if len(state["positions"])>=CONFIG["max_open_positions"] or not daily_pnl_ok(state): return
    side="long" if sig["dir"]==1 else "short"; price=analysis["price"]
    if (side=="long" and price<=sig["stop"]) or (side=="short" and price>=sig["stop"]):
        log(f"⏸️ {symbol} {sig['kind']} — السعر عدّى الوقف قبل الدخول"); return
    try:
        res=place_order(ex,symbol,side,position_size(price, ex, stop_price=sig["stop"]),price)
        tp=sig["tgt2"] if sig["two"] else sig["tgt1"]
        state["positions"][symbol]={"side":side,"entry":res["price"],"qty":res["qty"],"cost":res["cost"],"notional":res.get("notional"),"contract_size":res.get("contract_size", 1.0),"contract_size_verified":res.get("contract_size_verified", False),"entry_fee_rate":res.get("entry_fee_rate"),"entry_fee_cost":res.get("entry_fee_cost"),"leverage":res.get("leverage",CONFIG.get("leverage",5)),
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
    equity = _fetch_equity_usdt(ex)
    if equity is None:
        _ENTRY_BLOCK["reason"] = "account equity unavailable — blocking new entries until the risk gate can size risk"
        log(f"⚠️ {_ENTRY_BLOCK['reason']}")
    else:
        try:
            tripped, kill_reason = riskmgr.update_equity_and_check_kill_switch(RISK_PATH, equity)
            if tripped:
                _ENTRY_BLOCK["reason"] = f"Central Risk Manager kill switch is tripped — {kill_reason}"
                log(f"🛑 {_ENTRY_BLOCK['reason']}")
        except Exception as e:
            # Ledger unavailable: fail closed — block new entries rather than trade blind on risk state.
            _ENTRY_BLOCK["reason"] = f"risk ledger unavailable — blocking new entries: {e}"
            log(f"⚠️ {_ENTRY_BLOCK['reason']}")
    try:
        live = {}
        positions = ex.fetch_positions()
        # An empty list is a NORMAL, valid answer — a flat account (no open positions) — not a bad read.
        # Only a non-list response (None, a dict error body ccxt didn't raise on, etc.) is actually
        # incomplete/untrustworthy and should block entries. Blocking on a merely-empty list meant a bot
        # could never take its very first trade from a clean account (every fresh demo/testnet/live account
        # starts flat) — discovered during Testnet E2E validation (Phase 1 of the live-trading roadmap).
        if not isinstance(positions, list):
            _ENTRY_BLOCK["reason"] = "exchange position snapshot is empty or incomplete"
            log(f"⚠️ {_ENTRY_BLOCK['reason']}")
            save_state(state)
            return
        for p in positions:
            c = p.get("contracts") if p.get("contracts") is not None else (p.get("info") or {}).get("positionAmt")
            if c and abs(float(c)) > 0: live[(p.get("symbol") or "").split(":")[0]] = abs(float(c))
    except Exception as e:
        _ENTRY_BLOCK["reason"] = f"مقدرناش نقرا الصفقات من المنصة: {e}"; log(f"⚠️ {_ENTRY_BLOCK['reason']}"); return
    for sym, pos in list(state["positions"].items()):
        q = live.get(sym.split(":")[0])
        flat = state.setdefault("_flat_seen", {})
        if q:
            flat.pop(sym, None)
            # Position is still open on the exchange: opportunistically retry cancelling any stale
            # replacement stop left over from a prior SL amendment whose old-leg cancel was ambiguous
            # (covers restart recovery too, since this is durably persisted in pos["oco_ids"]).
            pending = (pos.get("oco_ids") or {}).get("sl_pending_cancel") or (pos.get("oco_ids") or {}).get("sl_pending_cleanup")
            pending_key = "sl_pending_cancel" if (pos.get("oco_ids") or {}).get("sl_pending_cancel") else "sl_pending_cleanup"
            if pending and pending.get("id"):
                try:
                    from backend.app.oco import cancel_oco_orders
                    if cancel_oco_orders(ex, sym, sl_id=pending["id"]) is True:
                        pos["oco_ids"].pop(pending_key, None)
                        save_state(state)
                except Exception:
                    pass
        elif _exchange_position_qty(ex, sym) != 0.0:
            flat.pop(sym, None); continue                                   # the per-coin check disagrees (or failed): wait
        if not q:
            flat[sym] = flat.get(sym, 0) + 1
            if flat[sym] < 2: continue                                     # flat twice in a row before believing it
            flat.pop(sym, None)
            fills = []
            try:
                since = int(datetime.fromisoformat(pos["time"]).timestamp() * 1000)
                close_side = "sell" if pos.get("side", "long") == "long" else "buy"
                fills = [t for t in ex.fetch_my_trades(sym, since=since, limit=50) if t.get("side") == close_side and float(t.get("filled", t.get("amount", 0)) or 0) > 0]
            except Exception:
                fills = []
            if not fills:
                state.setdefault("recovery_required", {})[sym] = {"reason": "exchange flat but no authoritative closing fill", "at": datetime.now(timezone.utc).isoformat()}
                _ENTRY_BLOCK["reason"] = "exchange exit has no authoritative fill evidence"
                save_state(state)
                continue
            fill_rows = []
            for fill in fills:
                try:
                    fq = float(fill.get("filled", fill.get("amount", 0)) or 0)
                    fp = float(fill.get("average") or fill.get("price"))
                    if fq > 0 and fp > 0:
                        fill_rows.append((fq, fp, fill))
                except (TypeError, ValueError):
                    continue
            total_filled = sum(x[0] for x in fill_rows)
            if total_filled + 1e-9 < float(pos.get("qty", 0)):
                state.setdefault("recovery_required", {})[sym] = {"reason": "closing fills are partial or incomplete", "filled": total_filled, "expected": pos.get("qty"), "at": datetime.now(timezone.utc).isoformat()}
                _ENTRY_BLOCK["reason"] = "partial closing fill requires recovery"
                save_state(state)
                continue
            exit_px = sum(qty * px for qty, px, _ in fill_rows) / total_filled
            fee_cost = sum(float((f.get("fee") or {}).get("cost", 0) or 0) for _, _, f in fill_rows)
            aggregate_fill = {"filled": total_filled, "price": exit_px, "fee": {"cost": fee_cost}}
            cs = _position_contract_size(pos)
            if cs is None:
                state.setdefault("recovery_required", {})[sym] = {"reason": "missing contract_size for realized PnL", "at": datetime.now(timezone.utc).isoformat()}
                save_state(state)
                continue
            try:
                _refresh_fee_evidence(ex, sym, pos, aggregate_fill)
                _refresh_funding_evidence(ex, sym, pos)
            except Exception as e:
                state.setdefault("recovery_required", {})[sym] = {"reason": f"funding evidence unavailable: {e}", "at": datetime.now(timezone.utc).isoformat()}
                _ENTRY_BLOCK["reason"] = "funding evidence unavailable for live accounting"
                save_state(state)
                continue
            pnl = futures_net_pnl(pos["entry"], exit_px, pos["qty"], cs, pos.get("side", "long"), fee_rate=_fee_rate(pos, required=True), funding_pnl=_funding_pnl(pos, required=True))
            by_hand = exit_px > float(pos.get("sl") or 0) * 1.01   # well above the stop: closed by hand in the Binance app
            why = "اتقفلت يدوي من Binance" if by_hand else "وقف الحماية اتنفذ على المنصة"
            if by_hand: state.setdefault("manual_hold", {})[sym] = datetime.now(timezone.utc).isoformat()
            log(f"🔒 {sym}: {why} @ {exit_px:.6g} PnL {pnl:+.2f}")
            notify(f"🔒 قفل {sym} — {why}\nدخول {pos['entry']:.6g} → خروج {exit_px:.6g}\nPnL {pnl:+.2f}$ ({_live_label()})")
            ids = pos.get("oco_ids") or {}
            try:
                cleanup_ok = _cancel_all_protective_orders(ex, sym, pos) if (ids.get("pos_id") or ids.get("sl") or ids.get("tp") or ids.get("sl_pending_cancel") or ids.get("sl_pending_cleanup")) else True
            except Exception:
                cleanup_ok = False
            if not cleanup_ok:
                state.setdefault("recovery_required", {})[sym] = {"reason": "protective cancellation unconfirmed after exchange flat", "at": datetime.now(timezone.utc).isoformat()}
                _ENTRY_BLOCK["reason"] = "protective cancellation requires recovery"
                save_state(state)
                continue
            state["history"].append({"symbol": sym, "side": pos.get("side", "long"), "entry": pos["entry"], "exit": exit_px, "qty": pos["qty"], "pnl": pnl,
                "pnl_pct": pnl / (pos["entry"] * pos["qty"] * cs / max(1, int(pos.get("leverage", CONFIG.get("leverage", 1))))) * 100, "reason": "قفل يدوي من Binance" if by_hand else "وقف المنصة", "time": datetime.now(timezone.utc).isoformat(),
                "type": "live", "opened": pos.get("time"), "rank": pos.get("rank")})
            state["stats"]["trades"] += 1; state["stats"]["pnl"] += float(pnl); state["stats"]["wins" if pnl > 0 else "losses"] += 1
            state["positions"].pop(sym, None); state["last_trade"][sym] = datetime.now(timezone.utc).isoformat()
            state.get("recovery_required", {}).pop(sym, None)
            save_state(state)
            _release_position_risk(sym, pos)
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
    """New temp file with an unpredictable name (O_EXCL: never follows a link someone planted), then rename over the
    target (rename replaces a link instead of writing through it)."""
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".w-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh: fh.write(json.dumps(data, ensure_ascii=False, default=str))
        os.replace(tmp, path)
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise

MANUAL_CLOSE_MAX_AGE_S = 600   # a request the bot couldn't run within 10 minutes is dropped, never executed late

def process_manual_closes(state, ex, prices):
    """Close requests from the site's admin button: close the position now, record it, and don't buy the coin
    again until its trend turns off and back on. Only closes — a request can never open anything."""
    d = _ipc_dir()
    if not d: return
    cmd_dir, res_dir = d / "commands", d / "results"
    try: files = sorted(cmd_dir.glob("close-*.json"))
    except Exception: return
    try:   # results older than a day are of no use to anyone
        for old in res_dir.glob("*.json"):
            if time.time() - old.stat().st_mtime > 86400: old.unlink()
    except Exception: pass
    for f in files:
        if f.is_symlink() or not f.is_file():
            try: f.unlink()
            except OSError: pass
            continue
        try: req = json.loads(f.read_text(encoding="utf-8"))
        except Exception: req = {}
        rid, sym = str(req.get("id", "")), str(req.get("symbol", ""))
        if not re.fullmatch(r"[0-9a-f]{32}", rid) or not re.fullmatch(r"[A-Z0-9]{1,20}/USDT(:USDT)?", sym):
            log(f"⚠️ طلب قفل مرفوض (id أو عملة مش صحيحة): {f.name}")
            try: f.unlink()
            except OSError: pass
            continue
        out = {"id": rid, "symbol": sym, "done_at": datetime.now(timezone.utc).isoformat()}
        try:
            at = float(req.get("at_epoch") or 0); age = time.time() - at
            if at <= 0 or age < -60: age = MANUAL_CLOSE_MAX_AGE_S + 1      # missing or in the future: treated as stale
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
                _require_verified_close(r)
                cs = _position_contract_size(pos)
                if cs is None:
                    raise RuntimeError("missing contract_size for live PnL")
                pnl = futures_net_pnl(pos["entry"], r["price"], r["qty"], cs, pos.get("side", "long"), fee_rate=_fee_rate(pos, required=True), funding_pnl=_funding_pnl(pos, required=True))
                state["history"].append({"symbol": match, "side": pos.get("side", "long"), "entry": pos["entry"], "exit": r["price"], "qty": r["qty"], "pnl": pnl,
                    "pnl_pct": pnl / (pos["entry"] * r["qty"] * cs / max(1, int(pos.get("leverage", CONFIG.get("leverage", 1))))) * 100, "reason": "قفل يدوي من الموقع", "time": datetime.now(timezone.utc).isoformat(),
                    "type": "live", "opened": pos.get("time"), "rank": pos.get("rank"), "by": req.get("by")})
                state["stats"]["trades"] += 1; state["stats"]["pnl"] += float(pnl); state["stats"]["wins" if pnl > 0 else "losses"] += 1
                state["positions"].pop(match, None); state["last_trade"][match] = datetime.now(timezone.utc).isoformat()
                state.get("recovery_required", {}).pop(match, None)
                state.setdefault("manual_hold", {})[match] = datetime.now(timezone.utc).isoformat()
                save_state(state)
                _release_position_risk(match, pos)
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

PAIR_RE = r"[A-Z0-9]{1,20}/USDT:USDT\|[A-Z0-9]{1,20}/USDT:USDT"

def process_paper_closes(state, ex, key):
    """Admin close requests for a paper bot (site: live bots section): RAQM_PAPER_IPC/<key>/commands/close-*.json,
    written by the API after checking the position exists. Only closes, at the current price, recorded like any exit;
    requests older than 10 minutes are dropped. key = the bot's public file name (status, momentum, ratio, ...)."""
    d = os.getenv("RAQM_PAPER_IPC", "").strip()
    if not d: return
    cmd_dir, res_dir = Path(d) / key / "commands", Path(d) / key / "results"
    try: files = sorted(cmd_dir.glob("close-*.json"))
    except Exception: return
    try:
        for old in res_dir.glob("*.json"):
            if time.time() - old.stat().st_mtime > 86400: old.unlink()
    except Exception: pass
    for f in files:
        if f.is_symlink() or not f.is_file():
            try: f.unlink()
            except OSError: pass
            continue
        try: req = json.loads(f.read_text(encoding="utf-8"))
        except Exception: req = {}
        rid, sym = str(req.get("id", "")), str(req.get("symbol", ""))
        sym_ok = re.fullmatch(PAIR_RE, sym) if key == "ratio" else re.fullmatch(r"[A-Z0-9]{1,20}/USDT(:USDT)?", sym)
        try: f.unlink()
        except OSError: pass
        if not re.fullmatch(r"[0-9a-f]{32}", rid) or not sym_ok:
            log(f"⚠️ طلب قفل مرفوض ({f.name})"); continue
        out = {"id": rid, "symbol": sym, "done_at": datetime.now(timezone.utc).isoformat()}
        at = float(req.get("at_epoch") or 0); age = time.time() - at
        reason = "قفل يدوي (أدمن)"
        try:
            if at <= 0 or age < -60 or age > MANUAL_CLOSE_MAX_AGE_S:
                out.update(ok=False, msg="الطلب قديم — اتلغى من غير تنفيذ")
            elif key == "ratio":
                if sym not in state.get("pairs", {}): out.update(ok=False, msg="الزوج ده مش مفتوح")
                else:
                    pnl = _ratio_close_pair(ex, state, sym, {}, reason, {}); save_state(state)
                    out.update(ok=True, msg="اتقفل", pnl=round(pnl, 4))
            else:
                match = next((k for k in state["positions"] if k.split(":")[0] == sym.split(":")[0]), None)
                if not match: out.update(ok=False, msg="مفيش صفقة مفتوحة على العملة دي")
                else:
                    price = float(ex.fetch_ticker(match)["last"])
                    if key == "status":       # paper daily trend: same record as its own exit, then no re-buy until the trend resets
                        pos = state["positions"].pop(match); pnl = (price - pos["entry"]) * pos["qty"]
                        state["history"].append({"symbol": match, "side": pos.get("side", "long"), "entry": pos["entry"], "exit": price, "qty": pos["qty"], "pnl": pnl,
                            "pnl_pct": pnl / (pos["entry"] * pos["qty"]) * 100, "reason": reason, "time": datetime.now(timezone.utc).isoformat(),
                            "type": "paper", "opened": pos.get("time"), "rank": pos.get("rank")})
                        st = state["stats"]; st["trades"] += 1; st["pnl"] += float(pnl); st["wins" if pnl > 0 else "losses"] += 1
                        state["last_trade"][match] = datetime.now(timezone.utc).isoformat()
                        state.setdefault("manual_hold", {})[match] = datetime.now(timezone.utc).isoformat()
                    elif key == "listing":
                        pnl = _listing_close(ex, state, match, price, reason)
                    else:
                        pnl = _paper_close(ex, state, match, price, reason)
                    save_state(state)
                    out.update(ok=True, msg="اتقفلت", price=price, pnl=round(pnl, 4))
            if out.get("ok"):
                log(f"🖐️ {key}: {reason} {sym} — {out.get('pnl'):+.4f}")
                notify(f"🖐️ قفل يدوي من الموقع ({key}): {sym.split(':')[0].replace('/USDT', '')}\nPnL {out.get('pnl'):+.2f}$ · Paper")
        except Exception as e:
            out.update(ok=False, msg=f"القفل فشل: {e}"); log(f"⚠️ {key} قفل يدوي {sym}: {e}")
        try:
            res_dir.mkdir(exist_ok=True); _write_json_atomic(res_dir / f"{rid}.json", out)
        except Exception as e: log(f"paper close result {rid}: {e}")

def write_live_status(state, prices, analyses=None):
    """What the site's admin page shows for the real-orders bot (not public)."""
    d = _ipc_dir()
    if not d: return
    pos = []
    for sym, p in state["positions"].items():
        px = prices.get(sym)
        exit_below = (((analyses or {}).get(sym) or {}).get("trend") or {}).get("exit_below")
        cs = _position_contract_size(p)
        funding = _funding_pnl(p)
        fee = _fee_rate(p)
        live_pnl = futures_net_pnl(p["entry"], px, p["qty"], cs, p.get("side", "long"), fee_rate=fee, funding_pnl=funding) if px and cs and funding is not None and fee is not None else None
        loss_at_sl = None
        if p.get("sl") and cs and funding is not None and fee is not None:
            loss_at_sl = futures_net_pnl(p["entry"], float(p["sl"]), p["qty"], cs, p.get("side", "long"), fee_rate=fee, funding_pnl=funding)
        pos.append({"symbol": sym.split(":")[0], "entry": p["entry"], "qty": p["qty"], "contract_size": cs, "sl": p.get("sl"), "price": px,
                    "exit_below": exit_below, "tp": p.get("tp"),
                    "loss_at_sl": round(loss_at_sl, 2) if loss_at_sl is not None else None,
                    "pnl": round(live_pnl, 4) if live_pnl is not None else None, "opened": p.get("time"),
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
                _require_verified_close(res)
            except Exception as e:
                log(f"⚠️ {symbol}: الترند وقف بس القفل فشل — هيحاول تاني الدورة الجاية: {e}")
                notify(f"⚠️ {symbol}: الترند وقف بس أمر القفل فشل — البوت هيحاول تاني. الوقف لسه على المنصة."); return
            exit_px, qty = res["price"], res["qty"]
        else:
            exit_px, qty = price, pos["qty"]
        if live:
            cs = _position_contract_size(pos)
            if cs is None:
                raise RuntimeError("missing contract_size for live PnL")
            pnl = futures_net_pnl(pos["entry"], exit_px, qty, cs, pos.get("side", "long"), fee_rate=_fee_rate(pos, required=True), funding_pnl=_funding_pnl(pos, required=True))
            margin = pos["entry"] * qty * cs / max(1, int(pos.get("leverage", CONFIG.get("leverage", 1))))
        else:
            pnl = (exit_px-pos["entry"])*qty
            margin = pos["entry"] * qty
        mode = _live_label() if live else "Paper"
        log(f"📉 اغلاق {symbol} — الترند وقف @ {exit_px:.6g} PnL {pnl:+.4f}")
        notify(f"📉 قفل {symbol} — الترند وقف\nدخول {pos['entry']:.6g} → خروج {exit_px:.6g}\nPnL {pnl:+.2f}$ ({mode})")
        state["history"].append({"symbol":symbol,"side":"long","entry":pos["entry"],"exit":exit_px,"qty":qty,"pnl":pnl,"pnl_pct":pnl/margin*100 if margin else 0,"reason":"الترند وقف","time":datetime.now(timezone.utc).isoformat(),"type":"live" if live else "paper","opened":pos.get("time"),"rank":pos.get("rank")})
        state["stats"]["trades"]+=1; state["stats"]["pnl"]+=float(pnl); state["stats"]["wins" if pnl>0 else "losses"]+=1
        state["positions"].pop(symbol,None); state["last_trade"][symbol]=datetime.now(timezone.utc).isoformat(); save_state(state)
        if live: _release_position_risk(symbol, pos)
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
    margin=position_size(price, ex, stop_price=sig.get("stop"))*sig["size"]
    if not live:
        try:
            res=place_order(ex,symbol,"long",margin,price)
            sl=res["price"]*(1-stt.STOP_SHARE/lev)
            state["positions"][symbol]={"side":"long","entry":res["price"],"qty":res["qty"],"cost":res["cost"],"notional":res.get("notional"),"contract_size":res.get("contract_size", 1.0),"contract_size_verified":res.get("contract_size_verified", False),"entry_fee_rate":res.get("entry_fee_rate"),"entry_fee_cost":res.get("entry_fee_cost"),"leverage":res.get("leverage",lev),
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
    activation_ok, activation_reason = _live_activation_gate("trend_daily")
    if not activation_ok:
        _ENTRY_BLOCK["reason"] = f"live activation blocked — {activation_reason}"
        log(f"⛔ {symbol} {_ENTRY_BLOCK['reason']}"); return
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
    equity = _fetch_equity_usdt(ex)
    if equity is None:
        log(f"⏸️ {symbol} equity unavailable — no entry"); return
    sl_estimate = price * (1 - stt.STOP_SHARE / lev)
    risk_usdt = _estimate_trade_risk_usdt(margin, lev, price, sl_estimate)
    allowed, reason = riskmgr.pre_trade_gate(
        RISK_PATH, strategy="trend_daily", symbol=symbol, side="long",
        risk_usdt=risk_usdt, notional_usdt=margin * lev, equity_usdt=equity,
        correlation_group=_correlation_group(symbol))
    if not allowed:
        log(f"⛔ {symbol} رفض بوابة المخاطر المركزية — {reason}"); return
    cid = "raqm-" + uuid.uuid4().hex[:27]   # per attempt — a fixed id per symbol matched trade #1's order on trade #2
    state.setdefault("pending_orders", {})[symbol] = cid; save_state(state)   # survives a crash between order and record
    try:
        res = place_order(ex, symbol, "long", margin, price, client_order_id=cid)
    except Exception as e:
        q = _exchange_position_qty(ex, symbol)
        if q is None:
            riskmgr.mark_reservation_recovery(RISK_PATH, strategy="trend_daily", symbol=symbol, reason="entry outcome unknown")
            state.setdefault("recovery_required", {})[symbol] = {"cid": cid, "reason": f"entry error, position unknown: {e}", "at": datetime.now(timezone.utc).isoformat()}
            save_state(state)
            notify(f"🚨 {symbol}: أمر الدخول رجّع خطأ ومقدرناش نعرف اتنفذ ولا لأ — راجع المنصة. البوت وقف أي دخول جديد."); return
        flat_ok, why = _entry_failed_flat(ex, symbol, cid, side="long") if q == 0 else (False, "")
        if flat_ok:
            riskmgr.rollback_reservation(RISK_PATH, strategy="trend_daily", symbol=symbol)
            state["pending_orders"].pop(symbol, None); save_state(state)
            log(f"فشل دخول {symbol}: {e}"); return
        if q == 0:   # one flat reading only — the order may have filled and the position not shown yet
            riskmgr.mark_reservation_recovery(RISK_PATH, strategy="trend_daily", symbol=symbol, reason=f"entry error, not proven flat: {why}")
            state.setdefault("recovery_required", {})[symbol] = {"cid": cid, "reason": f"entry error, not proven flat ({why}): {e}", "at": datetime.now(timezone.utc).isoformat()}
            _ENTRY_BLOCK["reason"] = "live entry outcome requires recovery"
            save_state(state)
            notify(f"🚨 {symbol}: أمر الدخول رجّع خطأ ومش متأكدين إنه ما اتنفذش ({why}) — راجع المنصة. البوت وقف أي دخول جديد.")
            return
        q, protected = _protect_unrecorded_entry(ex, symbol, "long", sl_estimate, cid)
        state.setdefault("recovery_required", {})[symbol] = {"cid": cid, "reason": f"entry error with an open position but no authoritative entry fill: {e}", "qty": q,
                                                             "emergency_stop": protected, "at": datetime.now(timezone.utc).isoformat()}
        riskmgr.mark_reservation_recovery(RISK_PATH, strategy="trend_daily", symbol=symbol, reason="open position without authoritative fill")
        _ENTRY_BLOCK["reason"] = "live entry fill evidence unavailable"
        save_state(state)
        notify(f"🚨 {symbol}: الصفقة ظهرت على المنصة لكن مفيش fill موثوق — دخلت recovery وممنوع تداول جديد. " +
               (f"اتحط وقف طوارئ عند {sl_estimate:.6g}" if protected else "ومن غير وقف — اقفلها يدوي"))
        return
    sl = res["price"] * (1 - stt.STOP_SHARE / lev)
    pos = {"side":"long","entry":res["price"],"qty":res["qty"],"cost":res["cost"],"notional":res.get("notional"),"contract_size":res.get("contract_size", 1.0),"contract_size_verified":res.get("contract_size_verified", False),"entry_fee_rate":res.get("entry_fee_rate"),"entry_fee_cost":res.get("entry_fee_cost"),"leverage":res.get("leverage",lev),
           "time":datetime.now(timezone.utc).isoformat(),"sl":sl,"tp":None,"breakeven":False,"trend":True,"rank":analysis.get("rank"),
           "clientOrderId": cid, "oco_ids": {"pos_id": cid}, "strategy": "trend_daily"}
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
            _require_verified_close(r)
            cs = _position_contract_size(pos)
            if cs is None:
                raise RuntimeError("missing contract_size for live PnL")
            pnl = futures_net_pnl(pos["entry"], r["price"], r["qty"], cs, pos.get("side", "long"), fee_rate=_fee_rate(pos, required=True), funding_pnl=_funding_pnl(pos, required=True))
            state["history"].append({"symbol":symbol,"side":"long","entry":pos["entry"],"exit":r["price"],"qty":r["qty"],"pnl":pnl,"pnl_pct":pnl/(pos["entry"]*r["qty"]*cs/max(1, int(pos.get("leverage", CONFIG.get("leverage", 1)))))*100,
                "reason":"الوقف اترفض — قفل فوري","time":datetime.now(timezone.utc).isoformat(),"type":"live","opened":pos["time"],"rank":pos.get("rank")})
            state["stats"]["trades"]+=1; state["stats"]["pnl"]+=float(pnl); state["stats"]["wins" if pnl>0 else "losses"]+=1
            state["last_trade"][symbol]=datetime.now(timezone.utc).isoformat(); save_state(state)
            riskmgr.release_open_risk(RISK_PATH, strategy="trend_daily", symbol=symbol)
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
    try:
        riskmgr.register_open_risk(RISK_PATH, strategy="trend_daily", symbol=symbol, side="long",
            risk_usdt=_estimate_trade_risk_usdt(margin, lev, res["price"], sl) or 0,
            notional_usdt=margin * lev, correlation_group=_correlation_group(symbol))
    except Exception as e:
        log(f"risk ledger register failed {symbol}: {e}")
    state["last_trade"][symbol]=datetime.now(timezone.utc).isoformat(); save_state(state)
    log(f"✅ 🟢 لونج {_live_label()} {symbol} ترند يومي x{lev} @ {res['price']:.6g} qty {res['qty']} وقف على المنصة {sl:.6g}")
    notify(f"🟢 لونج {symbol} — ترند يومي x{lev} ({_live_label()})\nدخول {res['price']:.6g} · هامش {margin:.2f}$\nوقف على المنصة {sl:.6g} · الخروج لما الترند يقف")

def try_enter(symbol, analysis, state, ex):
    """فيوتشر: لونج لو سكور > buy_threshold، شورت لو سكور < sell_threshold"""
    if not CONFIG.get("paper_trading") and _ENTRY_BLOCK["reason"] and not in_position(state, symbol):
        log(f"⛔ {symbol} دخول متوقف — {_ENTRY_BLOCK['reason']}")
        return
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
                    fq = normalize_filled_contracts(found)
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
                    _require_verified_close(res)
                    cs = _position_contract_size(pos)
                    if cs is None:
                        raise RuntimeError("missing contract_size for live PnL")
                    pnl = futures_net_pnl(entry, res["price"], res["qty"], cs, side, fee_rate=_fee_rate(pos, required=True), funding_pnl=_funding_pnl(pos, required=True))
                    pct=(pnl/(entry*res["qty"]*cs/max(1, int(pos.get("leverage", CONFIG.get("leverage", 1)))))*100) if entry*res["qty"] else 0
                    log(f"📉 اغلاق حقيقي {side} {symbol} @ {res['price']:.4f} PnL {pnl:+.4f}")
                    state["history"].append({"symbol":symbol,"side":side,"entry":entry,"exit":res["price"],"qty":res["qty"],"pnl":pnl,"pnl_pct":pct,"reason":"اشارة عكسية","time":datetime.now(timezone.utc).isoformat(),"type":"live"})
                state["stats"]["trades"]+=1; state["stats"]["pnl"]+=float(pnl)
                if pnl>0: state["stats"]["wins"]+=1
                else: state["stats"]["losses"]+=1
                state["positions"].pop(symbol,None); state["last_trade"][symbol]=datetime.now(timezone.utc).isoformat(); save_state(state)
                if not CONFIG["paper_trading"]: _release_position_risk(symbol, pos)
            except Exception as e:
                if not CONFIG["paper_trading"]:
                    state.setdefault("recovery_required", {})[symbol] = {"reason": f"reversal close accounting or protective cleanup unconfirmed: {e}", "at": datetime.now(timezone.utc).isoformat()}
                    _ENTRY_BLOCK["reason"] = "reversal close requires recovery"
                    save_state(state)
                log(f"فشل اغلاق {symbol} {side}: {e}")
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
        _f_df = None
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
        try:
            risk_sl, _risk_tp = dynamic_sl_tp(analysis["price"], side, _f_df)
        except Exception:
            risk_sl = None
        amount=position_size(analysis["price"], ex, stop_price=risk_sl)*analysis["amount_mult"]
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
            equity = _fetch_equity_usdt(ex)
            if equity is None:
                log(f"⏸️ {symbol} equity unavailable — no entry"); return
            risk_usdt = _estimate_trade_risk_usdt(amount, CONFIG.get("leverage", 5), price, risk_sl)
            allowed, reason = riskmgr.pre_trade_gate(
                RISK_PATH, strategy=_current_strategy_name(), symbol=symbol, side=side,
                risk_usdt=risk_usdt, notional_usdt=amount * CONFIG.get("leverage", 5), equity_usdt=equity,
                correlation_group=_correlation_group(symbol))
            if not allowed:
                log(f"⛔ {symbol} رفض بوابة المخاطر المركزية — {reason}"); return
        try:
            order_side="long" if side=="long" else "short"
            _f_df2 = _f_df if '_f_df' in locals() else fetch_ohlcv(symbol, CONFIG["timeframe"], limit=60, ex=ex)
            cid = "raqm-" + uuid.uuid5(uuid.NAMESPACE_URL, f"{_current_strategy_name()}|{symbol}|{side}").hex[:27]
            # pending flag for idempotent recovery (P0-05)
            state.setdefault("pending_orders", {})[symbol] = cid
            try: save_state(state)
            except: pass
            res=place_order(ex,symbol,order_side,amount,price, client_order_id=cid)
            sl, tp = dynamic_sl_tp(price, side, _f_df2)
            pos = {"side":side,"entry":res["price"],"qty":res["qty"],"cost":res["cost"],"notional":res.get("notional",amount*CONFIG.get("leverage",5)),"contract_size":res.get("contract_size", 1.0),"contract_size_verified":res.get("contract_size_verified", False),"entry_fee_rate":res.get("entry_fee_rate"),"entry_fee_cost":res.get("entry_fee_cost"),"leverage":res.get("leverage",CONFIG.get("leverage",5)),"time":datetime.now(timezone.utc).isoformat(),"sl":sl,"tp":tp,"breakeven":False, "clientOrderId": cid}
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
                    fr = {}
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
                        cleanup_ok = True
                        if oco:
                            try:
                                from backend.app.oco import cancel_oco_orders
                                cleanup_ok = bool(cancel_oco_orders(ex, symbol, pos_id=pos_id))
                            except Exception:
                                cleanup_ok = False
                        if not cleanup_ok:
                            pos["unprotected"] = True
                            pos["strategy"] = _current_strategy_name()
                            state["positions"][symbol] = pos
                            state.setdefault("recovery_required", {})[symbol] = {"cid": cid, "reason": "emergency flatten succeeded but protective cancellation is unconfirmed", "at": datetime.now(timezone.utc).isoformat()}
                            _ENTRY_BLOCK["reason"] = "protective cancellation requires recovery"
                            state.get("pending_orders", {}).pop(symbol, None)
                            save_state(state)
                            return
                        cs = _position_contract_size(pos)
                        try:
                            _refresh_fee_evidence(ex, symbol, pos, fr.get("raw"))
                            _refresh_funding_evidence(ex, symbol, pos)
                            if cs is None or not fr.get("price") or not fr.get("qty"):
                                raise RuntimeError("emergency close fill evidence incomplete")
                            pnl = futures_net_pnl(pos["entry"], fr["price"], fr["qty"], cs, side, fee_rate=_fee_rate(pos, required=True), funding_pnl=_funding_pnl(pos, required=True))
                        except Exception as e:
                            state["positions"][symbol] = pos
                            state.setdefault("recovery_required", {})[symbol] = {"cid": cid, "reason": f"emergency close accounting unavailable: {e}", "at": datetime.now(timezone.utc).isoformat()}
                            _ENTRY_BLOCK["reason"] = "emergency close accounting requires recovery"
                            save_state(state)
                            return
                        state["history"].append({"symbol": symbol, "side": side, "entry": pos["entry"], "exit": fr["price"], "qty": fr["qty"], "pnl": pnl, "funding_pnl": pos.get("funding_pnl"), "reason": "emergency flatten", "time": datetime.now(timezone.utc).isoformat(), "type": "live"})
                        state["stats"]["trades"] += 1
                        state["stats"]["pnl"] += float(pnl)
                        state["stats"]["wins" if pnl > 0 else "losses"] += 1
                        log(f"🔒 إغلاق طارئ {symbol} نجح — qty {flatten_qty} — PnL {pnl:+.4f}")
                        state.get("pending_orders", {}).pop(symbol, None)
                        state.get("recovery_required", {}).pop(symbol, None)
                        state["last_trade"][symbol] = datetime.now(timezone.utc).isoformat()
                        try: save_state(state)
                        except: pass
                        return
                    # still open on the exchange without a stop: the bot keeps managing it (its own SL/TP check)
                    # and no new entry anywhere until someone resolves it
                    pos["unprotected"] = True
                    pos["strategy"] = _current_strategy_name()
                    state["positions"][symbol] = pos
                    state.setdefault("recovery_required", {})[symbol] = {"cid": cid, "reason": "unprotected: " + reason, "qty": flatten_qty, "price": flatten_price, "at": datetime.now(timezone.utc).isoformat()}
                    state.get("pending_orders", {}).pop(symbol, None)
                    try:
                        riskmgr.register_open_risk(RISK_PATH, strategy=pos["strategy"], symbol=symbol, side=side,
                            risk_usdt=_estimate_trade_risk_usdt(amount, pos.get("leverage", CONFIG.get("leverage", 5)), flatten_price, None) or 0,
                            notional_usdt=amount * pos.get("leverage", CONFIG.get("leverage", 5)),
                            correlation_group=_correlation_group(symbol))
                    except Exception as e:
                        log(f"risk ledger register failed {symbol}: {e}")
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
            if not CONFIG["paper_trading"]:
                pos["strategy"] = _current_strategy_name()
                try:
                    riskmgr.register_open_risk(RISK_PATH, strategy=pos["strategy"], symbol=symbol, side=side,
                        risk_usdt=_estimate_trade_risk_usdt(amount, pos.get("leverage", CONFIG.get("leverage", 5)), res["price"], sl) or 0,
                        notional_usdt=amount * pos.get("leverage", CONFIG.get("leverage", 5)),
                        correlation_group=_correlation_group(symbol))
                except Exception as e:
                    log(f"risk ledger register failed {symbol}: {e}")
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
        except Exception as e:
            if not CONFIG.get("paper_trading"):
                try:
                    if "pos" in locals() and pos.get("qty"):
                        riskmgr.mark_reservation_recovery(RISK_PATH, strategy=pos.get("strategy") or _current_strategy_name(), symbol=symbol, reason=f"entry workflow ambiguous: {e}")
                    else:
                        riskmgr.rollback_reservation(RISK_PATH, strategy=_current_strategy_name(), symbol=symbol)
                except Exception as risk_exc:
                    log(f"risk reservation recovery failed {symbol}: {risk_exc}")
            log(f"فشل {side} {symbol}: {e}")


# ── Williams volatility breakout + Connors RSI-2: two paper bots on Binance's public market (research/traders_study.py,
#    traders_robustness.py, breakout_stop_hourly.py) ──
VB = {"top": 10, "k": 0.7, "ma": 20, "stop": 0.40, "slip": 0.001}
RSI2 = {"top": 10, "below": 5, "trend_ma": 200, "exit_ma": 5, "max_days": 10, "stop": 0.40}

def breakout_mode():
    """Paper volatility breakout (Larry Williams): each UTC day, among the top 10 by 30-day volume whose close is above
    its 20-day average, buy when the price trades 0.7 x yesterday's range above today's open; sell at the next day's
    open. No intraday stop (it cut profit in every hourly test), only the 40% guard before liquidation."""
    return "vol_breakout" in (CONFIG.get("enabled_strategies") or [])

def rsi2_mode():
    """Paper RSI-2 pullback (Larry Connors): at each daily close, among the top 10 by 30-day volume above their 200-day
    average, buy when the 2-day RSI is below 5; sell after a close above the 5-day average or 10 days, stop 40%."""
    return "rsi2_pullback" in (CONFIG.get("enabled_strategies") or [])

def _utc_day(now):
    return now.replace(hour=0, minute=0, second=0, microsecond=0)

def rsi_wilder(closes, n=2):
    s = pd.Series(closes, dtype=float); d = s.diff().fillna(0)
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return float(100.0 if dn.iloc[-1] == 0 else 100 - 100 / (1 + up.iloc[-1] / dn.iloc[-1]))

def _paper_open(state, sym, price, now, extra):
    lev = int(CONFIG.get("leverage", 2)); q = position_size(price) * lev / price
    state["positions"][sym] = {"side": "long", "entry": price, "qty": q, "leverage": lev, "time": now.isoformat(), "tp": None, **extra}
    return q


def _phase2_engine(state):
    return MultiLegExecutionEngine(STATE_PATH, risk_manager=riskmgr, risk_path=RISK_PATH,
                                   save_state=save_state,
                                   block=lambda reason: _ENTRY_BLOCK.__setitem__("reason", str(reason)))


def _phase2_live_basket(ex, state, strategy, intent, legs, *, reserve=True):
    """Execute a deterministic live basket and leave all ambiguity in recovery."""
    if CONFIG.get("paper_trading"):
        raise RuntimeError("Phase 2 live adapter called while paper trading is enabled")
    if binance_env() == "live" and os.getenv("ALLOW_LIVE_TRADING", "").strip().lower() != "true":
        _ENTRY_BLOCK["reason"] = "ALLOW_LIVE_TRADING is not enabled"; return None
    is_exit = bool(legs) and all(leg.get("action", "entry") == "exit" for leg in legs)
    if not is_exit:
        activation_ok, activation_reason = _live_activation_gate(strategy)
        if not activation_ok:
            _ENTRY_BLOCK["reason"] = f"live activation blocked — {activation_reason}"; return None
    if _ENTRY_BLOCK.get("reason") and not is_exit:
        return None
    if state.get("recovery_required") and not is_exit:
        return None
    equity = _fetch_equity_usdt(ex)
    if equity is None and not is_exit:
        _ENTRY_BLOCK["reason"] = "account equity unavailable — blocking new entries"; return None
    if not is_exit:
        tripped, reason = riskmgr.update_equity_and_check_kill_switch(RISK_PATH, equity)
        if tripped:
            _ENTRY_BLOCK["reason"] = f"Central Risk Manager kill switch is tripped — {reason}"; return None
    equity = equity or 1.0
    engine = _phase2_engine(state); fills = {}
    cycle_key = f"{strategy}:{intent}"
    cycles = state.setdefault("_execution_cycles", {})
    cycle_token = cycles.setdefault(cycle_key, uuid.uuid4().hex)
    def _lookup_pending(payload):
        symbols = [leg.get("symbol") for leg in payload.get("legs", []) if leg.get("symbol")]
        try:
            return ex.fetch_positions(symbols) if symbols else []
        except Exception as exc:
            return {"error": str(exc), "authoritative": False}
    def _resolve_pending(item):
        positions = item.get("positions")
        if isinstance(positions, dict) and positions.get("error"):
            return {"status": "recovery_required", "residual": [{"execution_id": item["execution_id"], "reason": positions["error"], "positions": positions}]}
        residual = [{"execution_id": item["execution_id"], "reason": "restart reconciliation requires exchange-confirmed compensation or manual residual recovery", "positions": positions, "legs": item["payload"].get("legs", [])}]
        if not positions or all(float((p.get("contracts") if isinstance(p, dict) else 0) or 0) == 0 for p in (positions or [])):
            return {"status": "compensated", "residual": []}
        return {"status": "recovery_required", "residual": residual}
    pending = engine.reconcile(position_lookup=_lookup_pending, resolve=_resolve_pending)
    unresolved = [row for row in pending if (row.get("resolution") or {}).get("status") == "recovery_required"]
    if unresolved:
        for row in unresolved:
            state.setdefault("recovery_required", {})[f"execution:{row['execution_id']}"] = {"reason": "restart reconciliation residual persisted", "residual": (row.get("resolution") or {}).get("residual"), "at": row["updated_at"]}
        _ENTRY_BLOCK["reason"] = "durable live execution residual requires recovery"; save_state(state); return None
    if pending:
        save_state(state)
    def execute_leg(leg):
        if leg.get("action", "entry") == "exit":
            result = close_live_position(ex, leg["symbol"], leg["position"], leg.get("price")); _require_verified_close(result)
            fills[leg["symbol"]] = result; return {**result, "qty": result.get("qty", leg["position"].get("qty"))}
        result = place_order(ex, leg["symbol"], leg["side"], leg["margin"], leg["price"], client_order_id=leg["client_order_id"])
        if float(result.get("qty", 0) or 0) <= 0: raise RuntimeError("leg returned no filled quantity")
        from backend.app.oco import place_oco_orders
        oco = place_oco_orders(ex, leg["symbol"], leg["side"], result["qty"], leg.get("sl"), leg.get("tp"), paper=False, pos_id=leg["client_order_id"])
        result = {**result, "oco": oco}
        authoritative_qty = _exchange_position_qty(ex, leg["symbol"], side=leg["side"])
        if authoritative_qty is None: raise RuntimeError("authoritative exchange position evidence unavailable")
        result["authoritative_qty"] = authoritative_qty
        result["authoritative_fill_qty"] = float(result.get("qty", 0) or 0)
        fills[leg["symbol"]] = result; return result
    def compensate(leg, result):
        if leg.get("action", "entry") == "exit": return {"confirmed": False, "reason": "closed exit leg cannot be compensated automatically"}
        close_side = "close_long" if leg["side"] == "long" else "close_short"
        closed = place_order(ex, leg["symbol"], close_side, 0, result.get("price", leg["price"]), close_qty=result.get("qty"), client_order_id=f"{leg['client_order_id']}-c"[:36])
        q = _exchange_position_qty(ex, leg["symbol"], side=leg["side"])
        if q is None or float(q or 0) != 0: raise RuntimeError("compensating close outcome ambiguous")
        # the unwound leg's own stop/target are still on the exchange: left there, a reduceOnly stop would close the
        # next position on this coin at a stale price (found by scripts/demo_e2e.py)
        try:
            from backend.app.oco import cancel_oco_orders
            cancel_oco_orders(ex, leg["symbol"], pos_id=leg["client_order_id"])
        except Exception as cancel_error:
            log(f"⚠️ {leg['symbol']}: الرجل اتقفلت بس أوامر الحماية بتاعتها ما اتلغتش: {cancel_error}")
            notify(f"⚠️ {leg['symbol']}: رجل اتقفلت تلقائياً بس أمر الوقف بتاعها ممكن يكون لسه على المنصة — راجعه")
        return {"confirmed": True, "close": closed}
    for leg in legs:
        if leg.get("action", "entry") == "exit":
            leg["requested_qty"] = float(leg["position"]["qty"])
        else:
            meta = _contract_meta(ex, leg["symbol"])
            requested = linear_contracts_from_margin(leg["margin"], int(CONFIG.get("leverage", 2)), leg["price"], meta["contract_size"])
            try: requested = float(ex.amount_to_precision(leg["symbol"], requested))
            except Exception: requested = float(requested)
            if requested <= 0: raise RuntimeError(f"invalid requested quantity for {leg['symbol']}")
            leg["requested_qty"] = requested
    def _persist_fills(filled):
        for leg, fill in filled:
            sym = leg["symbol"]
            if leg.get("action", "entry") == "exit":
                state["positions"].pop(sym, None)
                state["last_trade"][sym] = datetime.now(timezone.utc).isoformat()
                save_state(state)
                _release_position_risk(sym, leg["position"])
                continue
            oco = fill.get("oco") or {}
            state["positions"][sym] = {"side": leg["side"], "entry": fill["price"], "qty": fill["qty"], "cost": fill.get("cost"),
                "notional": fill.get("notional"), "contract_size": fill.get("contract_size"), "contract_size_verified": fill.get("contract_size_verified", False),
                "entry_fee_rate": fill.get("entry_fee_rate"), "entry_fee_cost": fill.get("entry_fee_cost"), "leverage": fill.get("leverage", CONFIG.get("leverage", 2)),
                "time": datetime.now(timezone.utc).isoformat(), "sl": leg.get("sl"), "tp": leg.get("tp"), "clientOrderId": leg["client_order_id"],
                "oco_ids": {"pos_id": leg["client_order_id"], "sl": oco.get("sl_id"), "tp": oco.get("tp_id")}, "strategy": strategy, **(leg.get("extra") or {})}
            riskmgr.register_open_risk(RISK_PATH, strategy=strategy, symbol=sym, side=leg["side"], risk_usdt=leg["risk_usdt"],
                notional_usdt=leg["notional_usdt"], correlation_group=leg.get("correlation_group"))
        save_state(state)
        cycles.pop(cycle_key, None)
        return True
    def protected(leg, result):
        if leg.get("action", "entry") == "exit": return True
        oco = result.get("oco") or {}; return not (oco.get("protection_missing") or oco.get("verify_failed") or oco.get("sl_unverified"))
    result = engine.execute(strategy=strategy, intent=intent, legs=legs, equity_usdt=equity, execute_leg=execute_leg,
                            compensate_leg=compensate, verify_protection=protected, state=state, reserve=reserve,
                            persist_fills=_persist_fills, cycle_token=cycle_token)
    if result.get("status") == "recovery_required":
        for item in result.get("residual", []):
            sym = item["leg"]["symbol"]
            state.setdefault("recovery_required", {})[sym] = {"reason": item.get("reason"), "execution_id": result.get("execution_id"), "at": datetime.now(timezone.utc).isoformat()}
        save_state(state)
    return result


def _phase2_leg(symbol, side, margin, price, sl, tp, strategy, order=0, extra=None):
    lev = int(CONFIG.get("leverage", 2))
    return {"symbol": symbol, "side": side, "margin": margin, "price": price, "sl": sl, "tp": tp,
            "risk_usdt": _estimate_trade_risk_usdt(margin, lev, price, sl), "notional_usdt": margin * lev,
            "correlation_group": _correlation_group(symbol), "strategy": strategy, "order": order, "extra": extra or {}}


def _protect_unrecorded_entry(ex, symbol, side, sl, cid):
    """An entry raised but the exchange shows a position: put a reduceOnly stop on the exchange quantity now. It can
    only shrink the position, so it is safe even though the fill isn't recorded; the position stays in recovery.
    Returns the exchange quantity (None = unknown, 0 = flat) and whether a stop is on the exchange."""
    q = _exchange_position_qty(ex, symbol, side=side)
    if not q or sl is None: return q, False
    try:
        from backend.app.oco import place_oco_orders
        oco = place_oco_orders(ex, symbol, side, q, sl, None, paper=False, pos_id=cid)
        return q, not oco.get("protection_missing") and not oco.get("verify_failed")
    except Exception as exc:
        log(f"⚠️ {symbol}: وقف الطوارئ فشل: {exc}"); return q, False

def _single_leg_live_entry(ex, state, symbol, side, margin, price, sl, tp, strategy, extra=None):

    """Fail-closed single-leg live entry shared by the Phase 1 adapters."""
    if CONFIG.get("paper_trading"):
        raise RuntimeError("live adapter called while paper trading is enabled")
    if binance_env() == "live" and os.getenv("ALLOW_LIVE_TRADING", "").strip().lower() != "true":
        _ENTRY_BLOCK["reason"] = "ALLOW_LIVE_TRADING is not enabled"
        return None
    activation_ok, activation_reason = _live_activation_gate(strategy)
    if not activation_ok:
        _ENTRY_BLOCK["reason"] = f"live activation blocked — {activation_reason}"
        return None
    if _ENTRY_BLOCK.get("reason") or state.get("recovery_required"):
        return None
    equity = _fetch_equity_usdt(ex)
    if equity is None:
        _ENTRY_BLOCK["reason"] = "account equity unavailable — blocking new entries"
        return None
    try:
        tripped, reason = riskmgr.update_equity_and_check_kill_switch(RISK_PATH, equity)
    except Exception as exc:
        _ENTRY_BLOCK["reason"] = f"risk ledger unavailable — blocking new entries: {exc}"
        return None
    if tripped:
        _ENTRY_BLOCK["reason"] = f"Central Risk Manager kill switch is tripped — {reason}"
        return None
    leverage = int(CONFIG.get("leverage", 1))
    risk_usdt = _estimate_trade_risk_usdt(margin, leverage, price, sl)
    allowed, reason = riskmgr.pre_trade_gate(
        RISK_PATH, strategy=strategy, symbol=symbol, side=side,
        risk_usdt=risk_usdt, notional_usdt=margin * leverage,
        equity_usdt=equity, correlation_group=_correlation_group(symbol))
    if not allowed:
        log(f"⛔ {symbol} رفض بوابة المخاطر المركزية — {reason}")
        return None
    cid = "raqm-" + uuid.uuid4().hex[:27]   # per attempt; pending_orders keeps it across a crash
    state.setdefault("pending_orders", {})[symbol] = cid
    save_state(state)
    try:
        res = place_order(ex, symbol, side, margin, price, client_order_id=cid)
        if float(res.get("qty", 0) or 0) <= 0:
            raise RuntimeError("entry returned no filled quantity")
    except Exception as exc:
        try:
            flat_ok, why = _entry_failed_flat(ex, symbol, cid, side=side)
            if flat_ok:
                riskmgr.rollback_reservation(RISK_PATH, strategy=strategy, symbol=symbol)
                state["pending_orders"].pop(symbol, None); save_state(state)
                return None
            riskmgr.mark_reservation_recovery(RISK_PATH, strategy=strategy, symbol=symbol, reason=f"entry outcome unknown: {why}")
        except Exception:
            pass
        q, protected = _protect_unrecorded_entry(ex, symbol, side, sl, cid)
        state.setdefault("recovery_required", {})[symbol] = {"cid": cid, "reason": f"entry outcome unknown: {exc}", "qty": q,
                                                             "emergency_stop": protected, "at": datetime.now(timezone.utc).isoformat()}
        _ENTRY_BLOCK["reason"] = "live entry outcome requires recovery"
        state["pending_orders"].pop(symbol, None); save_state(state)
        notify(f"🚨 {symbol}: أمر الدخول رجّع خطأ ومش متأكدين من نتيجته — " +
               (f"الصفقة ظاهرة على المنصة ({q}) واتحط لها وقف طوارئ عند {sl:.6g}" if protected else
                f"الصفقة ظاهرة على المنصة ({q}) ومن غير وقف — اقفلها يدوي" if q else "راجع المنصة") +
               ". البوت وقف أي دخول جديد.")
        return None
    pos = {"side": side, "entry": res["price"], "qty": res["qty"], "cost": res["cost"],
           "notional": res.get("notional"), "contract_size": res.get("contract_size"),
           "contract_size_verified": res.get("contract_size_verified", False),
           "entry_fee_rate": res.get("entry_fee_rate"), "entry_fee_cost": res.get("entry_fee_cost"),
           "leverage": res.get("leverage", leverage), "time": datetime.now(timezone.utc).isoformat(),
           "sl": sl, "tp": tp, "breakeven": False, "clientOrderId": cid,
           "oco_ids": {"pos_id": cid}, "strategy": strategy, **(extra or {})}
    try:
        from backend.app.oco import place_oco_orders
        oco = place_oco_orders(ex, symbol, side, res["qty"], sl, tp, paper=False, pos_id=cid)
    except Exception as exc:
        oco = {"protection_missing": True, "sl_error": str(exc)}
    pos["oco_ids"].update({"sl": oco.get("sl_id"), "tp": oco.get("tp_id")})
    state["pending_orders"].pop(symbol, None)
    if oco.get("protection_missing"):
        try:
            close_live_position(ex, symbol, pos, price)
        except Exception:
            pass
        pos["unprotected"] = True
        state["positions"][symbol] = pos
        state.setdefault("recovery_required", {})[symbol] = {"cid": cid, "reason": "protective stop missing", "at": datetime.now(timezone.utc).isoformat()}
        _ENTRY_BLOCK["reason"] = "protective stop requires recovery"
        save_state(state)
        return None
    state["positions"][symbol] = pos
    if oco.get("verify_failed"):
        pos["sl_unverified"] = True
        state.setdefault("recovery_required", {})[symbol] = {"cid": cid, "reason": oco.get("verify_warn"), "at": datetime.now(timezone.utc).isoformat()}
        _ENTRY_BLOCK["reason"] = "protective order verification requires recovery"
    riskmgr.register_open_risk(RISK_PATH, strategy=strategy, symbol=symbol, side=side,
        risk_usdt=risk_usdt or 0, notional_usdt=margin * leverage, correlation_group=_correlation_group(symbol))
    save_state(state)
    return pos


def _single_leg_live_exit(ex, state, symbol, price, reason):
    pos = state["positions"].get(symbol)
    if not pos:
        return False
    try:
        result = close_live_position(ex, symbol, pos, price)
        _require_verified_close(result)
        cs = _position_contract_size(pos)
        pnl = futures_net_pnl(pos["entry"], result["price"], result["qty"], cs, pos.get("side", "long"),
            fee_rate=_fee_rate(pos, required=True), funding_pnl=_funding_pnl(pos, required=True))
        state["history"].append({"symbol": symbol, "side": pos.get("side", "long"), "entry": pos["entry"],
            "exit": result["price"], "qty": result["qty"], "pnl": pnl, "reason": reason,
            "time": datetime.now(timezone.utc).isoformat(), "type": "live", "opened": pos.get("time")})
        state["stats"]["trades"] += 1; state["stats"]["pnl"] += float(pnl)
        state["stats"]["wins" if pnl > 0 else "losses"] += 1
        state["positions"].pop(symbol, None); state["last_trade"][symbol] = datetime.now(timezone.utc).isoformat()
        save_state(state)
        _release_position_risk(symbol, pos)
        return True
    except Exception as exc:
        state.setdefault("recovery_required", {})[symbol] = {"reason": f"live exit requires recovery: {exc}", "at": datetime.now(timezone.utc).isoformat()}
        _ENTRY_BLOCK["reason"] = "live exit requires recovery"
        save_state(state)
        return False


def _guard_stops(ex, state, prices, label):
    """The 40% protective stop (before liquidation at x2) between the bot's own exits."""
    for sym, pos in list(state["positions"].items()):
        try:
            price = float(ex.fetch_ticker(sym)["last"]); prices[sym] = price
            if price <= pos["sl"]:
                reason = f"وقف {pos['sl']:.6g}"
                if CONFIG.get("paper_trading"):
                    pnl = _paper_close(ex, state, sym, price, reason); save_state(state)
                    log(f"🔒 {label}: وقف {sym} @ {price:.6g} PnL {pnl:+.4f}")
                    notify(f"🔒 {label}: وقف {sym.split(':')[0]} @ {price:.6g}\nPnL {pnl:+.2f}$ · Paper")
                else:
                    _single_leg_live_exit(ex, state, sym, price, reason)
        except Exception as e: log(f"{label} {sym}: {e}")

def run_once_breakout(ex):
    V = VB; state = load_state(); now = datetime.now(timezone.utc); day = _utc_day(now); prices = {}
    if not CONFIG["paper_trading"]:
        reconcile_live(state, ex)
        if _ENTRY_BLOCK.get("reason"):
            save_state(state); return
    process_paper_closes(state, ex, "breakout")
    _guard_stops(ex, state, prices, "بريك أوت")
    if state.get("vb_day") != day.isoformat():
        # a new UTC day: yesterday's trades close at today's open, then today's triggers
        day_ms = int(day.timestamp() * 1000); closed = 0.0; n = 0
        for sym in list(state["positions"]):
            try:
                k = ex.fetch_ohlcv(sym, "1d", limit=2)
                px_open = float(k[-1][1]) if k and k[-1][0] == day_ms else float(ex.fetch_ticker(sym)["last"])
                if CONFIG.get("paper_trading"):
                    closed += _paper_close(ex, state, sym, px_open, "خروج افتتاح اليوم")
                    n += 1
                elif _single_leg_live_exit(ex, state, sym, px_open, "خروج افتتاح اليوم"):
                    closed += 1.0; n += 1
            except Exception as e: log(f"بريك أوت قفل {sym}: {e}")
        plan = {}
        for sym in volume_universe(ex, V["top"]):
            try:
                k = ex.fetch_ohlcv(sym, "1d", limit=V["ma"] + 3)
                if not k or k[-1][0] != day_ms: continue                  # today's candle not open yet
                closes = [r[4] for r in k[:-1]]; prev = k[-2]; rng = prev[2] - prev[3]
                avg = sum(closes[-V["ma"]:]) / V["ma"]
                plan[sym] = {"open": k[-1][1], "trigger": k[-1][1] + V["k"] * rng if rng > 0 else None, "above_ma": closes[-1] > avg,
                             "range": rng}
            except Exception as e: log(f"بريك أوت {sym}: {e}")
        state.update(vb_day=day.isoformat(), vb_plan=plan, vb_done=[]); save_state(state)
        armed = [f"{s.split('/')[0]} {p['trigger']:.6g}" for s, p in plan.items() if p["above_ma"] and p["trigger"]]
        log(f"📐 بريك أوت: يوم جديد — قفل {n} صفقة {closed:+.2f}$ | مستني اختراق: {', '.join(armed) or 'ولا عملة فوق متوسط 20'}")
        if n: notify(f"📐 بريك أوت (Paper): قفل {n} صفقة امبارح على افتتاح النهارده — {closed:+.2f}$")
    _guard_stops(ex, state, prices, "بريك أوت")
    plan = state.get("vb_plan") or {}
    for sym, p in plan.items():
        if not (p.get("above_ma") and p.get("trigger")) or sym in state["positions"] or sym in state.get("vb_done", []): continue
        try:
            price = prices.get(sym) or float(ex.fetch_ticker(sym)["last"]); prices[sym] = price
            if price < p["trigger"]: continue
            fill = price * (1 + V["slip"])
            if CONFIG.get("paper_trading"):
                _paper_open(state, sym, fill, now, {"sl": fill * (1 - V["stop"]), "trigger": p["trigger"],
                                                    "exit_at": (day + pd.Timedelta(days=1)).isoformat()})
                state.setdefault("vb_done", []).append(sym); save_state(state)
            else:
                pos = _single_leg_live_entry(ex, state, sym, "long", position_size(price, ex),
                    fill, fill * (1 - V["stop"]), None, "vol_breakout",
                    {"trigger": p["trigger"], "exit_at": (day + pd.Timedelta(days=1)).isoformat()})
                if pos:
                    state.setdefault("vb_done", []).append(sym); save_state(state)
            log(f"✅ 🟢 بريك أوت {sym} @ {fill:.6g} (الاختراق {p['trigger']:.6g})")
            notify(f"🟢 بريك أوت {sym.split(':')[0]} (Paper)\nاخترق {p['trigger']:.6g} — دخول {fill:.6g}\nخروج: افتتاح بكرة 00:00 UTC · وقف أمان {fill * (1 - V['stop']):.6g}")
        except Exception as e: log(f"بريك أوت دخول {sym}: {e}")
    write_simple_status("breakout", state, prices, V, {"day": state.get("vb_day"),
        "plan": [{"symbol": s.split(":")[0], "open": p["open"], "trigger": p["trigger"], "above_ma": p["above_ma"],
                  "entered": s in state.get("vb_done", []), "price": prices.get(s)} for s, p in plan.items()]})
    log(f"📊 بريك أوت: {len(state['positions'])} مفتوحة | PnL محقق {state['stats']['pnl']:+.4f}")

def run_once_rsi2(ex):
    R = RSI2; state = load_state(); now = datetime.now(timezone.utc); day = _utc_day(now); prices = {}
    if not CONFIG["paper_trading"]:
        reconcile_live(state, ex)
        if _ENTRY_BLOCK.get("reason"):
            save_state(state); return
    process_paper_closes(state, ex, "rsi2")
    _guard_stops(ex, state, prices, "RSI-2")
    if state.get("rsi2_day") != day.isoformat():
        # once per closed daily candle: exits first, then new entries at about today's open
        universe = volume_universe(ex, R["top"]); watch = []
        for sym in sorted(set(universe) | set(state["positions"])):
            try:
                k = ex.fetch_ohlcv(sym, "1d", limit=R["trend_ma"] + 15)[:-1]   # closed candles only
                c = [r[4] for r in k]
                if len(c) < R["exit_ma"] + 1: continue
                price = float(ex.fetch_ticker(sym)["last"]); prices[sym] = price
                if sym in state["positions"]:
                    pos = state["positions"][sym]
                    held = (day - _utc_day(datetime.fromisoformat(pos["time"]))).days
                    if c[-1] > sum(c[-R["exit_ma"]:]) / R["exit_ma"] or held >= R["max_days"]:
                        why = f"قفل فوق متوسط {R['exit_ma']} يوم" if c[-1] > sum(c[-R["exit_ma"]:]) / R["exit_ma"] else f"{R['max_days']} أيام"
                        if CONFIG.get("paper_trading"):
                            pnl = _paper_close(ex, state, sym, price, why)
                        else:
                            _single_leg_live_exit(ex, state, sym, price, why)
                        if sym in state["positions"]:
                            continue
                        log(f"📉 RSI-2: قفل {sym} @ {price:.6g} ({why}) PnL {pnl:+.4f}" if CONFIG.get("paper_trading") else f"📉 RSI-2: قفل {sym} @ {price:.6g} ({why})")
                    continue
                if sym not in universe or len(c) < R["trend_ma"]: continue
                r2 = rsi_wilder(c, 2); ma = sum(c[-R["trend_ma"]:]) / R["trend_ma"]
                watch.append({"symbol": sym.split(":")[0], "rsi2": round(r2, 1), "above_200": c[-1] > ma, "price": price})
                if r2 < R["below"] and c[-1] > ma:
                    sl = price * (1 - R["stop"])
                    if CONFIG.get("paper_trading"):
                        _paper_open(state, sym, price, now, {"sl": sl, "rsi2": round(r2, 1),
                                                             "exit_at": (day + pd.Timedelta(days=R["max_days"])).isoformat()})
                    else:
                        _single_leg_live_entry(ex, state, sym, "long", position_size(price, ex),
                            price, sl, None, "rsi2_pullback", {"rsi2": round(r2, 1),
                            "exit_at": (day + pd.Timedelta(days=R["max_days"])).isoformat()})
                    log(f"✅ 🟢 RSI-2 {sym} @ {price} (RSI-2 {r2:.1f} في ترند صاعد)")
                    notify(f"🟢 RSI-2 {sym.split(':')[0]} (Paper)\nRSI-2 {r2:.1f} وفوق متوسط 200 يوم — دخول {price:.6g}\nخروج: أول قفل يومي فوق متوسط 5 أيام (أقصى {R['max_days']} أيام) · وقف {price * (1 - R['stop']):.6g}")
            except Exception as e: log(f"RSI-2 {sym}: {e}")
        state.update(rsi2_day=day.isoformat(), rsi2_watch=watch); save_state(state)
    for sym in state["positions"]:
        if sym not in prices:
            try: prices[sym] = float(ex.fetch_ticker(sym)["last"])
            except Exception: pass
    write_simple_status("rsi2", state, prices, R, {"day": state.get("rsi2_day"), "watch": state.get("rsi2_watch", [])})
    log(f"📊 RSI-2: {len(state['positions'])} مفتوحة | PnL محقق {state['stats']['pnl']:+.4f}")

# ── trend-template breakout: what was left of Minervini / Darvas after research/vcp_deep.py (the contraction and the
#    breakout-volume conditions only hurt). Paper experiment — it added profit but not risk-adjusted return. ──
TB = {"top": 100, "L": 20, "exit_ma": 20, "stop": 0.40, "slip": 0.0005}

def tbreak_mode():
    """Paper trend-template breakout: at each daily close, among the top 100 by 30-day volume in a stage-2 uptrend
    (close > 50 > 150 > 200-day averages), buy when the close breaks the previous 20 days' high; sell after a close
    below the 20-day average; stop 40%."""
    return "trend_breakout" in (CONFIG.get("enabled_strategies") or [])

def run_once_tbreak(ex):
    T = TB; state = load_state(); now = datetime.now(timezone.utc); day = _utc_day(now); prices = {}
    if not CONFIG["paper_trading"]:
        reconcile_live(state, ex)
        if _ENTRY_BLOCK.get("reason"):
            save_state(state); return
    process_paper_closes(state, ex, "tbreak")
    _guard_stops(ex, state, prices, "اختراق الترند")
    if state.get("tb_day") != day.isoformat():
        universe = volume_universe(ex, T["top"]); watch = []; opened = []
        sma = lambda xs, n: sum(xs[-n:]) / n
        for sym in sorted(set(universe) | set(state["positions"])):
            try:
                k = ex.fetch_ohlcv(sym, "1d", limit=215)[:-1]          # closed candles only
                c = [r[4] for r in k]; h = [r[2] for r in k]
                if len(c) < T["exit_ma"] + 1: continue
                if sym in state["positions"]:
                    if c[-1] < sma(c, T["exit_ma"]):
                        price = float(ex.fetch_ticker(sym)["last"]); prices[sym] = price
                        if CONFIG.get("paper_trading"):
                            pnl = _paper_close(ex, state, sym, price, f"قفل تحت متوسط {T['exit_ma']} يوم")
                            log(f"📉 اختراق الترند: قفل {sym} @ {price:.6g} PnL {pnl:+.4f}")
                        else:
                            _single_leg_live_exit(ex, state, sym, price, f"قفل تحت متوسط {T['exit_ma']} يوم")
                        if sym in state["positions"]:
                            continue
                        log(f"📉 اختراق الترند: قفل {sym} @ {price:.6g}" if not CONFIG.get("paper_trading") else "")
                    continue
                if sym not in universe or len(c) < 201: continue
                m50, m150, m200 = sma(c, 50), sma(c, 150), sma(c, 200); hi = max(h[-T["L"] - 1:-1])
                if not (c[-1] > m50 > m150 > m200): continue
                watch.append({"symbol": sym.split(":")[0], "close": c[-1], "high": hi, "gap_pct": round((hi / c[-1] - 1) * 100, 1)})
                if c[-1] > hi:
                    price = float(ex.fetch_ticker(sym)["last"]) * (1 + T["slip"]); prices[sym] = price
                    if CONFIG.get("paper_trading"):
                        _paper_open(state, sym, price, now, {"sl": price * (1 - T["stop"]), "breakout": hi})
                    else:
                        _single_leg_live_entry(ex, state, sym, "long", position_size(price, ex),
                            price, price * (1 - T["stop"]), None, "trend_breakout", {"breakout": hi})
                    opened.append(f"{sym.split('/')[0]} {price:.6g}")
                    log(f"✅ 🟢 اختراق الترند {sym} @ {price:.6g} (قفل {c[-1]:.6g} فوق أعلى {T['L']} يوم {hi:.6g})")
            except Exception as e: log(f"اختراق الترند {sym}: {e}")
        if opened:
            notify(f"🟢 اختراق الترند (Paper) — {len(opened)} صفقة جديدة\n" + "\n".join(opened) +
                   f"\nخروج: قفل يومي تحت متوسط {T['exit_ma']} يوم · وقف 40%")
        state.update(tb_day=day.isoformat(), tb_watch=sorted(watch, key=lambda w: w["gap_pct"])[:15]); save_state(state)
    for sym in state["positions"]:
        if sym not in prices:
            try: prices[sym] = float(ex.fetch_ticker(sym)["last"])
            except Exception: pass
    write_simple_status("tbreak", state, prices, T, {"day": state.get("tb_day"), "watch": state.get("tb_watch", [])})
    log(f"📊 اختراق الترند: {len(state['positions'])} مفتوحة | PnL محقق {state['stats']['pnl']:+.4f}")

def write_simple_status(name, state, prices, rules, extra):
    """Public <name>.json for a long-only paper bot, in the shape the site reads for momentum.json."""
    out_dir = CONFIG.get("public_dir")
    if not out_dir: return
    pos = []
    for sym, p in state["positions"].items():
        price = prices.get(sym, p["entry"]); pnl = (price - p["entry"]) * p["qty"]
        margin = p["entry"] * p["qty"] / max(1, int(p.get("leverage", 2)))
        pos.append({"symbol": sym.split(":")[0], "id": sym.split("/")[0] + "USDT", "side": "long", "entry": p["entry"], "price": price,
                    "qty": p["qty"], "margin": round(margin, 2), "sl": p["sl"], "pnl": round(pnl, 4),
                    "pnl_pct": round(pnl / margin * 100, 2) if margin else 0, "opened": p["time"], "exit_at": p.get("exit_at")})
    st = state.get("stats", {})
    data = {"updated": datetime.now(timezone.utc).isoformat(), "mode": "paper" if CONFIG["paper_trading"] else "live", "rules": rules,
            "leverage": int(CONFIG.get("leverage", 2)), "margin": CONFIG.get("trade_amount_usdt"), "started": CONFIG.get("started_at"),
            "stats": {"closed": st.get("trades", 0), "wins": st.get("wins", 0), "losses": st.get("losses", 0),
                      "realized": round(float(st.get("pnl", 0)), 4), "unrealized": round(sum(x["pnl"] for x in pos), 4), "open": len(pos)},
            "positions": pos, **extra,
            "history": [{"symbol": h["symbol"].split(":")[0], "side": h.get("side", "long"), "entry": h["entry"], "exit": h["exit"], "pnl": round(h["pnl"], 4),
                         "reason": h.get("reason", ""), "time": h.get("time"), "opened": h.get("opened")}
                        for h in state.get("history", [])[-300:]][::-1]}
    try:
        d = Path(out_dir); tmp = d / f"{name}.json.tmp"
        tmp.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8"); tmp.replace(d / f"{name}.json")
    except Exception as e: log(f"public {name} status: {e}")

MARKET_DATA_METHODS = ("fetch_ohlcv", "fetch_ticker", "fetch_tickers")
_strategy_ex = {}

def strategy_exchange():
    """The exchange the portfolio strategies run on. Paper: Binance's public market (the research data is Binance's).
    Live / demo: the keyed account for orders, positions and balance — candles and prices still come from Binance's
    real public market, as in run_once (Demo Trading's own candles are its play-money activity). Before this, live
    mode handed these strategies the keyless public client: no order, balance or position call could ever work."""
    if "public" not in _strategy_ex: _strategy_ex["public"] = ccxt.binanceusdm({"enableRateLimit": True})
    if CONFIG["paper_trading"]: return _strategy_ex["public"]
    if "keyed" not in _strategy_ex:
        ex, err = get_exchange(auth=True)
        if err:
            log(f"⛔ LIVE من غير مفاتيح: {err} — البوت وقف"); notify(f"⛔ البوت الحقيقي وقف: {err}")
            raise SystemExit(2)
        for name in MARKET_DATA_METHODS: setattr(ex, name, getattr(_strategy_ex["public"], name))
        _strategy_ex["keyed"] = ex
    return _strategy_ex["keyed"]

def run_once():
    if breakout_mode(): return run_once_breakout(strategy_exchange())
    if rsi2_mode(): return run_once_rsi2(strategy_exchange())
    if tbreak_mode(): return run_once_tbreak(strategy_exchange())
    if ratio_mode(): return run_once_ratio(strategy_exchange())
    if momentum_mode(): return run_once_momentum(strategy_exchange())
    if listing_mode(): return run_once_listing(strategy_exchange())
    if trend_mode(): CONFIG["timeframe"]="1d"
    state=load_state()
    ex,err=get_exchange(auth=not CONFIG["paper_trading"])
    if err:
        # switching to paper here would "close" real positions only in state.json and leave them open on the exchange
        log(f"⛔ LIVE من غير مفاتيح: {err} — البوت وقف"); notify(f"⛔ البوت الحقيقي وقف: {err}")
        raise SystemExit(2)
    if CONFIG["paper_trading"]: process_paper_closes(state, ex, "status")
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
    if not CONFIG["paper_trading"] and ex.markets:
        symbols, allowed = _resolve_live_symbols(ex, symbols, allowed)
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
    if breakout_mode():
        V=VB
        log(f"=== بريك أوت التذبذب (Larry Williams): أعلى {V['top']} فوليوم فوق متوسط {V['ma']} يوم، دخول عند الافتتاح + {V['k']} × مدى امبارح، خروج افتتاح بكرة — {mode} | هامش {CONFIG['trade_amount_usdt']} USDT x{CONFIG.get('leverage',2)} ===")
        notify(f"▶️ بوت بريك أوت التذبذب اشتغل ({mode})\nأعلى {V['top']} عملة فوليوم · دخول عند اختراق الافتتاح + {V['k']} × مدى امبارح · خروج افتتاح اليوم التالي")
    elif tbreak_mode():
        T=TB
        log(f"=== اختراق الترند (Minervini/Darvas من غير الانكماش): أعلى {T['top']} فوليوم في ترند صاعد، دخول على كسر أعلى {T['L']} يوم، خروج تحت متوسط {T['exit_ma']} يوم — {mode} | هامش {CONFIG['trade_amount_usdt']} USDT x{CONFIG.get('leverage',2)} ===")
        notify(f"▶️ بوت اختراق الترند اشتغل ({mode}) — تجربة\nأعلى {T['top']} عملة فوليوم في ترند صاعد · دخول على كسر أعلى {T['L']} يوم · خروج تحت متوسط {T['exit_ma']} يوم")
    elif rsi2_mode():
        R=RSI2
        log(f"=== RSI-2 (Larry Connors): أعلى {R['top']} فوليوم فوق متوسط {R['trend_ma']} يوم، دخول لما RSI-2 تحت {R['below']}، خروج فوق متوسط {R['exit_ma']} أيام (أقصى {R['max_days']}) — {mode} | هامش {CONFIG['trade_amount_usdt']} USDT x{CONFIG.get('leverage',2)} ===")
        notify(f"▶️ بوت RSI-2 اشتغل ({mode})\nأعلى {R['top']} عملة فوليوم في ترند صاعد · شراء الهبوط لما RSI-2 تحت {R['below']} · خروج فوق متوسط {R['exit_ma']} أيام")
    elif ratio_mode():
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
    p.add_argument("--expect-env", default=None, choices=["live", "demo", "testnet"],
                   help="refuse to start unless BINANCE_ENV is exactly this (the testnet service passes testnet)")
    p.add_argument("--state", default=None, help="ملف الحالة (لتشغيل أكتر من بوت في نفس المجلد) — اللوج بيبقى بنفس الاسم .log")
    args=p.parse_args()
    if args.strategy: CONFIG["enabled_strategies"]=[s.strip() for s in args.strategy.split(",") if s.strip()]
    retired = [s for s in (CONFIG.get("enabled_strategies") or []) if s in RETIRED_STRATEGIES]
    if args.strategy and retired: p.error(f"الاستراتيجية دي اتلغت: {', '.join(retired)}")
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
        LOG_PATH=STATE_PATH.with_suffix(".log")   # next to the state (the live bot keeps both in state/, its code folder is read-only)
    elif listing_mode():
        STATE_PATH=Path(__file__).parent / "state_listing.json"; LOG_PATH=Path(__file__).parent / "state_listing.log"
    elif momentum_mode():
        STATE_PATH=Path(__file__).parent / "state_momentum.json"; LOG_PATH=Path(__file__).parent / "state_momentum.log"
    elif ratio_mode():
        STATE_PATH=Path(__file__).parent / "state_ratio.json"; LOG_PATH=Path(__file__).parent / "state_ratio.log"
    if args.paper and args.live: p.error("--paper و --live مع بعض؟ اختار واحد")
    if args.paper: CONFIG["paper_trading"]=True
    if args.expect_env and binance_env() != args.expect_env:
        p.error(f"BINANCE_ENV={binance_env()} لكن الخدمة متظبطة على {args.expect_env} — مش هيشتغل")
    if args.live:
        unsupported = [s for s in (CONFIG.get("enabled_strategies") or []) if s not in LIVE_READY_STRATEGIES]
        if unsupported:
            p.error(f"--live مش متاح لـ {', '.join(unsupported)} — الاستراتيجيات المتاحة: {', '.join(sorted(LIVE_READY_STRATEGIES))}")
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
