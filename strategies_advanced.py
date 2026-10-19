
"""
Raqm — 8 Advanced Strategies
SMC, VWAP+Volume, SuperTrend+ATR, Bollinger+Squeeze+StochRSI, Harmonic, ICT Killzone, HeikinAshi+ADX, AI Ensemble
Each returns score in [-1, +1] + reasons
"""
import pandas as pd, numpy as np

def smc_signal(df):
    """Smart Money: Order Block + FVG + BOS/CHoCH + Liquidity Sweep"""
    c=df.close; h=df.high; l=df.low
    price=c.iloc[-1]
    score=0; r=[]
    # BOS/CHoCH: last swing high/low break
    highs=[c.iloc[i] for i in range(2,len(c)-2) if c.iloc[i]==c.iloc[i-2:i+3].max()][-4:]
    lows=[l.iloc[i] for i in range(2,len(l)-2) if l.iloc[i]==l.iloc[i-2:i+3].min()][-4:]
    if len(highs)>=2 and price>highs[-2]: score+=0.5; r.append("BOS صاعد — كسر قمة")
    elif len(lows)>=2 and price<lows[-2]: score-=0.5; r.append("BOS هابط — كسر قاع")
    # FVG: 3-bar gap
    fvg_bull = (l.iloc[-1] > h.iloc[-3])  # gap up
    fvg_bear = (h.iloc[-1] < l.iloc[-3])
    if fvg_bull and c.iloc[-1]>c.iloc[-2]: score+=0.4; r.append("FVG صاعد")
    elif fvg_bear and c.iloc[-1]<c.iloc[-2]: score-=0.4; r.append("FVG هابط")
    # Order Block: last bearish/bullish engulfing near price
    if len(c)>=5 and c.iloc[-2]<c.iloc[-3] and c.iloc[-1]>c.iloc[-2] and (price - lows[-1])/price<0.02 if lows else False:
        score+=0.3; r.append("Order Block صاعد")
    if not r: r.append("SMC محايد")
    return float(np.clip(score,-1,1)), r

def vwap_volume_signal(df):
    """VWAP + Volume Profile: price vs VWAP + volume spike"""
    c=df.close; h=df.high; l=df.low; v=df.vol
    typical=(h+l+c)/3
    vwap=(typical*v).rolling(20).sum()/v.rolling(20).sum()
    vw=vwap.iloc[-1]; price=c.iloc[-1]
    score=0; r=[]
    if price>vw: score+=0.5; r.append(f"فوق VWAP {vw:.2f}")
    else: score-=0.5; r.append(f"تحت VWAP {vw:.2f}")
    vr=v.iloc[-1]/v.rolling(20).mean().iloc[-1] if v.rolling(20).mean().iloc[-1] else 1
    if vr>1.8 and score>0: score+=0.3; r.append(f"حجم متفجر {vr:.1f}x")
    elif vr>1.8 and score<0: score-=0.3; r.append(f"حجم بيعي {vr:.1f}x")
    return float(np.clip(score,-1,1)), r

def supertrend_atr_signal(df):
    """SuperTrend (ATR 10, mult 3) + ATR trend"""
    h=df.high; l=df.low; c=df.close
    atr=(h-l).rolling(10).mean()  # simplified ATR
    hl2=(h+l)/2
    upper=hl2+3*atr; lower=hl2-3*atr
    price=c.iloc[-1]
    # SuperTrend simplified: if price > upper -> bear, < lower -> bull? Use EMA ATR
    ema_atr=c.ewm(span=10).mean()
    score=0; r=[]
    if price > ema_atr.iloc[-1] + atr.iloc[-1]*1.5: score+=0.7; r.append("SuperTrend لونج")
    elif price < ema_atr.iloc[-1] - atr.iloc[-1]*1.5: score-=0.7; r.append("SuperTrend شورت")
    else: r.append("SuperTrend محايد")
    # ATR expanding = momentum
    if atr.iloc[-1] > atr.iloc[-5]*1.2: r.append("ATR يتوسع")
    return float(np.clip(score,-1,1)), r

def bollinger_squeeze_stochrsi_signal(df):
    """Bollinger Squeeze + StochRSI breakout"""
    c=df.close
    sma20=c.rolling(20).mean(); std=c.rolling(20).std()
    upper=sma20+2*std; lower=sma20-2*std
    bw=(upper-lower)/sma20  # bandwidth
    squeeze = bw.iloc[-1] < bw.rolling(50).quantile(0.2).iloc[-1] if bw.rolling(50).quantile(0.2).iloc[-1] else False
    price=c.iloc[-1]
    # StochRSI simplified: RSI position
    delta=c.diff(); gain=delta.where(delta>0,0).rolling(14).mean(); loss=(-delta.where(delta<0,0)).rolling(14).mean()
    rs=gain/loss; rsi=100-(100/(1+rs)); r=float(rsi.iloc[-1]) if pd.notna(rsi.iloc[-1]) else 50
    score=0; r_=[]
    if squeeze: r_.append("Squeeze — انفجار قريب")
    if price>upper.iloc[-1] and r>60: score+=0.8; r_.append("اختراق علوي + StochRSI قوي")
    elif price<lower.iloc[-1] and r<40: score-=0.8; r_.append("كسر سفلي + StochRSI ضعيف")
    elif r<30: score+=0.4; r_.append(f"RSI {r:.0f} تشبع بيعي")
    elif r>70: score-=0.4; r_.append(f"RSI {r:.0f} تشبع شرائي")
    else: r_.append(f"Bollinger محايد RSI {r:.0f}")
    return float(np.clip(score,-1,1)), r_

def harmonic_signal(df):
    """Harmonic simplified: Gartley/Bat via retracement ratios"""
    c=df.close.values
    # Find last 4 pivots
    pivots=[]
    for i in range(2,len(c)-2):
        if c[i]>c[i-1] and c[i]>c[i-2] and c[i]>c[i+1] and c[i]>c[i+2]: pivots.append((i,c[i],"H"))
        if c[i]<c[i-1] and c[i]<c[i-2] and c[i]<c[i+1] and c[i]<c[i+2]: pivots.append((i,c[i],"L"))
    pivots=pivots[-5:]
    if len(pivots)<4: return 0, ["Harmonic ناقص"]
    # Check XA retracement 0.618-0.786
    p0,p1,p2,p3=pivots[-4],pivots[-3],pivots[-2],pivots[-1]
    xa=abs(p1[1]-p0[1]); ab=abs(p2[1]-p1[1]); ret=ab/xa if xa else 0
    price=c[-1]
    score=0; r=[]
    if 0.618<=ret<=0.786:
        if p3[2]=="L" and price>p3[1]*1.01: score+=0.6; r.append(f"Gartley صاعد ret {ret:.2f}")
        elif p3[2]=="H" and price<p3[1]*0.99: score-=0.6; r.append(f"Gartley هابط ret {ret:.2f}")
    else: r.append(f"Harmonic ret {ret:.2f} محايد")
    return float(np.clip(score,-1,1)), r

def ict_killzone_signal(df):
    """ICT Killzone: London (07-10 UTC) / NY (12-15 UTC) + session high/low sweep"""
    c=df.close; h=df.high; l=df.low
    # Use last bar hour UTC
    try: hour=pd.to_datetime(df.ts.iloc[-1]).hour
    except: hour=datetime.now().hour
    score=0; r=[]
    in_kill = (7<=hour<=10) or (12<=hour<=15)
    if in_kill: r.append(f"Killzone {hour}:00 UTC نشط")
    else: r.append(f"خارج Killzone {hour}:00")
    # Session sweep: price beyond last 20 high/low
    hi=h.rolling(20).max().iloc[-2]; lo=l.rolling(20).min().iloc[-2]
    price=c.iloc[-1]
    if price>hi and in_kill: score-=0.5; r.append("Sweep قمة — انعكاس هابط")
    elif price<lo and in_kill: score+=0.5; r.append("Sweep قاع — انعكاس صاعد")
    return float(np.clip(score,-1,1)), r

def heikin_ashi_adx_signal(df):
    """Heikin Ashi trend + ADX strength"""
    o=df.open; h=df.high; l=df.low; c=df.close
    # Heikin Ashi
    ha_close=(o+h+l+c)/4
    ha_open=pd.Series(index=c.index, dtype=float)
    ha_open.iloc[0]=o.iloc[0]
    for i in range(1,len(c)): ha_open.iloc[i]=(ha_open.iloc[i-1]+ha_close.iloc[i-1])/2
    # ADX simplified via directional movement
    tr=pd.concat([h-l, (h-c.shift(1)).abs(), (l-c.shift(1)).abs()], axis=1).max(axis=1)
    atr=tr.rolling(14).mean()
    up=c.diff().where(lambda x: x>0, 0); down=(-c.diff()).where(lambda x: x>0, 0)
    plus_dm=up.rolling(14).mean()/atr*100; minus_dm=down.rolling(14).mean()/atr*100
    adx=(plus_dm-minus_dm).abs().rolling(14).mean()
    score=0; r=[]
    if ha_close.iloc[-1]>ha_open.iloc[-1] and ha_close.iloc[-2]>ha_open.iloc[-2]: score+=0.5; r.append("Heikin صاعد")
    elif ha_close.iloc[-1]<ha_open.iloc[-1] and ha_close.iloc[-2]<ha_open.iloc[-2]: score-=0.5; r.append("Heikin هابط")
    adxv=float(adx.iloc[-1]) if pd.notna(adx.iloc[-1]) else 15
    if adxv>25 and score>0: score+=0.3; r.append(f"ADX قوي {adxv:.0f}")
    elif adxv>25 and score<0: score-=0.3; r.append(f"ADX قوي {adxv:.0f}")
    elif adxv<15: score*=0.5; r.append(f"ADX ضعيف {adxv:.0f} — فلترة")
    return float(np.clip(score,-1,1)), r

def ai_ensemble_signal(df, breakdown_scores=None, perf_weights=None):
    """AI Ensemble: performance-weighted — يرجح الاستراتيجيات الكسبانة آخر 30 يوم"""
    if breakdown_scores is None: return 0, ["AI انتظار"]
    vals=list(breakdown_scores.values())
    if not vals: return 0, ["AI انتظار"]
    # perf_weights: dict {strategy_id: weight_boost} from backtest history
    if perf_weights:
        weighted=[breakdown_scores[k]*perf_weights.get(k,1.0) for k in breakdown_scores]
        avg=float(np.mean(weighted)) if weighted else 0
        # normalize by avg weight
        avg_w=float(np.mean(list(perf_weights.values()))) if perf_weights else 1
        if avg_w>0: avg/=avg_w
    else:
        avg=float(np.mean(vals))
    pos=sum(1 for v in vals if v>0.2); neg=sum(1 for v in vals if v<-0.2)
    score=avg
    if pos>=4 and avg>0: score=min(1, avg*1.3)
    elif neg>=4 and avg<0: score=max(-1, avg*1.3)
    # Regime hint
    regime=""
    if pos>=6: regime=" — إجماع قوي"
    elif neg>=6: regime=" — إجماع هابط قوي"
    r=[f"AI Ensemble إجماع {pos} صاعد / {neg} هابط{regime} — {score:+.2f}"]
    if perf_weights: r[0]+=f" (مرجح أداء)"
    return float(np.clip(score,-1,1)), r

def regime_detect_simple(df):
    """يكتشف ترند/عرضي للـ AI Ensemble"""
    try:
        h=df.high; l=df.low; c=df.close
        tr=pd.concat([h-l, (h-c.shift(1)).abs(), (l-c.shift(1)).abs()], axis=1).max(axis=1)
        atr=tr.rolling(14).mean().iloc[-1]
        c_ = c.iloc[-1]; sma20=c.rolling(20).mean().iloc[-1]
        if pd.isna(sma20) or pd.isna(atr): return "mixed"
        dist=abs(c_-sma20)/atr if atr else 0
        if dist>1.2: return "trend"
        elif dist<0.5: return "range"
        return "mixed"
    except: return "mixed"
