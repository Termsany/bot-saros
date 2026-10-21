"""
Two more ideas, on every Binance USDT-M perpetual since 2019 (delisted included), real per-coin funding (longs pay
positive funding, shorts receive it), fees 0.04%, $20 margin x2 per leg, chosen on Sharpe before 2024.

1. Pump continuation (long) — Gervais, Kaniel & Mingelgrin (2001) "The High-Volume Return Premium" (JF);
   Li, Urquhart, Wang & Zhang (2021) "MAX momentum in cryptocurrency markets". The same pump events as the rejected
   pump fade (day up >= R on >= V x 30-day median volume, top 100 by volume) — bought instead of shorted: enter the
   next open (or a day later), hold H days, stop S below entry, at most 10 open.
   Caveat: tested after the pump fade lost money, so only a clear out-of-sample win counts.
2. Pairs trading, distance method — Gatev, Goetzmann & Rouwenhorst (2006) "Pairs Trading" (RFS). Every 6 months:
   among the top 20 by volume, pick the N pairs whose normalised prices moved closest over the formation window
   (F days); for the next 6 months open long-laggard / short-leader when the spread is > k sigma (formation sigma),
   close when it crosses zero, at the end of the period, or (optional) when it reaches 4 sigma.

  python research/volume_pairs_study.py
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


# ── idea 1: buy the pump ──
def pump_long(df, fund, i, D, H, S):
    k = i + 1 + D
    if k >= len(df): return None
    o, l, c, ts = df.open.values, df.low.values, df.close.values, df.ts.values
    e = o[k]; q = AMOUNT * LEV / e; stop = e * (1 - S); fu = 0.0
    for j in range(k, min(len(df), k + H)):
        if l[j] <= stop:
            x = min(o[j], stop); return dict(entry_ts=int(ts[k]), exit_ts=int(ts[j]), side="long", entry=e, exit=x, qty=q, reason="stop",
                                            pnl=(x - e) * q - (e * q + x * q) * FEE - fu)
        fu += q * c[j] * fund.get(int(ts[j]), 0.0)
    j = k + H
    x, t = (o[j], ts[j]) if j < len(df) else (c[-1], ts[-1])
    return dict(entry_ts=int(ts[k]), exit_ts=int(t), side="long", entry=e, exit=x, qty=q, reason="time",
                pnl=(x - e) * q - (e * q + x * q) * FEE - fu)


# ── idea 2: pairs trading ──
def pair_periods(data, rk, F, N):
    """[(trade_start, trade_end, [(a, b, sigma)])] every 6 months; formation = the F days before trade_start."""
    closes = pd.DataFrame({s: df.set_index(pd.to_datetime(df.ts, unit="ms")).close for s, df in data.items()})
    out = []
    for start in pd.date_range("2020-07-01", closes.index[-1], freq="6MS"):
        f0, end = start - pd.Timedelta(days=F), min(start + pd.DateOffset(months=6), closes.index[-1])
        day0 = start - pd.Timedelta(days=1)
        if day0 not in rk.index: continue
        r = rk.loc[day0]; coins = [s for s in r[r <= 20].index if closes[s].loc[f0:day0].notna().sum() >= F - 2]
        if len(coins) < 6: continue
        form = closes.loc[f0:day0, coins].dropna()
        norm = form / form.iloc[0]
        cand = []
        for a, b in itertools.combinations(coins, 2):
            sp = norm[a] - norm[b]; cand.append(((sp ** 2).sum(), a, b, sp.std()))
        cand.sort()
        out.append((start, end, [(a, b, sd) for _, a, b, sd in cand[:N]]))
    return out


def pair_trades(data, fund, periods, k, stop_k):
    trades = []
    for start, end, pairs in periods:
        for a, b, sd in pairs:
            A = data[a].set_index(pd.to_datetime(data[a].ts, unit="ms")); B = data[b].set_index(pd.to_datetime(data[b].ts, unit="ms"))
            win = A.loc[start:end].index.intersection(B.loc[start:end].index)
            if len(win) < 10: continue
            A, B = A.loc[win], B.loc[win]
            na, nb = A.close / A.close.iloc[0], B.close / B.close.iloc[0]
            s = (na - nb).values; pos = None; blocked = False
            for i in range(len(win) - 1):
                if pos is None and not blocked and abs(s[i]) > k * sd:
                    lng, sht = (b, a) if s[i] > 0 else (a, b)        # a above b -> long b, short a
                    pos = {"i": i + 1, "sign": np.sign(s[i]), "long": lng, "short": sht}
                elif pos is not None:
                    cross = np.sign(s[i]) != pos["sign"]
                    stopped = stop_k and abs(s[i]) > stop_k * sd
                    last = i == len(win) - 2
                    if cross or stopped or last:
                        trades.append(close_pair(data, fund, pos, win, i + 1, "converged" if cross else "stop" if stopped else "period end"))
                        if stopped: blocked = True
                        pos = None
    return trades


def close_pair(data, fund, pos, win, j, reason):
    t0, t1 = win[pos["i"]], win[j]; pnl = 0.0
    for sym, sg in ((pos["long"], 1), (pos["short"], -1)):
        df = data[sym].set_index(pd.to_datetime(data[sym].ts, unit="ms"))
        e, x = df.open.loc[t0], df.open.loc[t1]; q = AMOUNT * LEV / e
        held = df.loc[t0:t1].iloc[:-1]
        fu = sum(q * c * fund[sym].get(int(t), 0.0) for t, c in zip(held.ts, held.close))
        pnl += sg * (x - e) * q - (e * q + x * q) * FEE - sg * fu
    return dict(entry_ts=int(t0.value // 10**6), exit_ts=int(t1.value // 10**6), side="pair", entry=0, exit=0, qty=0,
                pnl=pnl, reason=reason, pair=f"{pos['long']}/{pos['short']}")


def main():
    data = pickle.loads((CACHE / "universe_daily.pkl").read_bytes())
    fund_raw = pickle.loads((CACHE / "universe_funding.pkl").read_bytes())
    rk100 = pm.rank_table(data, 60)

    P1 = list(itertools.product([0.3, 0.5], [3, 5], [0, 1], [3, 7, 14], [0.2, 0.4]))
    events = {(R, V): pm.pump_events(data, rk100, R, V) for R, V in {(p[0], p[1]) for p in P1}}
    P2 = list(itertools.product([180, 365], [5, 10], [1.5, 2.0, 2.5], [None, 4.0]))
    periods = {(F, N): pair_periods(data, rk100, F, N) for F, N in {(p[0], p[1]) for p in P2}}

    # funding windows for the pair legs (pump windows were fetched by pump_momentum_study.py)
    windows = {}
    for ps in periods.values():
        for start, end, pairs in ps:
            for a, b, _ in pairs:
                for s in (a, b): windows.setdefault(s, []).append((int(start.value // 10**6), int(end.value // 10**6)))
    pm.fetch_windows(windows, fund_raw)
    fund = {s: fund_raw.get(s, {}) for s in data}

    rows, best1, best2 = [], None, None
    for R, V, D, H, S in P1:
        tr = [t for s, i in events[(R, V)] if (t := pump_long(data[s], fund[s], i, D, H, S))]
        r = ss.summary(pm.cap(tr, 10), f"1 BUY pump +{R:.0%}/day vol x{V} {'next day' if D == 0 else 'wait 1 day'} hold {H}d stop {S:.0%}")
        rows.append(r)
        if r["trades"] and (best1 is None or r["is_sharpe"] > best1["is_sharpe"]): best1 = r
    for F, N, k, sk in P2:
        r = ss.summary(pair_trades(data, fund, periods[(F, N)], k, sk), f"2 pairs form {F}d top {N} pairs open {k}σ{' stop 4σ' if sk else ''}")
        rows.append(r)
        if r["trades"] and (best2 is None or r["is_sharpe"] > best2["is_sharpe"]): best2 = r

    # the three paper bots running now
    rk10 = ranks(data); ever10 = [s for s in data if (rk10[s] <= 10).any()]
    long_tr = []
    for s in ever10:
        df = data[s]; top10 = list((rk10[s].reindex(pd.to_datetime(df.ts, unit="ms")) <= 10).fillna(False))
        long_tr += st.run_trend_daily(list(df.open), list(df.high), list(df.low), list(df.close), list(df.ts),
                                      [fund[s].get(int(t), 0.0) for t in df.ts], AMOUNT, LEV, FEE, 0, top10)
    base = ss.summary(long_tr, "PAPER 1: long trend top10")
    new = [s for s, df in data.items() if pd.to_datetime(df.ts.iloc[0], unit="ms") >= pd.Timestamp("2021-01-01")]
    lst = []
    for s in new: lst += ss.run_listing_short(data[s], [fund[s].get(int(t), 0.0) for t in data[s].ts], 30, 90, 0.4)
    lst = ss.summary(pm.cap(lst, 10), "PAPER 2: short new listings max 10")
    mom = ss.summary([t for s, d, side in pm.momentum_positions(data, rk100, 2, True) if (t := pm.momentum_trade(data[s], fund[s], d, side))],
                     "PAPER 3: momentum 2w long/short")

    def combo(name, parts):
        d = parts[0]["_daily"]
        for p in parts[1:]: d = d.add(p["_daily"], fill_value=0)
        eq = d.cumsum(); sh = lambda x: round(x.mean() / x.std() * math.sqrt(365), 2)
        return {"variant": name, "pnl": round(d.sum()), "maxDD": round(float((eq.cummax() - eq).max())),
                "is_sharpe": sh(d[d.index < CUT]), "oos_sharpe": sh(d[d.index >= CUT]), "oos_pnl": round(d[d.index >= CUT].sum()),
                **{str(y): int(v) for y, v in d.groupby(d.index.year).sum().round(0).items() if y >= 2020}}
    three = [base, lst, mom]
    rows = three + rows + [combo("THREE PAPER BOTS NOW", three), combo("three bots + best pump buy", three + [best1]),
                           combo("three bots + best pairs", three + [best2]), combo("three bots + both", three + [best1, best2])]
    out = pd.DataFrame([{k: v for k, v in r.items() if k != "_daily"} for r in rows]).set_index("variant")
    pd.set_option("display.width", 280); pd.set_option("display.max_columns", 30); pd.set_option("display.max_rows", 120)
    cols = [c for c in ["trades", "win%", "pnl", "maxDD", "is_sharpe", "oos_sharpe", "oos_pnl", "max_open", "2020", "2021", "2022", "2023", "2024", "2025", "2026"] if c in out]
    print(out[cols].to_string())
    print(f"\nchosen on in-sample Sharpe: idea 1 = {best1['variant']} | idea 2 = {best2['variant']}")
    for tag, P in (("1 ", P1), ("2 ", P2)):
        pos = sum(1 for r in rows if str(r.get("variant", "")).startswith(tag) and r.get("pnl", 0) > 0)
        print(f"variants with positive total PnL ({tag.strip()}): {pos}/{len(P)}")
    ex = periods[(365, 10)][-1]
    print("latest pairs (form 365d):", [f"{a.replace('USDT', '')}/{b.replace('USDT', '')}" for a, b, _ in ex[2]])


if __name__ == "__main__":
    main()
