"""
Crypto Auto-Trading Bot — 7 Strategies + 20 High-Liquidity Pairs
إيشيموكو + داو + جان + موجي + كلاسيكي + دعوم/مقاومات + RSI/MACD
Paper Trading (وهمي) — يعرض الصفقات بـ entry/SL/TP
python bot.py --paper   (وهمي كل 60s)  |  python bot.py --once  (مرة واحدة)
python bot.py --dashboard  (يشغّل البوت + داشبورد http://localhost:8765)
"""
import ccxt, pandas as pd, numpy as np, time, json, os, threading, http.server, socketserver, webbrowser
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
    return ccxt.bybit(kwargs), None

STABLES = {"USDC", "FDUSD", "TUSD", "USDP", "BUSD", "DAI", "USDE", "USD1", "PAXG", "XAUT"}  # stablecoins, gold
_universe = {"key": None, "symbols": []}

def volume_universe(ex, n):
    """Top n USDT perpetuals by average USDT volume over the last 30 closed daily candles, among coins with
    at least 150 daily candles (the trend needs 120 days) — research/universe_study.py. Refreshed once a day."""
    key = (datetime.now(timezone.utc).date().isoformat(), n)
    if _universe["key"] == key: return _universe["symbols"]
    ex.load_markets()
    tickers = ex.fetch_tickers(params={"category": "linear"})
    cands = []
    for sym, t in tickers.items():
        m = ex.markets.get(sym) or {}
        info = m.get("info") or {}
        crypto = info.get("symbolType", "") in ("", "innovation")   # Bybit also lists stocks, ETFs, commodities, forex as USDT perps
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
                          "pnl_pct": round(pnl / margin * 100, 2) if margin else 0, "opened": pos.get("time")})
    history = [{"symbol": h["symbol"].split(":")[0], "entry": h.get("entry"), "exit": h.get("exit"), "pnl": round(float(h.get("pnl", 0)), 4),
                "reason": h.get("reason", ""), "time": h.get("time")} for h in state.get("history", [])[-200:]]
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
    closed=df.iloc[:-1]; on,size=stt.signal_now(list(closed.close))
    price=float(df.close.iloc[-1]); lev=int(CONFIG.get("leverage",2))
    sr_info=sr_signal(df)[2]; rsi_info=rsi_macd_signal(df)[2]
    reason=f"ترند صاعد — حجم {size*100:.0f}%" if on else "مفيش ترند صاعد"
    return {"symbol":symbol,"price":price,"total":1.0 if on else 0.0,"decision":"شراء" if on else "انتظار",
            "breakdown":{"trend_daily":(1.0 if on else 0.0,reason)},"amount_mult":1.0,
            "sl":price*(1-stt.STOP_SHARE/lev),"tp":None,"rsi":rsi_info["rsi"],"supports":sr_info["supports"],"resistances":sr_info["resistances"],
            "trend":{"on":on,"size":size,"ts":int(closed.ts.iloc[-1].value//10**6)},"time":datetime.now(timezone.utc).isoformat()}

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
        try: return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except: pass
    return {"positions":{},"last_trade":{},"stats":{"trades":0,"wins":0,"losses":0,"pnl":0},"history":[]}

def save_state(s): STATE_PATH.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")

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
    """يضبط الرافعة ونوع الهامش للفيوتشر — يتجاهل الخطأ لو سبوت"""
    if CONFIG.get("market")!="future": return
    lev = int(CONFIG.get("leverage", 5))
    mtype = CONFIG.get("margin_type", "ISOLATED")
    try: ex.set_leverage(lev, symbol)
    except: pass
    try: ex.set_margin_mode(mtype, symbol)
    except: pass
    try: ex.set_position_mode(False)  # one-way mode
    except: pass

def place_order(ex,symbol,side,amount_usdt,price):
    """side = long/short/close_long/close_short — يحسب الكمية من USDT * leverage"""
    is_future = CONFIG.get("market","future")=="future"
    lev = int(CONFIG.get("leverage",5)) if is_future else 1
    # notional = amount_usdt * leverage في الفيوتشر، لكن الهامش = amount_usdt
    notional = amount_usdt * lev if is_future else amount_usdt
    qty = notional / price
    try: qty=float(ex.amount_to_precision(symbol, qty))
    except: qty=round(qty,6)
    if CONFIG["paper_trading"]:
        return {"id":"paper-"+str(int(time.time()*1000)),"qty":qty,"price":price,"cost":qty*price,"notional":notional,"leverage":lev}
    ensure_futures_setup(ex, symbol)
    # ccxt unified: create_order with side buy/sell يفتح لونج/شورت حسب positionSide
    # للفيوتشر نستخدم create_order مع params
    if is_future:
        if side in ("long","close_short"):  # شراء = لونج أو إغلاق شورت
            params = {"positionSide": "LONG" if side=="long" else "SHORT"}
            # للونج: buy, لإغلاق الشورت: buy أيضا لكن reduceOnly
            if side=="close_short": params["reduceOnly"] = True
            order = ex.create_order(symbol, "market", "buy", qty, None, params)
        else:  # short / close_long
            params = {"positionSide": "SHORT" if side=="short" else "LONG"}
            if side=="close_long": params["reduceOnly"] = True
            order = ex.create_order(symbol, "market", "sell", qty, None, params)
        # fallback لو المنصة one-way mode (بدون positionSide)
        # ccxt سيعيد المحاولة بدون params تلقائيا لو فشل — نعالجها
    else:
        if side in ("long","close_short"): order=ex.create_market_buy_order(symbol,qty)
        else: order=ex.create_market_sell_order(symbol,qty)
    fq=float(order.get("filled",qty) or qty); ap=float(order.get("average",price) or price)
    return {"id":str(order.get("id","")),"qty":fq,"price":ap,"cost":fq*ap,"notional":notional,"leverage":lev,"raw":order}

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
            if not pos.get("breakeven") and sign*(price-wave["be"])>0:
                pos["sl"]=sl=entry; pos["breakeven"]=True; save_state(state)
                log(f"♻️ {symbol} {side} كسر قمة التصحيح {wave['be']:.6g} — الوقف لنقطة الدخول {entry:.6g}")
            # TP1: close half (Running/Expanded Flat only); paper only — LIVE is refused for Wave Flats
            if wave.get("tp1") and not wave.get("tp1_done") and sign*(price-wave["tp1"])>=0 and CONFIG["paper_trading"]:
                half=pos["qty"]/2; pnl=(price-entry)*half*sign
                state["history"].append({"symbol":symbol,"side":side,"entry":entry,"exit":price,"qty":half,"pnl":pnl,"pnl_pct":pnl/(entry*half)*100,"reason":f"TP1 نص الكمية {wave['tp1']:.6g}","time":datetime.now(timezone.utc).isoformat(),"type":"paper"})
                state["stats"]["pnl"]+=float(pnl); pos["qty"]-=half; wave["tp1_done"]=True; save_state(state)
                log(f"🎯 {symbol} {side} TP1 @ {price:.6g} — قفل نص الكمية PnL {pnl:+.4f}")
        # ♻️ Breakeven — بعد 50% للهدف ينقل الوقف لنقطة الدخول
        if CONFIG.get("breakeven_enabled") and not pos.get("breakeven") and not wave and not pos.get("trend"):
            trig_pct = float(CONFIG.get("breakeven_trigger_pct", 0.5))
            off = float(CONFIG.get("breakeven_offset_pct", 0.001))
            trig_price = entry + (tp - entry) * trig_pct if side=="long" else entry - (entry - tp) * trig_pct
            hit_be = (price >= trig_price) if side=="long" else (price <= trig_price)
            if hit_be:
                be_sl = entry * (1 + off) if side=="long" else entry * (1 - off)
                # لا تضيّق الوقف لو كان أضيق أصلاً
                if side=="long" and be_sl > sl: pos["sl"] = be_sl
                elif side=="short" and be_sl < sl: pos["sl"] = be_sl
                pos["breakeven"] = True
                sl = pos["sl"]
                try: save_state(state)
                except: pass
                log(f"♻️ {symbol} {side} حقق 50% للهدف @ {price:.4f} — نقل الوقف لنقطة الدخول {be_sl:.4f}")
                try:
                    from backend.app.telegram_bot import send_telegram as _tg
                    import asyncio as _aio
                    _aio.create_task(_tg(f"♻️ *Breakeven* {symbol} {side} — SL → {be_sl:.4f}"))
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
                state["history"].append({"symbol":symbol,"side":pos.get("side","long"),"entry":entry,"exit":price,"qty":qty,"pnl":pnl,"pnl_pct":pnl_pct,"reason":reason,"time":datetime.now(timezone.utc).isoformat(),"type":"paper"})
            else:
                close_side="close_long" if pos.get("side","long")=="long" else "close_short"; _lev=int(CONFIG.get("leverage",5)) if CONFIG.get("market","future")=="future" else 1; res=place_order(ex or get_exchange(auth=True)[0],symbol,close_side,qty*price/_lev,price); pnl=(res["price"]-entry)*res["qty"] if pos.get("side","long")=="long" else (entry-res["price"])*res["qty"]
                log(f"🔒 بيع حقيقي {symbol} @ {res['price']:.4f} PnL {pnl:+.4f}")
                state["history"].append({"symbol":symbol,"entry":entry,"exit":res["price"],"qty":res["qty"],"pnl":pnl,"pnl_pct":(res["price"]/entry-1)*100,"reason":reason,"time":datetime.now(timezone.utc).isoformat(),"type":"live"})
            state["stats"]["trades"]+=1; state["stats"]["pnl"]+=float(pnl)
            if pnl>0: state["stats"]["wins"]+=1
            else: state["stats"]["losses"]+=1
            closed.append(symbol)
        except Exception as e: log(f"فشل اغلاق {symbol}: {e}")
    for s in closed:
        state["positions"].pop(s,None); state["last_trade"][s]=datetime.now(timezone.utc).isoformat()
    if closed: save_state(state)
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

def try_enter_trend(symbol, analysis, state, ex):
    """Daily trend: buy at market when the last closed daily candle turns the trend on; sell when it turns off."""
    import strategies_trend as stt
    sig=analysis.get("trend"); price=analysis["price"]
    if not sig: return
    if in_position(state, symbol):
        if sig["on"]: return
        pos=state["positions"][symbol]
        if not CONFIG["paper_trading"]: log(f"⏸️ {symbol} الترند اليومي شغال Paper بس"); return
        pnl=(price-pos["entry"])*pos["qty"]
        log(f"📉 اغلاق {symbol} — الترند وقف @ {price:.6g} PnL {pnl:+.4f}")
        notify(f"📉 قفل {symbol} — الترند وقف\nدخول {pos['entry']:.6g} → خروج {price:.6g}\nPnL {pnl:+.2f}$ (Paper)")
        state["history"].append({"symbol":symbol,"side":"long","entry":pos["entry"],"exit":price,"qty":pos["qty"],"pnl":pnl,"pnl_pct":pnl/(pos["entry"]*pos["qty"])*100,"reason":"الترند وقف","time":datetime.now(timezone.utc).isoformat(),"type":"paper"})
        state["stats"]["trades"]+=1; state["stats"]["pnl"]+=float(pnl); state["stats"]["wins" if pnl>0 else "losses"]+=1
        state["positions"].pop(symbol,None); state["last_trade"][symbol]=datetime.now(timezone.utc).isoformat(); save_state(state)
        return
    if not analysis.get("in_universe", True): return   # not in the volume top list today: no new trade
    seen=state.setdefault("trend_seen",{})
    if not sig["on"] or seen.get(symbol)==sig["ts"]: return   # one entry per closed daily candle, like the backtest
    seen[symbol]=sig["ts"]; save_state(state)
    if not CONFIG["paper_trading"]:
        log(f"⏸️ {symbol} الترند اليومي شغال Paper بس — مفيش أوامر حقيقية"); return
    if len(state["positions"])>=CONFIG["max_open_positions"] or not daily_pnl_ok(state): return
    try:
        lev=int(CONFIG.get("leverage",2))
        res=place_order(ex,symbol,"long",position_size(price, ex)*sig["size"],price)
        sl=res["price"]*(1-stt.STOP_SHARE/lev)
        state["positions"][symbol]={"side":"long","entry":res["price"],"qty":res["qty"],"cost":res["cost"],"notional":res.get("notional"),"leverage":res.get("leverage",lev),
            "time":datetime.now(timezone.utc).isoformat(),"sl":sl,"tp":None,"breakeven":False,"trend":True}
        state["last_trade"][symbol]=datetime.now(timezone.utc).isoformat(); save_state(state)
        log(f"✅ 🟢 لونج وهمي {symbol} ترند يومي x{lev} @ {res['price']:.6g} حجم {sig['size']*100:.0f}% وقف حماية {sl:.6g}")
        notify(f"🟢 لونج {symbol} — ترند يومي x{lev} (Paper)\nدخول {res['price']:.6g} · حجم {sig['size']*100:.0f}% من ${position_size(price, ex)*lev:.0f}\nوقف حماية {sl:.6g} · الخروج لما الترند يقف")
    except Exception as e: log(f"فشل long {symbol}: {e}")

def try_enter(symbol, analysis, state, ex):
    """فيوتشر: لونج لو سكور > buy_threshold، شورت لو سكور < sell_threshold"""
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
                    close_side="close_long" if side=="long" else "close_short"
                    res=place_order(ex,symbol,close_side,qty*price,price)
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
            except Exception as e: log(f"فحص الرصيد: {e}")
        try:
            order_side="long" if side=="long" else "short"
            res=place_order(ex,symbol,order_side,amount,price)
            sl, tp = dynamic_sl_tp(price, side, _f_df if '_f_df' in locals() else fetch_ohlcv(symbol, CONFIG["timeframe"], limit=60, ex=ex))
            state["positions"][symbol]={"side":side,"entry":res["price"],"qty":res["qty"],"cost":res["cost"],"notional":res.get("notional",amount*CONFIG.get("leverage",5)),"leverage":res.get("leverage",CONFIG.get("leverage",5)),"time":datetime.now(timezone.utc).isoformat(),"sl":sl,"tp":tp,"breakeven":False}
            state["last_trade"][symbol]=datetime.now(timezone.utc).isoformat(); save_state(state)
            mode="وهمي" if CONFIG["paper_trading"] else "حقيقي"
            lev_txt=f" x{res.get('leverage',CONFIG.get('leverage',5))}" if CONFIG.get("market")=="future" else ""
            emoji="🟢 لونج" if side=="long" else "🔴 شورت"
            log(f"✅ {emoji} {mode} {symbol}{lev_txt} @ {res['price']:.6f} qty {res['qty']} SL {sl:.4f} TP {tp:.4f} سكور {total:+.3f} {analysis['decision']}")
        except Exception as e: log(f"فشل {side} {symbol}: {e}")


def run_once():
    if trend_mode(): CONFIG["timeframe"]="1d"
    state=load_state()
    ex,err=get_exchange(auth=not CONFIG["paper_trading"])
    if err: ex=ccxt.bybit({"enableRateLimit":True}); CONFIG["paper_trading"]=True
    prices={}; analyses={}
    try: symbols, allowed = cycle_symbols(ex, state)
    except Exception as e: log(f"قائمة العملات: {e}"); symbols, allowed = sorted(set(_universe["symbols"]) | set(state["positions"])), set(_universe["symbols"])
    for sym in symbols:
        try:
            df=fetch_ohlcv(sym, CONFIG["timeframe"], limit=candles_needed(), ex=ex)
            a=analyze(sym, df); a["in_universe"]=allowed is None or sym in allowed; analyses[sym]=a; prices[sym]=a["price"]
            bd=" | ".join(f"{k} {v[0]:+.2f}" for k,v in a["breakdown"].items())
            # اختصر SHIB/PEPE لعرض أوضح
            log(f"{sym:10s} @ {a['price']:.6g} سكور {a['total']:+.3f} {a['decision']:8s} | {bd} | SL {a['sl']:.4g} TP {a['tp']:.4g}" if a.get('tp') else f"{sym:10s} @ {a['price']:.6g} {a['decision']:8s} | {bd} | وقف حماية {a['sl']:.4g}")
        except Exception as e: log(f"{sym} فشل: {e}")
    if prices: check_sl_tp(state, prices, ex)
    for sym,a in analyses.items():
        try: try_enter(sym,a,state,ex)
        except Exception as e: log(f"دخول {sym}: {e}")
    write_public_status(state, analyses, allowed if allowed is not None else symbols)
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
    if trend_mode():
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
            url=f"https://api.binance.com/api/v3/klines?symbol={sym}&interval={interval}&limit={limit}"
            try:
                with urllib.request.urlopen(url, timeout=10) as r: body=r.read()
                self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Access-Control-Allow-Origin","*"); self.end_headers()
                self.wfile.write(body); return
            except Exception as e:
                self.send_response(502); self.end_headers(); self.wfile.write(json.dumps({"error":str(e)}).encode()); return
        return super().do_GET()
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin","*"); super().end_headers()

def start_dashboard_server(port=None):
    port=port or CONFIG["dashboard_port"]
    root=str(Path(__file__).parent)
    os.chdir(root)
    handler=lambda *a, **kw: DashHandler(*a, directory=root, **kw)
    with socketserver.TCPServer(("", port), handler) as httpd:
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
    if args.paper: CONFIG["paper_trading"]=True
    if args.live: CONFIG["paper_trading"]=False
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
