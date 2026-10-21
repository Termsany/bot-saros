"""
Two more short ideas, on every Binance USDT-M perpetual since 2019 (delisted included), real per-coin funding,
fees 0.04%, $20 margin x2, chosen on Sharpe of daily realised PnL before 2024 (same rules as short_study.py).

1. Pump fade — Kamps & Kleinberg (2018) "To the moon" (Crime Science) and the pump-and-dump literature: coins pumped
   in a coordinated way tend to give the rise back within days. Short a top-100-by-volume coin after a day up >= R
   on >= V x its 30-day median volume; enter the next open (or one day later), hold H days, stop S above entry;
   at most 10 open.
2. Cross-sectional momentum — Liu, Tsyvinski & Wu (2022) "Common Risk Factors in Cryptocurrency" (JF): past
   winners beat past losers. Every 7 days rank the top 50 by volume on the last L weeks' return; short the weakest 5
   (or also long the strongest 5); hold a week; stop 40%.

  python research/pump_momentum_study.py          # downloads the missing funding windows first (Bybit, Binance fallback)
"""
import sys, pickle, itertools, math, time, json, urllib.request
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import short_study as ss
import strategies_trend as st
from universe_study import ranks

CACHE = ss.CACHE
AMOUNT, LEV, FEE, CUT = ss.AMOUNT, ss.LEV, ss.FEE, ss.CUT
DAY = 86_400_000


def rank_table(data, min_history):
    """day x symbol rank by 30-day average USDT volume (1 = most), NaN when the coin has < min_history days."""
    vol = {}
    for s, df in data.items():
        v = df.set_index(pd.to_datetime(df.ts, unit="ms")).qvol.rolling(30).mean()
        v.iloc[:min_history - 1] = np.nan
        vol[s] = v
    return pd.DataFrame(vol).rank(axis=1, ascending=False)


# ── funding windows: fetch only what the trades need ──
def covered(days, a, b):
    want = range(a // DAY * DAY, b // DAY * DAY + 1, DAY)
    n = len(want); return n == 0 or sum(d in days for d in want) >= 0.9 * n


def fetch_windows(windows, fund_raw):
    """windows: {sym: [(start_ms, end_ms)]}; fetches the uncovered ones from Binance into fund_raw (saved)."""
    todo = []
    for s, ws in windows.items():
        ws = sorted(ws); merged = []
        for a, b in ws:
            if merged and a <= merged[-1][1] + 3 * DAY: merged[-1][1] = max(merged[-1][1], b)
            else: merged.append([a, b])
        todo += [(s, a, b) for a, b in merged if not covered(fund_raw.get(s, {}), a, b)]
    print(f"funding: {len(todo)} windows to download (Bybit first, Binance for what Bybit doesn't have)", flush=True)
    path = CACHE / "universe_funding.pkl"
    src = {"bybit": 0, "binance": 0}
    for n, (s, a, b) in enumerate(todo):
        day = fund_raw.setdefault(s, {})
        if bybit_window(s, a, b, day):
            src["bybit"] += 1
            if n % 100 == 0: path.write_bytes(pickle.dumps(fund_raw)); print(f"  {n}/{len(todo)}", flush=True)
            continue
        src["binance"] += 1
        start = a
        while start < b + DAY:
            f = None
            for attempt in range(6):
                try:
                    with urllib.request.urlopen(f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={s}&startTime={start}&endTime={b + DAY}&limit=1000", timeout=20) as r:
                        f = json.loads(r.read()); break
                except Exception: time.sleep(5 + attempt * 10)
            time.sleep(0.65)
            if not f: break
            for x in f:
                d = x["fundingTime"] // DAY * DAY; day[d] = day.get(d, 0.0) + float(x["fundingRate"])
            for d in range(a // DAY * DAY, b // DAY * DAY + 1, DAY): day.setdefault(d, 0.0)   # mark the window as fetched
            start = f[-1]["fundingTime"] + 1
            if len(f) < 1000: break
        if n % 100 == 0: path.write_bytes(pickle.dumps(fund_raw)); print(f"  {n}/{len(todo)}", flush=True)
    path.write_bytes(pickle.dumps(fund_raw))
    print(f"funding sources: {src}", flush=True)


def bybit_window(s, a, b, day):
    """Bybit linear funding for [a, b] (fast: generous rate limits). False if Bybit doesn't list the symbol then."""
    got, end = [], b + DAY
    for _ in range(20):
        try:
            with urllib.request.urlopen(f"https://api.bybit.com/v5/market/funding/history?category=linear&symbol={s}&startTime={a}&endTime={end}&limit=200", timeout=20) as r:
                lst = (json.loads(r.read()).get("result") or {}).get("list") or []
        except Exception:
            return False
        if not lst: break
        got += lst
        oldest = int(lst[-1]["fundingRateTimestamp"])          # newest first
        if len(lst) < 200 or oldest <= a: break
        end = oldest - 1
        time.sleep(0.05)
    span = (b - a) / DAY
    if not got or (int(got[-1]["fundingRateTimestamp"]) - a) / DAY > max(2, span * 0.1):   # Bybit listed it later
        return False
    for x in got:
        d = int(x["fundingRateTimestamp"]) // DAY * DAY; day[d] = day.get(d, 0.0) + float(x["fundingRate"])
    for d in range(a // DAY * DAY, b // DAY * DAY + 1, DAY): day.setdefault(d, 0.0)
    return True


# ── idea 1: pump fade ──
def pump_events(data, rk, R, V):
    ev = []
    for s, df in data.items():
        if s not in rk: continue
        c, q = df.close.values, df.qvol.values
        r = rk[s].reindex(pd.to_datetime(df.ts, unit="ms")).values
        med = pd.Series(q).rolling(30).median().shift(1).values
        for i in range(31, len(df) - 2):
            if c[i] / c[i - 1] - 1 >= R and q[i] >= V * med[i] and r[i - 1] <= 100:   # rank before the pump day
                ev.append((s, i))
    return ev


def pump_trade(df, fund, i, D, H, S):
    k = i + 1 + D
    if k >= len(df): return None
    o, h, c, ts = df.open.values, df.high.values, df.close.values, df.ts.values
    e = o[k]; q = AMOUNT * LEV / e; stop = e * (1 + S); fu = 0.0
    for j in range(k, min(len(df), k + H)):
        if h[j] >= stop:
            x = max(o[j], stop); return dict(entry_ts=int(ts[k]), exit_ts=int(ts[j]), side="short", entry=e, exit=x, qty=q, reason="stop",
                                            pnl=(e - x) * q - (e * q + x * q) * FEE + fu)
        fu += q * c[j] * fund.get(int(ts[j]), 0.0)
    j = k + H
    x, t = (o[j], ts[j]) if j < len(df) else (c[-1], ts[-1])
    return dict(entry_ts=int(ts[k]), exit_ts=int(t), side="short", entry=e, exit=x, qty=q, reason="time",
                pnl=(e - x) * q - (e * q + x * q) * FEE + fu)


def cap(trades, n):
    trades = sorted(trades, key=lambda t: t["entry_ts"]); out, open_ = [], []
    for t in trades:
        open_ = [x for x in open_ if x > t["entry_ts"]]
        if len(open_) < n: out.append(t); open_.append(t["exit_ts"])
    return out


# ── idea 2: cross-sectional momentum, weekly ──
def momentum_positions(data, rk50, L, longs):
    closes = pd.DataFrame({s: df.set_index(pd.to_datetime(df.ts, unit="ms")).close for s, df in data.items()})
    past = closes / closes.shift(7 * L) - 1
    pos = []
    for d in closes.index[7 * L + 30::7]:
        r = rk50.loc[d] if d in rk50.index else None
        if r is None: continue
        elig = r[r <= 50].index
        p = past.loc[d, elig].dropna()
        if len(p) < 20: continue
        p = p.sort_values()
        pos += [(s, d, "short") for s in p.index[:5]]
        if longs: pos += [(s, d, "long") for s in p.index[-5:]]
    return pos


def momentum_trade(df, fund, d, side):
    idx = pd.to_datetime(df.ts, unit="ms"); k = idx.searchsorted(d) + 1      # next open after the ranking close
    if k >= len(df): return None
    o, h, l, c, ts = df.open.values, df.high.values, df.low.values, df.close.values, df.ts.values
    sg = 1 if side == "long" else -1
    e = o[k]; q = AMOUNT * LEV / e; stop = e * (1 - sg * st.STOP_SHARE / LEV); fu = 0.0
    for j in range(k, min(len(df), k + 7)):
        if (sg == -1 and h[j] >= stop) or (sg == 1 and l[j] <= stop):
            x = max(o[j], stop) if sg == -1 else min(o[j], stop)
            return dict(entry_ts=int(ts[k]), exit_ts=int(ts[j]), side=side, entry=e, exit=x, qty=q, reason="stop",
                        pnl=sg * (x - e) * q - (e * q + x * q) * FEE + fu)
        fu += -sg * q * c[j] * fund.get(int(ts[j]), 0.0)                  # longs pay positive funding, shorts receive it
    j = k + 7
    x, t = (o[j], ts[j]) if j < len(df) else (c[-1], ts[-1])
    return dict(entry_ts=int(ts[k]), exit_ts=int(t), side=side, entry=e, exit=x, qty=q, reason="week",
                pnl=sg * (x - e) * q - (e * q + x * q) * FEE + fu)


def main():
    data = pickle.loads((CACHE / "universe_daily.pkl").read_bytes())
    fund_raw = pickle.loads((CACHE / "universe_funding.pkl").read_bytes())
    rk100 = rank_table(data, 60)

    # plan every trade first, so only the needed funding windows are downloaded
    P1 = list(itertools.product([0.3, 0.5], [3, 5], [0, 1], [3, 7, 14], [0.3, 0.5]))       # R, V, delay, hold, stop
    events = {(R, V): pump_events(data, rk100, R, V) for R, V in {(p[0], p[1]) for p in P1}}
    P2 = list(itertools.product([1, 2, 4], [False, True]))                                 # weeks, with longs
    mom = {(L, lg): momentum_positions(data, rk100, L, lg) for L, lg in P2}
    windows = {}
    for ev in events.values():
        for s, i in ev:
            t0 = int(data[s].ts.iloc[i]); windows.setdefault(s, []).append((t0, t0 + 16 * DAY))
    for ps in mom.values():
        for s, d, _ in ps:
            t0 = int(d.value // 10**6); windows.setdefault(s, []).append((t0, t0 + 9 * DAY))
    fetch_windows(windows, fund_raw)
    fund = {s: fund_raw.get(s, {}) for s in data}

    rows, best1, best2 = [], None, None
    for R, V, D, H, S in P1:
        tr = [t for s, i in events[(R, V)] if (t := pump_trade(data[s], fund[s], i, D, H, S))]
        r = ss.summary(cap(tr, 10), f"1 pump fade +{R:.0%}/day vol x{V} {'next day' if D == 0 else 'wait 1 day'} hold {H}d stop {S:.0%}")
        rows.append(r)
        if r["trades"] and (best1 is None or r["is_sharpe"] > best1["is_sharpe"]): best1 = r
    for L, lg in P2:
        tr = [t for s, d, side in mom[(L, lg)] if (t := momentum_trade(data[s], fund[s], d, side))]
        r = ss.summary(tr, f"2 momentum {L}w: short weakest 5{' + long strongest 5' if lg else ''}")
        rows.append(r)
        if r["trades"] and (best2 is None or r["is_sharpe"] > best2["is_sharpe"]): best2 = r

    # the two paper bots running now, for the combinations
    rk10 = ranks(data)
    ever10 = [s for s in data if (rk10[s] <= 10).any()]
    long_tr = []
    for s in ever10:
        df = data[s]; top10 = list((rk10[s].reindex(pd.to_datetime(df.ts, unit="ms")) <= 10).fillna(False))
        fu = [fund_raw.get(s, {}).get(int(t), 0.0) for t in df.ts]
        long_tr += st.run_trend_daily(list(df.open), list(df.high), list(df.low), list(df.close), list(df.ts), fu, AMOUNT, LEV, FEE, 0, top10)
    base = ss.summary(long_tr, "LONG trend top10 (paper bot)")
    new = [s for s, df in data.items() if pd.to_datetime(df.ts.iloc[0], unit="ms") >= pd.Timestamp("2021-01-01")]
    lst = []
    for s in new: lst += ss.run_listing_short(data[s], [fund_raw.get(s, {}).get(int(t), 0.0) for t in data[s].ts], 30, 90, 0.4)
    lst = ss.summary(cap(lst, 10), "SHORT new listings max 10 (paper bot)")

    def combo(name, parts):
        d = parts[0]["_daily"]
        for p in parts[1:]: d = d.add(p["_daily"], fill_value=0)
        eq = d.cumsum(); sh = lambda x: round(x.mean() / x.std() * math.sqrt(365), 2)
        return {"variant": name, "pnl": round(d.sum()), "maxDD": round(float((eq.cummax() - eq).max())),
                "is_sharpe": sh(d[d.index < CUT]), "oos_sharpe": sh(d[d.index >= CUT]), "oos_pnl": round(d[d.index >= CUT].sum()),
                **{str(y): int(v) for y, v in d.groupby(d.index.year).sum().round(0).items() if y >= 2020}}
    rows = [base, lst] + rows + [combo("BOTH BOTS NOW (long + listings)", [base, lst]),
                                 combo("both bots + best pump fade", [base, lst, best1]),
                                 combo("both bots + best momentum", [base, lst, best2]),
                                 combo("both bots + both new ideas", [base, lst, best1, best2])]
    out = pd.DataFrame([{k: v for k, v in r.items() if k != "_daily"} for r in rows]).set_index("variant")
    pd.set_option("display.width", 280); pd.set_option("display.max_columns", 30); pd.set_option("display.max_rows", 90)
    cols = [c for c in ["trades", "win%", "pnl", "maxDD", "is_sharpe", "oos_sharpe", "oos_pnl", "max_open", "2020", "2021", "2022", "2023", "2024", "2025", "2026"] if c in out]
    print(out[cols].to_string())
    print(f"\nchosen on in-sample Sharpe: idea 1 = {best1['variant']} | idea 2 = {best2['variant']}")
    print("pump events (R, V -> count):", {k: len(v) for k, v in events.items()})
    pos1 = sum(1 for r in rows if str(r.get("variant", "")).startswith("1 ") and r.get("pnl", 0) > 0)
    pos2 = sum(1 for r in rows if str(r.get("variant", "")).startswith("2 ") and r.get("pnl", 0) > 0)
    print(f"variants with positive total PnL: pump fade {pos1}/{len(P1)}, momentum {pos2}/{len(P2)}")


if __name__ == "__main__":
    main()
