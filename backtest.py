"""
Backtest — 7 Strategies on BTC Futures LONG/SHORT
python backtest.py --symbol BTC/USDT --timeframe 1h --limit 1000 --leverage 5 --amount 20
python backtest.py --symbol BTC/USDT --timeframe 4h --limit 500
"""
import ccxt, pandas as pd, numpy as np, json, argparse, sys
from datetime import datetime, timezone
from pathlib import Path
import strategies_advanced as adv
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

CONFIG = {
    "weights": {"ichimoku":0.10,"dow":0.05,"gann":0.05,"elliott":0.08,"classical":0.05,"sr":0.05,"rsi_macd":0.12,"smc":0.10,"vwap":0.07,"supertrend":0.07,"bollinger":0.07,"harmonic":0.05,"ict":0.05,"heikin":0.05,"ai":0.04},
    "buy_threshold": 0.15, "strong_buy": 0.35, "sell_threshold": -0.15, "strong_sell": -0.35,
    "stop_loss_pct": 0.03, "take_profit_pct": 0.06,
    "trade_amount_usdt": 20, "leverage": 5, "fee_pct": 0.0004,
    "adx_threshold": 0, "vol_filter": False, "htf_filter": False, "htf_timeframe": "4h","dynamic_sl_tp": False, "atr_sl_mult": 2.0, "atr_tp_mult": 3.0,
}

def ichimoku_signal(df):
    h,l,c=df.high,df.low,df.close
    tenkan=(h.rolling(9).max()+l.rolling(9).min())/2; kijun=(h.rolling(26).max()+l.rolling(26).min())/2
    senkou_a=((tenkan+kijun)/2).shift(26); senkou_b=((h.rolling(52).max()+l.rolling(52).min())/2).shift(26)
    last=-1; score=0; reasons=[]
    try:
        if c.iloc[last]>senkou_a.iloc[last] and c.iloc[last]>senkou_b.iloc[last]: score+=1; reasons.append("up")
        elif c.iloc[last]<senkou_a.iloc[last] and c.iloc[last]<senkou_b.iloc[last]: score-=1; reasons.append("down")
        else: reasons.append("inside")
    except: reasons.append("n/a")
    score+=0.5 if tenkan.iloc[last]>kijun.iloc[last] else -0.5
    return max(-1,min(1,score/2)), reasons
def dow_signal(df):
    c=df.close.values
    highs=[c[i] for i in range(1,len(c)-1) if c[i]>c[i-1] and c[i]>c[i+1]][-5:]
    lows=[c[i] for i in range(1,len(c)-1) if c[i]<c[i-1] and c[i]<c[i+1]][-5:]
    if len(highs)<2 or len(lows)<2: return 0, ["n/a"]
    hh=sum(1 for i in range(1,len(highs)) if highs[i]>highs[i-1]); hl=sum(1 for i in range(1,len(lows)) if lows[i]>lows[i-1])
    return float(np.clip((hh+hl)/8*2-1,-1,1)), ["dow"]
def gann_signal(df):
    c=df.close; h=df.high; l=df.low; period=50
    hi=h.rolling(period).max().iloc[-1]; lo=l.rolling(period).min().iloc[-1]; rng=hi-lo if hi!=lo else 1
    price=c.iloc[-1]; slope=(c.iloc[-1]-c.iloc[-10])/10; avg=rng/period if period else 1
    return float(np.clip(slope/avg,-1,1)*0.7), ["gann"]
def elliott_signal(df):
    c=df.close.values; pivots=[]
    for i in range(2,len(c)-2):
        if c[i]>c[i-1] and c[i]>c[i-2] and c[i]>c[i+1] and c[i]>c[i+2]: pivots.append((i,c[i],"H"))
        if c[i]<c[i-1] and c[i]<c[i-2] and c[i]<c[i+1] and c[i]<c[i+2]: pivots.append((i,c[i],"L"))
    pivots=pivots[-9:]
    if len(pivots)<5: return 0, ["n/a"]
    lastH=max(p[1] for p in pivots if p[2]=="H"); lastL=min(p[1] for p in pivots if p[2]=="L")
    price=c[-1]; f05=lastH-(lastH-lastL)*0.5; f618=lastH-(lastH-lastL)*0.618
    if f618<price<f05 and c[-1]>c[-2]: return 0.8, ["fib rebound"]
    if price<f618 and c[-1]<c[-2]: return -0.6, ["fib break"]
    if price>lastH: return 0.5, ["breakout"]
    return 0.1, ["wait"]
def classical_signal(df):
    c=df.close; sma20=c.rolling(20).mean().iloc[-1]; sma50=c.rolling(50).mean().iloc[-1]; price=c.iloc[-1]; score=0
    if price>sma20>sma50: score+=0.6
    elif price<sma20<sma50: score-=0.6
    if len(c)>=20:
        slope=np.polyfit(range(20), c.values[-20:],1)[0]
        score+=np.clip(slope/(price*0.002),-0.4,0.4)
    return float(np.clip(score,-1,1)), ["classical"]
def sr_signal(df):
    h,l,c=df.high,df.low,df.close; price=c.iloc[-1]
    piv_hi=[h.iloc[i] for i in range(2,len(h)-2) if h.iloc[i]==h.iloc[i-2:i+3].max()][-6:]
    piv_lo=[l.iloc[i] for i in range(2,len(l)-2) if l.iloc[i]==l.iloc[i-2:i+3].min()][-6:]
    sups=sorted(set(round(x,2) for x in piv_lo)); ress=sorted(set(round(x,2) for x in piv_hi))
    sup=max([x for x in sups if x<price], default=None); res=min([x for x in ress if x>price], default=None)
    score=0
    if sup and (price-sup)/price<0.015: score+=0.7
    elif res and (res-price)/price<0.015: score-=0.7
    elif sup and res: score=np.clip((price-(sup+res)/2)/(res-sup)*0.3,-0.3,0.3)
    return float(np.clip(score,-1,1)), ["sr"]
def rsi_macd_signal(df):
    c=df.close; delta=c.diff(); gain=delta.where(delta>0,0).rolling(14).mean(); loss=(-delta.where(delta<0,0)).rolling(14).mean()
    rs=gain/loss; rsi=100-(100/(1+rs)); r=float(rsi.iloc[-1])
    ema12=c.ewm(span=12).mean(); ema26=c.ewm(span=26).mean(); macd=ema12-ema26; sig=macd.ewm(span=9).mean(); hist=macd-sig
    score=0
    if r<30: score+=0.8
    elif r>70: score-=0.8
    elif r<40: score+=0.3
    elif r>60: score-=0.3
    score+=0.5 if hist.iloc[-1]>0 else -0.5
    return float(np.clip(score,-1,1)), ["rsi"]
def score_at(df, enabled=None):
    s1,_=ichimoku_signal(df); s2,_=dow_signal(df); s3,_=gann_signal(df); s4,_=elliott_signal(df); s5,_=classical_signal(df); s6,_=sr_signal(df); s7,_=rsi_macd_signal(df)
    s8,_=adv.smc_signal(df); s9,_=adv.vwap_volume_signal(df); s10,_=adv.supertrend_atr_signal(df); s11,_=adv.bollinger_squeeze_stochrsi_signal(df)
    s12,_=adv.harmonic_signal(df); s13,_=adv.ict_killzone_signal(df); s14,_=adv.heikin_ashi_adx_signal(df)
    base={"ichimoku":s1,"dow":s2,"gann":s3,"elliott":s4,"classical":s5,"sr":s6,"rsi_macd":s7,"smc":s8,"vwap":s9,"supertrend":s10,"bollinger":s11,"harmonic":s12,"ict":s13,"heikin":s14}
    s15,_=adv.ai_ensemble_signal(df, base); base["ai"]=s15
    if enabled:
        # enabled is list of names to use; others weight 0
        total=sum(base[k]*CONFIG["weights"].get(k,0) for k in enabled if k in base)
        wsum=sum(CONFIG["weights"].get(k,0) for k in enabled if k in base) or 1
        total/=wsum  # normalize
        filtered={k:v for k,v in base.items() if k in enabled}
        return total, filtered
    total=sum(base[k]*CONFIG["weights"][k] for k in CONFIG["weights"] if k in base)
    return total, base
CACHE_DIR = Path(__file__).parent / ".cache"
CACHE_TTL_S = 3600  # 1 hour

def _cache_key(symbol, timeframe, limit, from_date, to_date):
    return f"{symbol.replace('/','')}_{timeframe}_{limit}_{from_date or ''}_{to_date or ''}.json"

def _cache_get(key):
    try:
        fp = CACHE_DIR / key
        if not fp.exists(): return None
        import time as _t
        if _t.time() - fp.stat().st_mtime > CACHE_TTL_S: return None
        data = json.loads(fp.read_text(encoding="utf-8"))
        df = pd.DataFrame(data, columns=["ts","open","high","low","close","vol"])
        df["ts"] = pd.to_datetime(df["ts"])
        return df
    except: return None

def _cache_put(key, df):
    try:
        CACHE_DIR.mkdir(exist_ok=True)
        # store as list of rows
        rows = df.copy()
        rows["ts"] = rows["ts"].astype(str)
        (CACHE_DIR / key).write_text(json.dumps(rows.values.tolist(), ensure_ascii=False), encoding="utf-8")
    except: pass

def fetch_ohlcv(symbol, timeframe, limit, from_date=None, to_date=None):
    # Try cache first (skip cache for from/to range fetches longer than TTL)
    _key = _cache_key(symbol, timeframe, limit, from_date, to_date)
    _cached = _cache_get(_key)
    if _cached is not None and len(_cached) >= limit * 0.9:
        print(f"cache hit {_key} ({len(_cached)} bars)")
        return _cached
    ex = ccxt.bybit({"enableRateLimit": True, "options": {"defaultType": "future"}})
    ex2 = ccxt.bybit({"enableRateLimit": True})  # bybit primary
    # If from/to provided, fetch by date range
    if from_date or to_date:
        import time as _time
        since = None; until = None
        if from_date:
            try: since = int(pd.to_datetime(from_date).tz_localize("UTC").timestamp()*1000)
            except: since = int(pd.to_datetime(from_date).timestamp()*1000)
        if to_date:
            try: until = int(pd.to_datetime(to_date).tz_localize("UTC").timestamp()*1000) + 24*3600*1000
            except: until = int(pd.to_datetime(to_date).timestamp()*1000) + 24*3600*1000
        # Fetch in chunks
        all_ohlcv=[]
        cur_since=since
        # Estimate timeframe ms
        tf_ms={"1m":60000,"15m":900000,"1h":3600000,"4h":14400000,"1d":86400000}.get(timeframe, 3600000)
        for _ in range(2):  # max 300 candles (300*60 min)
            try:
                chunk = ex.fetch_ohlcv(symbol, timeframe, since=cur_since, limit=300)
            except:
                try: chunk = ex2.fetch_ohlcv(symbol, timeframe, since=cur_since, limit=1000)
                except Exception as e2: print(f"fetch {symbol}: {e2}"); break
            if not chunk: break
            all_ohlcv.extend(chunk)
            if len(chunk)<1000: break
            cur_since=chunk[-1][0]+tf_ms
            if until and cur_since>=until: break
            _time.sleep(0.2)
        # Filter by until
        if until: all_ohlcv=[c for c in all_ohlcv if c[0] < until]
        if not all_ohlcv: raise RuntimeError(f"no data for {symbol} {from_date}→{to_date}")
        if len(all_ohlcv) > 300:
            all_ohlcv = all_ohlcv[-300:]  # keep most recent 300
        df=pd.DataFrame(all_ohlcv, columns=["ts","open","high","low","close","vol"])
        df["ts"]=pd.to_datetime(df["ts"], unit="ms")
        _cache_put(_key, df)
        return df
    for t in [timeframe]:
        # Retry on 418/429
        import time as _sleep
        last_err = None
        for attempt in range(3):
            try:
                ohlcv = ex.fetch_ohlcv(symbol, t, limit=limit)
                break
            except Exception as _e:
                last_err = _e
                msg = str(_e)
                if "418" in msg or "429" in msg or "Too much" in msg:
                    # Use cache if available (even stale)
                    _stale = None
                    try:
                        fp = CACHE_DIR / _key
                        if fp.exists():
                            import json as _js
                            data = _js.loads(fp.read_text(encoding="utf-8"))
                            _stale = data
                    except: pass
                    if _stale:
                        df = pd.DataFrame(_stale, columns=["ts","open","high","low","close","vol"])
                        df["ts"] = pd.to_datetime(df["ts"])
                        print(f"serving stale cache for {symbol} {t} due to ban")
                        return df
                    wait = 2 ** attempt
                    print(f"binance throttled, retry in {wait}s (attempt {attempt+1}/3)")
                    _sleep.sleep(wait)
                    continue
                raise
        # success — ohlcv already set
        df = pd.DataFrame(ohlcv, columns=["ts","open","high","low","close","vol"])
        df["ts"] = pd.to_datetime(df["ts"], unit="ms")
        _cache_put(_key, df)
        return df
    raise RuntimeError("fetch failed")


def adx_value_bt(df, period=14):
    import pandas as pd, numpy as np
    h=df.high; l=df.low; c=df.close
    tr=pd.concat([h-l, (h-c.shift(1)).abs(), (l-c.shift(1)).abs()], axis=1).max(axis=1)
    atr=tr.rolling(period).mean()
    up=c.diff().where(lambda x: x>0, 0); down=(-c.diff()).where(lambda x: x>0, 0)
    plus_dm=up.rolling(period).mean()/atr*100; minus_dm=down.rolling(period).mean()/atr*100
    dx=(plus_dm-minus_dm).abs()/(plus_dm+minus_dm).replace(0, np.nan)*100
    adx=dx.rolling(period).mean()
    return float(adx.iloc[-1]) if pd.notna(adx.iloc[-1]) else 20

def volume_ok_bt(df):
    avg=df.vol.rolling(20).mean().iloc[-1]
    if pd.isna(avg) or avg==0: return True
    return float(df.vol.iloc[-1]) >= float(avg) * 0.9

def htf_trend_ok_bt(full_df, idx, side):
    # Use SMA20/50 on 4h-equivalent: for 1h, look back 80 bars ~ 4h*20
    if not CONFIG.get("htf_filter"): return True
    if idx < 80: return True
    window=full_df.iloc[:idx+1]
    sma20=window.close.rolling(20).mean().iloc[-1]
    # Approximate HTF: SMA 50 on 1h ~ SMA 12 on 4h
    sma50=window.close.rolling(50).mean().iloc[-1]
    if pd.isna(sma20) or pd.isna(sma50): return True
    # Only block if strongly opposite (gap > 1%)
    gap=abs(sma20-sma50)/sma50 if sma50 else 0
    if gap < 0.02: return True
    if side=="long" and sma20 < sma50: return False
    if side=="short" and sma20 > sma50: return False
    return True

def run_backtest(df, amount_usdt=20, leverage=5, fee_pct=0.0004, warmup=60, enabled=None):
    CONFIG["trade_amount_usdt"]=amount_usdt; CONFIG["leverage"]=leverage; CONFIG["fee_pct"]=fee_pct
    sl_pct=CONFIG["stop_loss_pct"]; tp_pct=CONFIG["take_profit_pct"]
    bt_threshold=CONFIG["buy_threshold"]; st_threshold=CONFIG["sell_threshold"]
    trades=[]; position=None; equity=[0]; equity_curve=[{"ts": df.ts.iloc[0] if len(df)>0 else None, "equity": 0}]
    wins=0; losses=0

    for i in range(warmup, len(df)):
        window = df.iloc[:i+1]  # all data up to i
        price = float(df.close.iloc[i])
        ts = df.ts.iloc[i]
        # Score at this bar close
        total, breakdown = score_at(window, enabled)
        # Check SL/TP first if in position
        if position is not None:
            side=position["side"]; entry=position["entry"]
            sl=position["sl"]; tp=position["tp"]
            hit=False; reason=""
            if side=="long":
                if df.low.iloc[i] <= sl: hit=True; reason="SL"; price_exit=sl
                elif df.high.iloc[i] >= tp: hit=True; reason="TP"; price_exit=tp
                # also check reverse signal
                elif total < CONFIG["strong_sell"]: hit=True; reason="reverse"; price_exit=price
            else: # short
                if df.high.iloc[i] >= sl: hit=True; reason="SL"; price_exit=sl
                elif df.low.iloc[i] <= tp: hit=True; reason="TP"; price_exit=tp
                elif total > CONFIG["strong_buy"]: hit=True; reason="reverse"; price_exit=price
            if hit:
                # PnL with leverage: pnl = (exit-entry)*qty for long, (entry-exit)*qty for short
                # qty = notional/entry, notional = amount*leverage
                qty=position["qty"]
                if side=="long": pnl=(price_exit - entry)*qty
                else: pnl=(entry - price_exit)*qty
                fee = (entry*qty + price_exit*qty)*fee_pct
                pnl -= fee
                trades.append({"entry_ts":position["ts"],"exit_ts":ts,"side":side,"entry":entry,"exit":price_exit,"qty":qty,"pnl":pnl,"reason":reason,"score":total,"breakdown":breakdown})
                if pnl>0: wins+=1
                else: losses+=1
                equity.append(equity[-1]+pnl)
                equity_curve.append({"ts":ts,"equity":equity[-1]})
                position=None
                continue
            else:
                # ♻️ Breakeven 50% -> move SL to entry + offset.
                # Applied after this bar's SL/TP check so the new SL only counts from the next bar
                # (we can't know intrabar order of high/low — avoids an optimistic WR).
                if not position.get("breakeven"):
                    trig = entry + (tp - entry) * 0.5
                    hit_be = (df.high.iloc[i] >= trig) if side=="long" else (df.low.iloc[i] <= trig)
                    if hit_be:
                        be_sl = entry * 1.001 if side=="long" else entry * 0.999
                        if side=="long" and be_sl > sl: position["sl"] = be_sl
                        if side=="short" and be_sl < sl: position["sl"] = be_sl
                        position["breakeven"] = True
                # unrealized
                qty=position["qty"]
                if side=="long": upnl=(price - entry)*qty
                else: upnl=(entry - price)*qty
                equity_curve.append({"ts":ts,"equity":equity[-1]+upnl})
                continue
        # No position — try to enter (with week1 filters)
        if position is None:
            side=None
            if total > bt_threshold: side="long"
            elif total < st_threshold: side="short"
            if side:
                # ADX filter
                try:
                    adx_v=adx_value_bt(window)
                    if adx_v < 10:
                        equity_curve.append({"ts":ts,"equity":equity[-1]})
                        continue
                    if CONFIG.get("vol_filter") and not volume_ok_bt(window):
                        equity_curve.append({"ts":ts,"equity":equity[-1]})
                        continue
                    _reg=regime_detect_bt(window)
                    if _reg=="range" and abs(total) < 0.30:
                        equity_curve.append({"ts":ts,"equity":equity[-1]})
                        continue
                    if not htf_trend_ok_bt(df, i, side):
                        equity_curve.append({"ts":ts,"equity":equity[-1]})
                        continue
                except:
                    pass
            if side:
                # Enforce max one position at a time for backtest
                notional = amount_usdt * leverage
                qty = notional / price
                fee_entry = notional * fee_pct
                # cost is margin (amount), but we track PnL only
                sl, tp = dynamic_sl_tp_bt(price, side, window)
                position={"side":side,"entry":price,"qty":qty,"sl":sl,"tp":tp,"ts":ts,"fee_entry":fee_entry}
                equity_curve.append({"ts":ts,"equity":equity[-1]})
                continue
        equity_curve.append({"ts":ts,"equity":equity[-1]})

    # Close any open at last price
    if position is not None:
        price=float(df.close.iloc[-1]); entry=position["entry"]; side=position["side"]; qty=position["qty"]
        if side=="long": pnl=(price-entry)*qty
        else: pnl=(entry-price)*qty
        fee=(entry*qty+price*qty)*fee_pct; pnl-=fee
        trades.append({"entry_ts":position["ts"],"exit_ts":df.ts.iloc[-1],"side":side,"entry":entry,"exit":price,"qty":qty,"pnl":pnl,"reason":"close","score":0,"breakdown":{}} )
        if pnl>0: wins+=1
        else: losses+=1
        equity.append(equity[-1]+pnl)

    total_pnl=sum(t["pnl"] for t in trades)
    win_rate=(wins/(wins+losses)*100) if (wins+losses)>0 else 0
    # Metrics
    returns = [t["pnl"] for t in trades]
    avg_win = np.mean([r for r in returns if r>0]) if any(r>0 for r in returns) else 0
    avg_loss = np.mean([r for r in returns if r<0]) if any(r<0 for r in returns) else 0
    pf = abs(sum(r for r in returns if r>0) / sum(r for r in returns if r<0)) if any(r<0 for r in returns) else float("inf")
    # Max drawdown
    eq = [e["equity"] for e in equity_curve]
    peak=eq[0] if eq else 0; max_dd=0
    for v in eq:
        if v>peak: peak=v
        dd=peak-v
        if dd>max_dd: max_dd=dd
    return {"trades":trades,"equity_curve":equity_curve,"stats":{"total":len(trades),"wins":wins,"losses":losses,"win_rate":win_rate,"pnl":total_pnl,"avg_win":avg_win,"avg_loss":avg_loss,"profit_factor":pf,"max_dd":max_dd,"equity":eq}}


# === Phase 1: ATR + Regime + Dynamic SL/TP ===

def atr_value_bt2(df, period=14):
    h=df.high; l=df.low; c=df.close
    tr=pd.concat([h-l, (h-c.shift(1)).abs(), (l-c.shift(1)).abs()], axis=1).max(axis=1)
    atr=tr.rolling(period).mean()
    return float(atr.iloc[-1]) if pd.notna(atr.iloc[-1]) else float(c.iloc[-1]*0.01)

def regime_detect_bt(df):
    adx=adx_value_bt(df)
    c=df.close; sma20=c.rolling(20).mean(); std=c.rolling(20).std()
    bw=(std/sma20).iloc[-1] if pd.notna(sma20.iloc[-1]) and sma20.iloc[-1]!=0 else 0.02
    if adx > 20 and bw > 0.015: return "trend"
    elif adx < 15 or bw < 0.01: return "range"
    return "mixed"

def dynamic_sl_tp_bt(price, side, df):
    # Dynamic SL/TP - can disable via CONFIG dynamic_sl_tp=False
    if not CONFIG.get("dynamic_sl_tp", False):
        if side=="long": return price*(1-0.03), price*(1+0.06)
        else: return price*(1+0.03), price*(1-0.06)
    atr=atr_value_bt2(df, 14)
    price=float(price)
    atr=max(price*0.008, min(price*0.03, atr))
    if side=="long": sl=price - atr*2.0; tp=price + atr*3.0
    else: sl=price + atr*2.0; tp=price - atr*3.0
    if side=="long":
        if (price-sl)/price < 0.01: sl=price*0.99
        if (tp-price)/price < 0.015: tp=price*1.02
    else:
        if (sl-price)/price < 0.01: sl=price*1.01
        if (price-tp)/price < 0.015: tp=price*0.98
    return sl, tp

def walk_forward_splits(n, train_ratio=0.7, n_splits=3):
    """يقسم الداتا ل Walk-Forward: كل Split تدريب 70% + اختبار 30% متداخلة"""
    splits=[]
    total=n
    window=int(total / (n_splits + 0.5))
    if window < 100: return [(0, int(n*train_ratio), int(n*train_ratio), n)]
    step=int(window * 0.5)
    for i in range(n_splits):
        train_start=i*step
        train_end=train_start + int(window*train_ratio)
        test_start=train_end
        test_end=min(test_start + int(window*(1-train_ratio)), n)
        if test_end - test_start < 50: break
        if train_end >= n or test_start >= n: break
        splits.append((train_start, train_end, test_start, test_end))
    if not splits: splits=[(0, int(n*train_ratio), int(n*train_ratio), n)]
    return splits

def kelly_position_size(win_rate, avg_win, avg_loss, balance, max_risk=0.02):
    """Kelly: f* = p - q/b  حيث b = avg_win/|avg_loss|"""
    if avg_loss==0 or win_rate==0: return balance * 0.02
    p=win_rate/100; q=1-p; b=abs(avg_win/avg_loss) if avg_loss!=0 else 1
    if b==0: return balance * 0.02
    f = p - q/b
    f = max(0.005, min(max_risk, f * 0.5))  # half-kelly cap 2%
    return balance * f

def monte_carlo_dd(trades, n_sim=1000, seed=42):
    """Monte Carlo على ترتيب الصفقات لحساب Max DD المحتمل"""
    import random
    random.seed(seed)
    base = [t["pnl"] for t in trades]
    if not base: return 0, 0
    dds=[]
    for _ in range(n_sim):
        random.shuffle(base)
        peak=0; cur=0; max_dd=0
        for pnl in base:
            cur+=pnl
            if cur>peak: peak=cur
            dd=peak-cur
            if dd>max_dd: max_dd=dd
        dds.append(max_dd)
    dds.sort()
    return dds[int(len(dds)*0.5)], dds[int(len(dds)*0.95)]


def print_report(res, df, symbol, timeframe, amount, leverage):
    s=res["stats"]
    print("="*60)
    print(f"BACKTEST — {symbol} {timeframe}  |  {len(df)} bars  |  {df.ts.iloc[0].date()} → {df.ts.iloc[-1].date()}")
    print(f"رأس الصفقة {amount} USDT  رافعة x{leverage}  SL {CONFIG['stop_loss_pct']*100:.0f}%  TP {CONFIG['take_profit_pct']*100:.0f}%  عمولة {CONFIG['fee_pct']*100:.3f}%")
    print("-"*60)
    print(f"الصفقات: {s['total']}  |  رابحة: {s['wins']}  |  خاسرة: {s['losses']}  |  نسبة الربح: {s['win_rate']:.1f}%")
    print(f"إجمالي PnL: {s['pnl']:+.2f} USDT  |  متوسط ربح: {s['avg_win']:+.2f}  |  متوسط خسارة: {s['avg_loss']:+.2f}")
    print(f"Profit Factor: {s['profit_factor']:.2f}  |  Max DD: {s['max_dd']:.2f} USDT")
    print("-"*60)
    if s["total"]>0:
        # Per side
        longs=[t for t in res["trades"] if t["side"]=="long"]; shorts=[t for t in res["trades"] if t["side"]=="short"]
        lw=sum(1 for t in longs if t["pnl"]>0); sw=sum(1 for t in shorts if t["pnl"]>0)
        print(f"LONG:  {len(longs)}  رابح {lw}  PnL {sum(t['pnl'] for t in longs):+.2f}")
        print(f"SHORT: {len(shorts)} رابح {sw}  PnL {sum(t['pnl'] for t in shorts):+.2f}")
        print("-"*60)
        print(f"{'دخول':12s} {'خروج':12s} {'اتجاه':6s} {'دخول':8s} {'خروج':8s} {'PnL':8s} السبب")
        for t in res["trades"][-20:]:
            ets=t["entry_ts"].strftime("%m-%d %H:%M") if hasattr(t["entry_ts"],"strftime") else str(t["entry_ts"])[:16]
            xts=t["exit_ts"].strftime("%m-%d %H:%M") if hasattr(t["exit_ts"],"strftime") else str(t["exit_ts"])[:16]
            print(f"{ets:12s} {xts:12s} {t['side']:6s} {t['entry']:8.2f} {t['exit']:8.2f} {t['pnl']:+8.2f} {t['reason']}")
    print("="*60)

def plot_results(df, res, symbol, timeframe, out_path):
    fig, axes = plt.subplots(3, 1, figsize=(14,10), sharex=True, gridspec_kw={"height_ratios":[3,1,1]})
    ax1, ax2, ax3 = axes
    # Price + trades
    ax1.plot(df.ts, df.close, color="#8a9ab0", linewidth=0.8, label="BTC close")
    for t in res["trades"]:
        col="#00d395" if t["pnl"]>0 else "#ff3b5c"
        marker="^" if t["side"]=="long" else "v"
        ax1.scatter(t["entry_ts"], t["entry"], color="#00d395" if t["side"]=="long" else "#ff3b5c", marker=marker, s=60, zorder=5, edgecolors="white", linewidths=0.5)
        ax1.scatter(t["exit_ts"], t["exit"], color=col, marker="o", s=40, zorder=5, edgecolors="white", linewidths=0.5)
        # line
        ax1.plot([t["entry_ts"], t["exit_ts"]], [t["entry"], t["exit"]], color=col, alpha=0.3, linewidth=1)
    ax1.set_title(f"{symbol} {timeframe} — 7 Strategies Futures x{CONFIG['leverage']}  |  PnL {res['stats']['pnl']:+.2f}  WR {res['stats']['win_rate']:.1f}%", fontsize=11)
    ax1.set_ylabel("Price")
    ax1.grid(alpha=0.2); ax1.legend(fontsize=8)
    # Scores
    scores=[]
    for i in range(60, len(df)):
        sc,_=score_at(df.iloc[:i+1])
        scores.append((df.ts.iloc[i], sc))
    if scores:
        ts_sc=[x[0] for x in scores]; vals=[x[1] for x in scores]
        ax2.fill_between(ts_sc, vals, 0, where=[v>=0 for v in vals], color="#00d395", alpha=0.3)
        ax2.fill_between(ts_sc, vals, 0, where=[v<0 for v in vals], color="#ff3b5c", alpha=0.3)
        ax2.plot(ts_sc, vals, color="#60a5fa", linewidth=0.7)
        ax2.axhline(0.15, color="#00d395", linestyle="--", linewidth=0.6); ax2.axhline(-0.15, color="#ff3b5c", linestyle="--", linewidth=0.6)
        ax2.axhline(0.35, color="#00d395", linestyle=":", linewidth=0.5); ax2.axhline(-0.35, color="#ff3b5c", linestyle=":", linewidth=0.5)
    ax2.set_ylabel("Score"); ax2.set_ylim(-1,1); ax2.grid(alpha=0.2)
    # Equity
    eq=res["equity_curve"]
    if eq:
        ets=[e["ts"] for e in eq]; evals=[e["equity"] for e in eq]
        ax3.fill_between(ets, evals, 0, where=[v>=0 for v in evals], color="#00d395", alpha=0.2)
        ax3.fill_between(ets, evals, 0, where=[v<0 for v in evals], color="#ff3b5c", alpha=0.2)
        ax3.plot(ets, evals, color="#ffb800", linewidth=1)
        ax3.axhline(0, color="white", linewidth=0.5)
    ax3.set_ylabel("Equity USDT"); ax3.grid(alpha=0.2)
    for ax in axes: ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    plt.tight_layout(); plt.savefig(out_path, dpi=150, facecolor="#070b12", edgecolor="none"); plt.close()
    print(f"Chart saved → {out_path}")

def main():
    p=argparse.ArgumentParser(description="Backtest 7 strategies on BTC Futures")
    p.add_argument("--symbol", default="BTC/USDT", help="زوج — BTC/USDT ETH/USDT SOL/USDT ... 20 زوج")
    p.add_argument("--from", dest="from_date", default=None, help="من تاريخ YYYY-MM-DD")
    p.add_argument("--to", dest="to_date", default=None, help="إلى تاريخ YYYY-MM-DD")
    p.add_argument("--timeframe", default="1h", help="1h/4h/1d/15m")
    p.add_argument("--limit", type=int, default=1000, help="عدد الشموع")
    p.add_argument("--strategies", default=None, help="comma-separated: ichimoku,dow,gann,elliott,classical,sr,rsi_macd,smc,vwap,supertrend,bollinger,harmonic,ict,heikin,ai  (default all)")
    p.add_argument("--compare", action="store_true", help="قارن كل استراتيجية لوحدها + المجموعة")
    p.add_argument("--amount", type=float, default=20, help="هامش الصفقة USDT")
    p.add_argument("--leverage", type=int, default=5, help="الرافعة")
    p.add_argument("--fee", type=float, default=0.0004, help="عمولة")
    p.add_argument("--walk-forward", action="store_true", help="Walk-Forward 70/30 × 3 splits")
    p.add_argument("--kelly", action="store_true", help="احسب Kelly sizing")
    p.add_argument("--out", default=None, help="مسار الصورة")
    p.add_argument("--out-json", dest="out_json", default=None, help="مسار ملف JSON (افتراضي backtest_SYMBOL_TF.json)")
    args=p.parse_args()
    if args.leverage: CONFIG["leverage"]=args.leverage
    if args.amount: CONFIG["trade_amount_usdt"]=args.amount
    if args.fee is not None: CONFIG["fee_pct"]=args.fee
    enabled=None
    if args.strategies:
        enabled=[s.strip() for s in args.strategies.split(",") if s.strip()]
        print(f"الاستراتيجيات المفعلة: {enabled}")

    # Compare mode: run each strategy alone + combined
    if args.compare:
        from pathlib import Path as _P
        import json as _js
        all_names=["ichimoku","dow","gann","elliott","classical","sr","rsi_macd","smc","vwap","supertrend","bollinger","harmonic","ict","heikin","ai"]
        results=[]
        if getattr(args, "from_date", None) or getattr(args, "to_date", None):
            print(f"جلب {args.symbol} {args.timeframe} من {args.from_date} إلى {args.to_date} ...")
            df=fetch_ohlcv(args.symbol, args.timeframe, args.limit, from_date=args.from_date, to_date=args.to_date)
        else:
            print(f"جلب {args.symbol} {args.timeframe} x{args.limit} ...")
            df=fetch_ohlcv(args.symbol, args.timeframe, args.limit)
        print(f"Loaded {len(df)} bars: {df.ts.iloc[0]} -> {df.ts.iloc[-1]}")
        for name in all_names:
            print(f"\n--- {name} لوحده ---")
            r=run_backtest(df, amount_usdt=args.amount, leverage=args.leverage, fee_pct=args.fee, enabled=[name])
            print_report(r, df, f"{args.symbol} [{name}]", args.timeframe, args.amount, args.leverage)
            results.append((name, r["stats"]))
        print(f"\n--- المجموعة الكاملة (15) ---")
        r_all=run_backtest(df, amount_usdt=args.amount, leverage=args.leverage, fee_pct=args.fee, enabled=None)
        print_report(r_all, df, f"{args.symbol} [ALL 15]", args.timeframe, args.amount, args.leverage)
        results.append(("ALL 15", r_all["stats"]))
        # Save compare JSON
        cmp_path=_P(__file__).parent / f"backtest_compare_{args.symbol.replace('/','')}_{args.timeframe}.json"
        cmp_path.write_text(_js.dumps({n: s for n,s in results}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nCompare saved -> {cmp_path}")
        # Print ranking
        ranked=sorted(results, key=lambda x: x[1]["pnl"], reverse=True)
        print("\n=== الترتيب حسب PnL ===")
        for i,(n,s) in enumerate(ranked,1):
            print(f"{i:2d}. {n:12s}  PnL {s['pnl']:+7.2f}  WR {s['win_rate']:5.1f}%  PF {s['profit_factor']:.2f}  ({s['total']} trades)")
        return

    if args.walk_forward:
        if getattr(args, "from_date", None) or getattr(args, "to_date", None):
            print(f"جلب {args.symbol} {args.timeframe} من {args.from_date} الى {args.to_date} ...")
            df=fetch_ohlcv(args.symbol, args.timeframe, args.limit, from_date=args.from_date, to_date=args.to_date)
        else:
            print(f"جلب {args.symbol} {args.timeframe} x{args.limit} ...")
            df=fetch_ohlcv(args.symbol, args.timeframe, args.limit)
        print(f"Loaded {len(df)} bars: {df.ts.iloc[0]} -> {df.ts.iloc[-1]}")
        splits=walk_forward_splits(len(df), 0.7, 3)
        print(f"=== Walk-Forward {len(splits)} splits (70% train / 30% test) ===")
        wf_results=[]
        for idx,(a,b,c,d) in enumerate(splits,1):
            test_df=df.iloc[c:d]
            r=run_backtest(test_df, amount_usdt=args.amount, leverage=args.leverage, fee_pct=args.fee, enabled=enabled)
            print(f"--- Split {idx}: test bars {c}->{d} ({test_df.ts.iloc[0].date()} -> {test_df.ts.iloc[-1].date()}) ---")
            print_report(r, test_df, f"{args.symbol} WF{idx}", args.timeframe, args.amount, args.leverage)
            wf_results.append(r["stats"]["pnl"])
        avg_wf=sum(wf_results)/len(wf_results) if wf_results else 0
        print(f"=== Walk-Forward avg PnL: {avg_wf:+.2f} ===")
        print(f"=== Full Backtest ===")
        res=run_backtest(df, amount_usdt=args.amount, leverage=args.leverage, fee_pct=args.fee, enabled=enabled)
        print_report(res, df, args.symbol, args.timeframe, args.amount, args.leverage)
        try:
            mc_med, mc_p95 = monte_carlo_dd(res["trades"])
            print(f"Monte Carlo MaxDD: median {mc_med:.2f}  p95 {mc_p95:.2f}")
            kelly=kelly_position_size(res["stats"]["win_rate"], res["stats"]["avg_win"], res["stats"]["avg_loss"], 1000)
            print(f"Kelly sizing: {kelly:.2f} USDT")
        except: pass
        out_json=Path(args.out_json) if args.out_json else Path(__file__).parent / f"backtest_{args.symbol.replace('/','')}_{args.timeframe}.json"
        import json as _js
        jtrs=[{**tt, "entry_ts": str(tt["entry_ts"]), "exit_ts": str(tt["exit_ts"])} for tt in res["trades"]]
        out_json.write_text(_js.dumps({"symbol":args.symbol,"timeframe":args.timeframe,"stats":res["stats"],"walk_forward":{"splits":len(splits),"avg_pnl":avg_wf,"pnls":wf_results},"trades":jtrs}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON saved -> {out_json}")
        out_img=args.out or str(Path(__file__).parent / f"backtest_{args.symbol.replace('/','')}_{args.timeframe}.png")
        plot_results(df, res, args.symbol, args.timeframe, out_img)
        print(f"Done WF avg {avg_wf:+.2f} Full {res['stats']['pnl']:+.2f}")
        return

    if getattr(args, "from_date", None) or getattr(args, "to_date", None):
        print(f"جلب {args.symbol} {args.timeframe} من {args.from_date} إلى {args.to_date} ...")
        df=fetch_ohlcv(args.symbol, args.timeframe, args.limit, from_date=args.from_date, to_date=args.to_date)
    else:
        print(f"جلب {args.symbol} {args.timeframe} x{args.limit} ...")
        df=fetch_ohlcv(args.symbol, args.timeframe, args.limit)
    print(f"Loaded {len(df)} bars: {df.ts.iloc[0]} → {df.ts.iloc[-1]}")
    res=run_backtest(df, amount_usdt=args.amount, leverage=args.leverage, fee_pct=args.fee, enabled=enabled)
    print_report(res, df, args.symbol, args.timeframe, args.amount, args.leverage)
    # Save JSON
    out_json=Path(args.out_json) if args.out_json else Path(__file__).parent / f"backtest_{args.symbol.replace('/','')}_{args.timeframe}.json"
    # serialize
    jtrs=[{**t, "entry_ts": str(t["entry_ts"]), "exit_ts": str(t["exit_ts"])} for t in res["trades"]]
    out_json.write_text(json.dumps({"symbol":args.symbol,"timeframe":args.timeframe,"stats":res["stats"],"trades":jtrs}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"JSON saved → {out_json}")
    # Plot
    out_img=args.out or str(Path(__file__).parent / f"backtest_{args.symbol.replace('/','')}_{args.timeframe}.png")
    plot_results(df, res, args.symbol, args.timeframe, out_img)
    print(f"Done ✓  {res['stats']['total']} trades  PnL {res['stats']['pnl']:+.2f}  WR {res['stats']['win_rate']:.1f}%")

if __name__=="__main__":
    main()
