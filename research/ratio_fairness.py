"""
Fairness check for the ratio trend (research/breakout_ratio_study.py idea 3): instead of five majors picked today
(BTC, ETH, SOL, BNB, XRP — survivors), every 7 days take the top K coins by 30-day volume AT THAT TIME and trade the
ratio trend on every pair among them. A pair opens when both coins are in the list and closes when either leaves.
Same costs as the other studies (fees 0.04%, real funding per leg, $20 x2 per leg).

  python research/ratio_fairness.py
"""
import sys, pickle, itertools, math
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import short_study as ss
import pump_momentum_study as pm
import breakout_ratio_study as br
import strategies_trend as st
from universe_study import ranks

CACHE = ss.CACHE
AMOUNT, LEV, FEE, CUT = ss.AMOUNT, ss.LEV, ss.FEE, ss.CUT


def ratio_window(frames, fund, a, b, rule, t0, t1):
    """Ratio trend on pair (a, b) traded only from t0 to t1 (signal uses the history before t0 too)."""
    A, B = frames[a], frames[b]
    idx = A.index.intersection(B.index)
    r = (A.close.loc[idx] / B.close.loc[idx]).values
    oa, ob, ca, cb = A.open.loc[idx].values, B.open.loc[idx].values, A.close.loc[idx].values, B.close.loc[idx].values
    if rule == "2of3":
        sig = lambda i: 1 if sum(r[i] > r[i - L] for L in (20, 60, 120)) >= 2 else -1; need = 120
    else:
        sma = pd.Series(r).rolling(rule).mean().values; sig = lambda i: 1 if r[i] > sma[i] else -1; need = rule
    i0, i1 = idx.searchsorted(t0), min(idx.searchsorted(t1), len(idx) - 1)
    if i0 < need or i1 - i0 < 2: return []
    O, C = {a: oa, b: ob}, {a: ca, b: cb}
    trades = []; cur = 0; legs = None; ets = 0
    def close(j, why):
        pnl = sum(sg * (O[s][j] - e) * q - (e * q + O[s][j] * q) * FEE - sg * fu for s, sg, e, q, fu in legs)
        return {"entry_ts": ets, "exit_ts": int(idx[j].value // 10**6), "side": "pair", "entry": 0, "exit": 0, "qty": 0, "pnl": pnl,
                "reason": why, "pair": f"{a}/{b}"}
    for i in range(i0 - 1, i1):
        if legs and i >= i0:
            t = int(idx[i].value // 10**6)
            legs = [(s, sg, e, q, fu + q * C[s][i] * fund[s].get(t, 0.0)) for s, sg, e, q, fu in legs]
        s_ = sig(i)
        if s_ != cur and i + 1 < i1:
            if legs: trades.append(close(i + 1, "flip"))
            j = i + 1; ets = int(idx[j].value // 10**6)
            lng, sht = (a, b) if s_ == 1 else (b, a)
            legs = [(s, sg, O[s][j], AMOUNT * LEV / O[s][j], 0.0) for s, sg in ((lng, 1), (sht, -1))]; cur = s_
    if legs: trades.append(close(i1, "left the list"))
    return trades


def dynamic_trades(data, fund, rk, K, rule):
    frames = {s: df.set_index(pd.to_datetime(df.ts, unit="ms")) for s, df in data.items()}
    weeks = rk.index[rk.index >= pd.Timestamp("2020-01-01")][::7]
    member = {d: sorted(rk.loc[d][rk.loc[d] <= K].index) for d in weeks}
    # contiguous weekly intervals per pair
    intervals = {}; open_ = {}
    for k, d in enumerate(weeks):
        pairs = set(itertools.combinations(member[d], 2))
        for p in list(open_):
            if p not in pairs: intervals.setdefault(p, []).append((open_.pop(p), d))
        for p in pairs:
            if p not in open_: open_[p] = d
    for p, t0 in open_.items(): intervals.setdefault(p, []).append((t0, rk.index[-1]))
    trades = []
    for (a, b), ivs in intervals.items():
        for t0, t1 in ivs: trades += ratio_window(frames, fund, a, b, rule, t0, t1)
    return trades, member


def main():
    data = pickle.loads((CACHE / "universe_daily.pkl").read_bytes())
    fund_raw = pickle.loads((CACHE / "universe_funding.pkl").read_bytes())
    fund = {s: fund_raw.get(s, {}) for s in data}
    rk = pm.rank_table(data, 120)

    rows = []
    for rule in [50, "2of3"]:
        tr = []
        for a, b in itertools.combinations(br.MAJORS, 2): tr += br.run_ratio(data, fund, a, b, rule)
        rows.append(ss.summary(tr, f"FIXED 5 majors picked today, rule {rule}"))
    members = {}
    for K, rule in itertools.product([5, 7], [50, "2of3"]):
        tr, members[K] = dynamic_trades(data, fund, rk, K, rule)
        rows.append(ss.summary(tr, f"DYNAMIC top {K} by volume each week, rule {rule}"))

    # the three paper bots, for the combination
    rk10 = ranks(data); ever10 = [s for s in data if (rk10[s] <= 10).any()]
    long_tr = []
    for s in ever10:
        df = data[s]; top10 = list((rk10[s].reindex(pd.to_datetime(df.ts, unit="ms")) <= 10).fillna(False))
        long_tr += st.run_trend_daily(list(df.open), list(df.high), list(df.low), list(df.close), list(df.ts),
                                      [fund[s].get(int(t), 0.0) for t in df.ts], AMOUNT, LEV, FEE, 0, top10)
    rk100 = pm.rank_table(data, 60)
    new = [s for s, df in data.items() if pd.to_datetime(df.ts.iloc[0], unit="ms") >= pd.Timestamp("2021-01-01")]
    lst = []
    for s in new: lst += ss.run_listing_short(data[s], [fund[s].get(int(t), 0.0) for t in data[s].ts], 30, 90, 0.4)
    three = [ss.summary(long_tr, "PAPER 1"), ss.summary(pm.cap(lst, 10), "PAPER 2"),
             ss.summary([t for s, d, side in pm.momentum_positions(data, rk100, 2, True) if (t := pm.momentum_trade(data[s], fund[s], d, side))], "PAPER 3")]

    def combo(name, parts):
        d = parts[0]["_daily"]
        for p in parts[1:]: d = d.add(p["_daily"], fill_value=0)
        eq = d.cumsum(); sh = lambda x: round(x.mean() / x.std() * math.sqrt(365), 2)
        return {"variant": name, "pnl": round(d.sum()), "maxDD": round(float((eq.cummax() - eq).max())),
                "is_sharpe": sh(d[d.index < CUT]), "oos_sharpe": sh(d[d.index >= CUT]), "oos_pnl": round(d[d.index >= CUT].sum()),
                **{str(y): int(v) for y, v in d.groupby(d.index.year).sum().round(0).items() if y >= 2020}}
    dyn = [r for r in rows if r["variant"].startswith("DYNAMIC")]
    best = max(dyn, key=lambda r: r["is_sharpe"])
    rows += [combo("THREE PAPER BOTS NOW", three), combo(f"three bots + {best['variant']}", three + [best])]
    out = pd.DataFrame([{k: v for k, v in r.items() if k != "_daily"} for r in rows]).set_index("variant")
    pd.set_option("display.width", 290); pd.set_option("display.max_columns", 30)
    cols = [c for c in ["trades", "win%", "pnl", "maxDD", "is_sharpe", "oos_sharpe", "oos_pnl", "max_open", "2020", "2021", "2022", "2023", "2024", "2025", "2026"] if c in out]
    print(out[cols].to_string())
    print(f"\nbest dynamic version on in-sample Sharpe: {best['variant']}")
    m5 = members[5]
    for d in [pd.Timestamp(x) for x in ("2020-06-01", "2021-06-01", "2022-06-01", "2023-06-01", "2024-06-01", "2025-06-01", "2026-10-01")]:
        k = min(m5, key=lambda w: abs(w - d))
        print(f"top 5 around {d.date()}: {', '.join(s.replace('USDT', '') for s in m5[k])}")


if __name__ == "__main__":
    main()
