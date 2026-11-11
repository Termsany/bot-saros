"""the legacy indicator strategies, their filters and the SL/TP and regime helpers.
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


def wave_mode():
    """Wave Flats runs alone with its own entries, stops and targets (strategies_wave.py)."""
    return "wave_flats" in (bot.CONFIG.get("enabled_strategies") or [])

def candles_needed():
    return 1000 if bot.wave_mode() else 300   # the ZigZag needs earlier swings to find wave A

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
    if not bot.CONFIG.get("vol_filter"): return True
    avg=df.vol.rolling(20).mean().iloc[-1]
    if pd.isna(avg) or avg==0: return True
    return float(df.vol.iloc[-1]) >= float(avg) * 0.9

def htf_trend_ok(symbol, side, ex=None):
    """فلتر الترند الأكبر — لا تدخل عكس 4h"""
    if not bot.CONFIG.get("htf_filter"): return True
    htf=bot.CONFIG.get("htf_timeframe","4h")
    try:
        hdf=bot.fetch_ohlcv(symbol, htf, limit=60, ex=ex)
        # ترند 4h: SMA20 vs SMA50
        sma20=hdf.close.rolling(20).mean().iloc[-1]
        sma50=hdf.close.rolling(50).mean().iloc[-1]
        if pd.isna(sma20) or pd.isna(sma50): return True
        if side=="long" and sma20 < sma50: return False
        if side=="short" and sma20 > sma50: return False
        return True
    except:
        return True

def atr_value(df, period=14):
    h=df.high; l=df.low; c=df.close
    tr=pd.concat([h-l, (h-c.shift(1)).abs(), (l-c.shift(1)).abs()], axis=1).max(axis=1)
    atr=tr.rolling(period).mean()
    return float(atr.iloc[-1]) if pd.notna(atr.iloc[-1]) else float(c.iloc[-1]*0.01)

def regime_detect(df):
    """يكتشف هل السوق ترند ولا عرضي"""
    adx=bot.adx_value(df)
    c=df.close; sma20=c.rolling(20).mean(); std=c.rolling(20).std()
    bw=(std/sma20).iloc[-1] if pd.notna(sma20.iloc[-1]) and sma20.iloc[-1]!=0 else 0.02
    if adx > float(bot.CONFIG.get("regime_adx_trend",20)) and bw > 0.015:
        return "trend"
    elif adx < 15 or bw < 0.01:
        return "range"
    return "mixed"

def dynamic_sl_tp(price, side, df):
    """وقف/هدف ديناميكي حسب ATR"""
    if not bot.CONFIG.get("dynamic_sl_tp"):
        if side=="long": return price*(1-bot.CONFIG["stop_loss_pct"]), price*(1+bot.CONFIG["take_profit_pct"])
        else: return price*(1+bot.CONFIG["stop_loss_pct"]), price*(1-bot.CONFIG["take_profit_pct"])
    atr=bot.atr_value(df, int(bot.CONFIG.get("atr_period",14)))
    sl_mult=float(bot.CONFIG.get("atr_sl_mult",1.5)); tp_mult=float(bot.CONFIG.get("atr_tp_mult",3.0))
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
    wf.run_wave_flats(list(closed.open), list(closed.high), list(closed.low), list(closed.close), ms, bot.CONFIG["timeframe"], last_signal=sig)
    price=float(df.close.iloc[-1]); d=sig.get("dir",0)
    reason=f"{sig['kind']} — وقف {sig['stop']:.6g} هدف {(sig['tgt2'] or sig['tgt1']):.6g}" if d else "لا إعداد"
    sr_info=bot.sr_signal(df)[2]; rsi_info=bot.rsi_macd_signal(df)[2]
    return {"symbol":symbol,"price":price,"total":float(d),"decision":"شراء" if d==1 else "بيع" if d==-1 else "انتظار",
            "breakdown":{"wave_flats":(float(d),reason)},"amount_mult":1.0,
            "sl":sig.get("stop",price*(1-bot.CONFIG["stop_loss_pct"])),"tp":(sig.get("tgt2") or sig.get("tgt1") or price*(1+bot.CONFIG["take_profit_pct"])),
            "rsi":rsi_info["rsi"],"supports":sr_info["supports"],"resistances":sr_info["resistances"],
            "wave":sig or None,"time":datetime.now(timezone.utc).isoformat()}

def analyze(symbol, df=None, timeframe=None):
    if df is None: df=bot.fetch_ohlcv(symbol, timeframe or bot.CONFIG["timeframe"], limit=bot.candles_needed())
    if bot.trend_mode(): return bot.analyze_trend(symbol, df)
    if bot.wave_mode(): return bot.analyze_wave(symbol, df)
    results={}
    s1,r1,_=bot.ichimoku_signal(df); results["ichimoku"]=(s1,r1)
    s2,r2=bot.dow_signal(df); results["dow"]=(s2,r2)
    s3,r3,_=bot.gann_signal(df); results["gann"]=(s3,r3)
    s4,r4=bot.elliott_signal(df); results["elliott"]=(s4,r4)
    s5,r5=bot.classical_signal(df); results["classical"]=(s5,r5)
    s6,r6,_=bot.sr_signal(df); results["sr"]=(s6,r6)
    s7,r7,_=bot.rsi_macd_signal(df); results["rsi_macd"]=(s7,r7)
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
        _pw_path=Path(bot.__file__).parent / "ai_weights.json"
        if _pw_path.exists(): _pw=json.loads(_pw_path.read_text(encoding="utf-8"))
    except: pass
    s15,r15=adv.ai_ensemble_signal(df, _base, _pw); results["ai"]=(s15,r15)
    # Respect enabled_strategies filter
    enabled=bot.CONFIG.get("enabled_strategies")
    if enabled:
        total=sum(results[k][0]*bot.CONFIG["weights"][k] for k in enabled if k in results and k in bot.CONFIG["weights"])
        wsum=sum(bot.CONFIG["weights"][k] for k in enabled if k in bot.CONFIG["weights"]) or 1
        total/=wsum
        # Keep only enabled in results for cleaner output
        results={k:v for k,v in results.items() if k in enabled}
    else:
        total=sum(results[k][0]*bot.CONFIG["weights"][k] for k in bot.CONFIG["weights"] if k in results)
    if total>bot.CONFIG["strong_buy"]: decision="شراء قوي"
    elif total>bot.CONFIG["buy_threshold"]: decision="شراء"
    elif total<bot.CONFIG["strong_sell"]: decision="بيع قوي"
    elif total<bot.CONFIG["sell_threshold"]: decision="بيع"
    else: decision="انتظار"
    mult=1.5 if total>bot.CONFIG["strong_buy"] else 1.0
    # also extract SR for chart
    sr_info=bot.sr_signal(df)[2]
    rsi_info=bot.rsi_macd_signal(df)[2]
    price=float(df.close.iloc[-1])
    sl=price*(1-bot.CONFIG["stop_loss_pct"]); tp=price*(1+bot.CONFIG["take_profit_pct"])
    return {"symbol":symbol,"price":price,"total":round(total,4),"decision":decision,"breakdown":results,"amount_mult":mult,"sl":sl,"tp":tp,"rsi":rsi_info["rsi"],"supports":sr_info["supports"],"resistances":sr_info["resistances"],"time":datetime.now(timezone.utc).isoformat()}
