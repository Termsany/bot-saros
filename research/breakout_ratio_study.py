"""
Three long/short ideas from the trend family — every Binance USDT-M perpetual since 2019 (delisted included),
real per-coin funding, fees 0.04%, $20 x2 per position (per leg), chosen on Sharpe before 2024.

1. 52-week-high momentum — George & Hwang (2004) "The 52-Week High and Momentum Investing" (JF): every 7 days among
   the top 50 by volume, long the 5 closest to their W-day high, short the 5 furthest from it; hold a week, stop 40%.
2. Donchian breakout (the Turtles; Hurst, Ooi & Pedersen 2017 "A Century of Evidence on Trend-Following"):
   top 10 by volume; long on a close above the N-day high, short below the N-day low; exit on the opposite M-day
   level; stop 2 x ATR(20) or only the 40% protective stop; size like the trend bot (min(1, 80% / 30-day vol)).
3. Ratio trend — time-series momentum (Moskowitz, Ooi & Pedersen 2012) on the price ratio of two majors
   (BTC, ETH, SOL, BNB, XRP: 10 pairs): ratio trending up -> long the first / short the second, and the reverse.
   Caveat: the five coins are picked today (they survived and stayed large).

  python research/breakout_ratio_study.py
"""
import sys, pickle, itertools, math
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import short_study as ss
import pump_momentum_study as pm
import strategies_trend as st
from universe_study import ranks

CACHE = ss.CACHE
AMOUNT, LEV, FEE, CUT, DAY = ss.AMOUNT, ss.LEV, ss.FEE, ss.CUT, pm.DAY
MAJORS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]


# ── 1. 52-week high ──
def high52_positions(data, rk, W):
    closes = pd.DataFrame({s: df.set_index(pd.to_datetime(df.ts, unit="ms")).close for s, df in data.items()})
    highs = pd.DataFrame({s: df.set_index(pd.to_datetime(df.ts, unit="ms")).high for s, df in data.items()})
    near = closes / highs.rolling(W, min_periods=W).max()
    pos = []
    for d in closes.index[W + 30::7]:
        if d not in rk.index: continue
        r = rk.loc[d]; p = near.loc[d, r[r <= 50].index].dropna()
        if len(p) < 20: continue
        p = p.sort_values()
        pos += [(s, d, "short") for s in p.index[:5]] + [(s, d, "long") for s in p.index[-5:]]
    return pos


# ── 2. Donchian breakout ──
def run_donchian(df, fund, allowed, N, M, atr_stop, sides):
    o, h, l, c, ts = df.open.values, df.high.values, df.low.values, df.close.values, list(df.ts)
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    atr = np.r_[np.nan, pd.Series(tr).rolling(20).mean().values]
    n = len(c); trades = []; pos = None; pending = None
    def close(price, t, reason):
        q, sg = pos["qty"], pos["sg"]
        return {"entry_ts": pos["ts"], "exit_ts": t, "side": "long" if sg == 1 else "short", "entry": pos["entry"], "exit": price,
                "qty": q, "reason": reason, "pnl": sg * (price - pos["entry"]) * q - (pos["entry"] * q + price * q) * FEE - sg * pos["funding"]}
    for i in range(n):
        if pending and pending[0] == "open":
            sg, size, a = pending[1], pending[2], pending[3]
            q = AMOUNT * LEV * size / o[i]
            stop = o[i] - sg * 2 * a if atr_stop else o[i] * (1 - sg * st.STOP_SHARE / LEV)
            pos = {"entry": o[i], "qty": q, "ts": ts[i], "sg": sg, "funding": 0.0, "stop": stop}
        elif pending and pending[0] == "close" and pos:
            trades.append(close(o[i], ts[i], "exit channel")); pos = None
        pending = None
        if pos:
            sg = pos["sg"]
            if (sg == 1 and l[i] <= pos["stop"]) or (sg == -1 and h[i] >= pos["stop"]):
                x = min(o[i], pos["stop"]) if sg == 1 else max(o[i], pos["stop"])
                trades.append(close(x, ts[i], "stop")); pos = None
            else:
                pos["funding"] += pos["qty"] * c[i] * fund.get(ts[i], 0.0)
        if i + 1 < n and i > max(N, 30):
            if pos is None and allowed[i] and not np.isnan(atr[i]):
                up, dn = c[i] > h[i - N:i].max(), c[i] < l[i - N:i].min()
                sg = 1 if up and sides in ("both", "long") else -1 if dn and sides in ("both", "short") else 0
                if sg: pending = ("open", sg, st.size_factor(c, i), atr[i])
            elif pos is not None:
                if (pos["sg"] == 1 and c[i] < l[i - M:i].min()) or (pos["sg"] == -1 and c[i] > h[i - M:i].max()):
                    pending = ("close",)
    if pos: trades.append(close(c[-1], ts[-1], "close"))
    return trades


# ── 3. ratio trend ──
def run_ratio(data, fund, a, b, rule):
    A = data[a].set_index(pd.to_datetime(data[a].ts, unit="ms")); B = data[b].set_index(pd.to_datetime(data[b].ts, unit="ms"))
    idx = A.index.intersection(B.index); A, B = A.loc[idx], B.loc[idx]
    r = (A.close / B.close).values
    if rule == "2of3": sig = lambda i: 1 if sum(r[i] > r[i - L] for L in (20, 60, 120)) >= 2 else -1
    else:
        sma = pd.Series(r).rolling(rule).mean().values; sig = lambda i: 1 if r[i] > sma[i] else -1
    start = 120 if rule == "2of3" else rule
    trades = []; cur = 0; legs = None; legs_ts = 0
    frames = {a: A, b: B}
    def close_legs(j, reason):
        pnl = 0.0
        for sym, sg, e, q, fu in legs:
            x = frames[sym].open.values[j]; pnl += sg * (x - e) * q - (e * q + x * q) * FEE - sg * fu
        return {"entry_ts": legs_ts, "exit_ts": int(idx[j].value // 10**6), "side": "pair", "entry": 0, "exit": 0, "qty": 0, "pnl": pnl, "reason": reason}
    for i in range(start, len(idx) - 1):
        if legs:   # funding over candle i: longs pay positive funding, shorts receive it
            t = int(idx[i].value // 10**6)
            legs = [(sym, sg, e, q, fu + q * frames[sym].close.values[i] * fund[sym].get(t, 0.0)) for sym, sg, e, q, fu in legs]
        s = sig(i)
        if s != cur:
            if legs: trades.append(close_legs(i + 1, "flip"))
            j = i + 1; legs_ts = int(idx[j].value // 10**6)
            lng, sht = (a, b) if s == 1 else (b, a)
            legs = [(sym, sg, frames[sym].open.values[j], AMOUNT * LEV / frames[sym].open.values[j], 0.0) for sym, sg in ((lng, 1), (sht, -1))]
            cur = s
    if legs: trades.append(close_legs(len(idx) - 1, "end"))
    return trades


def main():
    data = pickle.loads((CACHE / "universe_daily.pkl").read_bytes())
    fund_raw = pickle.loads((CACHE / "universe_funding.pkl").read_bytes())
    rk100 = pm.rank_table(data, 60)
    P1 = [180, 365]
    h52 = {W: high52_positions(data, rk100, W) for W in P1}
    windows = {}
    for ps in h52.values():
        for s, d, _ in ps:
            t0 = int(d.value // 10**6); windows.setdefault(s, []).append((t0, t0 + 9 * DAY))
    pm.fetch_windows(windows, fund_raw)
    fund = {s: fund_raw.get(s, {}) for s in data}

    rows, best = [], {}
    def keep(tag, r):
        rows.append(r)
        if r.get("trades") and (tag not in best or r["is_sharpe"] > best[tag]["is_sharpe"]): best[tag] = r

    for W in P1:
        keep("1", ss.summary([t for s, d, side in h52[W] if (t := pm.momentum_trade(data[s], fund[s], d, side))], f"1 52w-high momentum, high over {W}d"))

    rk10 = ranks(data); ever10 = [s for s in data if (rk10[s] <= 10).any()]
    top10 = {s: list((rk10[s].reindex(pd.to_datetime(data[s].ts, unit="ms")) <= 10).fillna(False)) for s in ever10}
    sides_rows = []
    for N, M, atr_stop in itertools.product([20, 55], [10, 20], [True, False]):
        if M >= N: continue
        for sides in ("both", "long", "short"):
            tr = []
            for s in ever10:
                fdict = {int(t): fund[s].get(int(t), 0.0) for t in data[s].ts}
                tr += run_donchian(data[s], fdict, top10[s], N, M, atr_stop, sides)
            r = ss.summary(tr, f"2 Donchian {N}/{M}{' stop 2ATR' if atr_stop else ' stop 40%'} — {sides}")
            if sides == "both": keep("2", r)
            else: sides_rows.append(r)

    for rule in ["2of3", 50, 100]:
        tr = []
        for a, b in itertools.combinations(MAJORS, 2): tr += run_ratio(data, fund, a, b, rule)
        keep("3", ss.summary(tr, f"3 ratio trend, 10 major pairs, rule {'20/60/120 2-of-3' if rule == '2of3' else f'vs {rule}d average'}"))

    # the three paper bots
    long_tr = []
    for s in ever10:
        df = data[s]
        long_tr += st.run_trend_daily(list(df.open), list(df.high), list(df.low), list(df.close), list(df.ts),
                                      [fund[s].get(int(t), 0.0) for t in df.ts], AMOUNT, LEV, FEE, 0, top10[s])
    p1 = ss.summary(long_tr, "PAPER 1: long trend top10")
    new = [s for s, df in data.items() if pd.to_datetime(df.ts.iloc[0], unit="ms") >= pd.Timestamp("2021-01-01")]
    lst = []
    for s in new: lst += ss.run_listing_short(data[s], [fund[s].get(int(t), 0.0) for t in data[s].ts], 30, 90, 0.4)
    p2 = ss.summary(pm.cap(lst, 10), "PAPER 2: short new listings max 10")
    p3 = ss.summary([t for s, d, side in pm.momentum_positions(data, rk100, 2, True) if (t := pm.momentum_trade(data[s], fund[s], d, side))],
                    "PAPER 3: momentum 2w long/short")

    def combo(name, parts):
        d = parts[0]["_daily"]
        for p in parts[1:]: d = d.add(p["_daily"], fill_value=0)
        eq = d.cumsum(); sh = lambda x: round(x.mean() / x.std() * math.sqrt(365), 2)
        return {"variant": name, "pnl": round(d.sum()), "maxDD": round(float((eq.cummax() - eq).max())),
                "is_sharpe": sh(d[d.index < CUT]), "oos_sharpe": sh(d[d.index >= CUT]), "oos_pnl": round(d[d.index >= CUT].sum()),
                **{str(y): int(v) for y, v in d.groupby(d.index.year).sum().round(0).items() if y >= 2020}}
    three = [p1, p2, p3]
    rows = three + rows + sides_rows + [combo("THREE PAPER BOTS NOW", three)] + \
        [combo(f"three bots + best idea {k}", three + [best[k]]) for k in ("1", "2", "3")] + \
        [combo("three bots + best of all three", three + [best["1"], best["2"], best["3"]])]
    out = pd.DataFrame([{k: v for k, v in r.items() if k != "_daily"} for r in rows]).set_index("variant")
    pd.set_option("display.width", 290); pd.set_option("display.max_columns", 30); pd.set_option("display.max_rows", 90)
    cols = [c for c in ["trades", "win%", "pnl", "maxDD", "is_sharpe", "oos_sharpe", "oos_pnl", "max_open", "2020", "2021", "2022", "2023", "2024", "2025", "2026"] if c in out]
    print(out[cols].to_string())
    for k in ("1", "2", "3"): print(f"best idea {k} on in-sample Sharpe: {best[k]['variant']}")


if __name__ == "__main__":
    main()
