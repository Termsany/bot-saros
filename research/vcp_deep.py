"""
A closer look at the Minervini / Darvas volatility-contraction breakout that research/traders_study.py did not adopt
(124 trades in 7 years, Sharpe 0.20 before 2024, most of the profit after it).

1. Where the profit of that variant comes from: by year, the biggest trades, holding time.
2. Which condition chokes it — one change at a time from that variant:
   universe (top 30 / 100 / every coin with 200+ days), trend template (full 50>150>200 / close above 200 only),
   contraction (ATR10/ATR50 below 0.6 / 0.8 / off), breakout volume (x1.5 / x2 / off), box length (20 / 40 / 55 days),
   exit (below the 20 / 50-day average, below the 10-day low).
3. A modest grid of the conditions that matter, picked before 2024 as always (60+ trades), with how many variants
   stay positive after 2024 and the profit without the 5 biggest trades.
Same costs as the other studies: $20 x2, 0.04% fee per side, 0.05% slippage on the entry, real funding.

  python research/vcp_deep.py
"""
import sys, pickle, itertools, math
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import traders_study as ts
import short_study as ss
import pump_momentum_study as pm

LEV, SLIP = ts.LEV, ts.SLIP
BASE = dict(top=100, template="full", cmax=0.8, vol=1.5, L=20, exit="ma20", stop="40pct")
_cache = {}


def ind(s, a, key, fn):
    k = (s, key)
    if k not in _cache: _cache[k] = fn()
    return _cache[k]


def vcp(A, top, template, cmax, vol, L, exit, stop):
    out = []
    for s, a in A.items():
        o, h, l, c, v = a["o"], a["h"], a["l"], a["c"], a["v"]; n = len(c)
        if n < 210: continue
        m50 = ind(s, a, "m50", lambda: ts.sma(c, 50)); m150 = ind(s, a, "m150", lambda: ts.sma(c, 150)); m200 = ind(s, a, "m200", lambda: ts.sma(c, 200))
        a10 = ind(s, a, "a10", lambda: ts.atr(h, l, c, 10)); a50 = ind(s, a, "a50", lambda: ts.atr(h, l, c, 50)); v50 = ind(s, a, "v50", lambda: ts.sma(v, 50))
        hi = ind(s, a, f"hi{L}", lambda: pd.Series(h).rolling(L).max().shift(1).values)
        lo = ind(s, a, f"lo{L}", lambda: pd.Series(l).rolling(L).min().shift(1).values)
        if exit == "low10": ex_line = ind(s, a, "lo10", lambda: pd.Series(l).rolling(10).min().shift(1).values)
        else: ex_line = ind(s, a, exit, lambda: ts.sma(c, int(exit[2:])))
        i = 200
        while i < n - 2:
            rank_ok = top == "all" or a["rk"][i + 1] <= top
            trend = (c[i] > m50[i] > m150[i] > m200[i]) if template == "full" else c[i] > m200[i]
            setup = (rank_ok and trend and (cmax is None or a10[i - 1] < cmax * a50[i - 1]) and c[i] > hi[i]
                     and (vol is None or v[i] > vol * v50[i - 1]))
            if not setup: i += 1; continue
            k = i + 1; e = o[k] * (1 + SLIP)
            sp = max(lo[i] if stop == "box" else 0, e * (1 - 0.8 / LEV))
            done = None
            for j in range(k, n):
                if l[j] <= sp: done = (j, min(o[j], sp), "stop"); break
                if j + 1 < n and c[j] < ex_line[j]: done = (j + 1, o[j + 1], exit); break
            if done is None: done = (n - 1, c[-1], "open")
            j, x, why = done
            t = ts.long_trade(a, k, e, j, x, why, s); t["days"] = j - k; out.append(t); i = j
    return out


def line(label, tr):
    r = ss.summary(tr, label)
    if not tr: return r, f"{label:<44}{0:>7}"
    p = sorted((t["pnl"] for t in tr), reverse=True)
    no5 = round(sum(p[5:]))
    return r, (f"{label:<44}{r['trades']:>7}{r['win%']:>6}{r['pnl']:>8}{no5:>9}{r['maxDD']:>7}{r['is_sharpe']:>7}{r['oos_sharpe']:>7}{r['oos_pnl']:>8}")


HEAD = f"{'':<44}{'trades':>7}{'win%':>6}{'pnl':>8}{'no top5':>9}{'maxDD':>7}{'IS':>7}{'OOS':>7}{'oosPnL':>8}"


def main():
    data = pickle.loads((ts.CACHE / "universe_daily.pkl").read_bytes())
    fund_raw = pickle.loads((ts.CACHE / "universe_funding.pkl").read_bytes())
    A = ts.coin_arrays(data, {s: fund_raw.get(s, {}) for s in data}, pm.rank_table(data, 60))

    base_tr = vcp(A, **BASE)
    r = ss.summary(base_tr, "base")
    t = pd.DataFrame(base_tr); t["year"] = pd.to_datetime(t.entry_ts, unit="ms").dt.year
    print("=== 1. the variant from traders_study (top 100, full template, ATR < 0.8, volume x1.5, 20-day box, exit below 20-day avg) ===")
    print("trades by year: " + "  ".join(f"{y}: {n}" for y, n in t.groupby("year").size().items()))
    print("profit by year: " + "  ".join(f"{y}: {r.get(str(y), 0):+d}" for y in range(2020, 2027)))
    top = t.sort_values("pnl", ascending=False).head(5)
    print(f"5 biggest trades: {round(top.pnl.sum())}$ of {round(t.pnl.sum())}$ — " +
          ", ".join(f"{s.replace('USDT', '')} {pd.to_datetime(e, unit='ms').date()} {p:+.0f}$" for s, e, p in zip(top.symbol, top.entry_ts, top.pnl)))
    print(f"win {(t.pnl > 0).mean():.0%}, average win {t.pnl[t.pnl > 0].mean():+.1f}$, average loss {t.pnl[t.pnl <= 0].mean():+.1f}$, "
          f"median hold {t.days.median():.0f} days, exits: " + ", ".join(f"{k} {v}" for k, v in t.reason.value_counts().items()))

    print("\n=== 2. one condition at a time ===\n" + HEAD)
    print(line("base", base_tr)[1])
    for key, vals in (("top", (30, "all")), ("template", ("ma200",)), ("cmax", (0.6, None)), ("vol", (2.0, None)),
                      ("L", (40, 55)), ("exit", ("ma50", "low10")), ("stop", ("box",))):
        for v in vals:
            print(line(f"{key} = {v}", vcp(A, **{**BASE, key: v}))[1])

    print("\n=== 3. grid, picked before 2024 among 60+ trades ===")
    rows = []
    for top_, tpl, cmax, vol, L, ex in itertools.product((100, "all"), ("full", "ma200"), (0.8, None), (1.5, None), (20, 55), ("ma20", "ma50", "low10")):
        tr = vcp(A, top_, tpl, cmax, vol, L, ex, "40pct")
        rr, ln = line(f"top {top_} {tpl} atr {cmax} vol {vol} L {L} {ex}", tr); rr["_line"] = ln; rows.append(rr)
    ok = [x for x in rows if x["trades"] >= 60]
    print(f"{len(ok)}/{len(rows)} variants with 60+ trades; positive before 2024: {sum(x['is_sharpe'] > 0 for x in ok)}, "
          f"after 2024: {sum(x['oos_sharpe'] > 0 for x in ok)}; median Sharpe before {np.median([x['is_sharpe'] for x in ok]):.2f} / after {np.median([x['oos_sharpe'] for x in ok]):.2f}")
    print(HEAD)
    for x in sorted(ok, key=lambda x: x["is_sharpe"], reverse=True)[:10]: print(x["_line"])
    best = max(ok, key=lambda x: x["is_sharpe"])
    print(f"\npick: {best['variant']}\n  by year: " + "  ".join(f"{y}: {best.get(str(y), 0):+d}" for y in range(2020, 2027)))


if __name__ == "__main__":
    main()
