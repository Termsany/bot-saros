"""
Three more short ideas on every Binance USDT-M perpetual since 2019 (delisted included), coins ranked by 30-day volume
at the time, 0.04% fee per side, real per-coin funding (shorts receive positive funding, pay negative), $20 margin x2,
stop 40% above entry (before liquidation at x2). Variants ranked by Sharpe before 2024-01-01; 2024 on is out-of-sample.

2. Dying coin: a coin that was liquid (top R0 by volume at some point in the last 90 days) whose volume has collapsed
   (rank now beyond R1) while it trades below its N-day average -> short the next open for H days. Binance delists
   for low liquidity and volume; a coin that is delisted while held is closed at its last price.
3. RSI-2 short (Connors' short side): below the 200-day average (or not), short the next open after the 2-day RSI
   closes above T; cover the next open after a close below the 5-day average (or RSI-2 under 30), 10 days at most.
4. Crash continuation: a one-day drop of R% or more on volume V x its 30-day median, among the top N by volume ->
   short the next open for H days (bad news is absorbed slowly — the opposite bet of the rejected pump fade).
Then each pick next to the three core paper bots. Shorts at most 10 open per idea (as the new-listing short).

  python research/short_ideas_study.py
"""
import sys, pickle, itertools, math
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import traders_study as ts
import short_study as ss
import pump_momentum_study as pm
import bots_stats as bs
from universe_study import ranks

AMOUNT, LEV, FEE, CUT = ts.AMOUNT, ts.LEV, ts.FEE, ts.CUT
STOP = 0.8 / LEV
MIN_TRADES = 60


def short_trade(a, k, e, j, x, reason, sym):
    q = AMOUNT * LEV / e
    fu = sum(q * a["c"][m] * a["f"][m] for m in range(k, j))          # shorts receive positive funding
    return dict(symbol=sym, entry_ts=int(a["ts"][k]), exit_ts=int(a["ts"][min(j, len(a["ts"]) - 1)]), side="short",
                entry=e, exit=x, qty=q, reason=reason, pnl=(e - x) * q - (e + x) * q * FEE + fu)


def hold_short(a, k, H, sym, exit_fn=None):
    """Short at the open of day k; stop 40% above; exit_fn(j) -> True covers at the next open; else after H days."""
    o, h, c = a["o"], a["h"], a["c"]; n = len(c); e = o[k]; sp = e * (1 + STOP)
    for j in range(k, min(n, k + H)):
        if h[j] >= sp: return short_trade(a, k, e, j, max(o[j], sp), "stop", sym), j
        if exit_fn and j + 1 < n and exit_fn(j): return short_trade(a, k, e, j + 1, o[j + 1], "signal", sym), j + 1
    j = k + H
    if j < n: return short_trade(a, k, e, j, o[j], "time", sym), j
    return short_trade(a, k, e, n - 1, c[-1], "delisted / data end", sym), n - 1


# ── 2. dying coin ──
def dying_trades(A, R0, R1, N, H):
    out = []
    for s, a in A.items():
        c = a["c"]; n = len(c)
        if n < N + 30: continue
        m = ts.sma(c, N); rk = a["rk"]
        best90 = pd.Series(rk).rolling(90, min_periods=30).min().values
        i = N
        while i < n - 2:
            r_now = rk[i + 1]                                          # rank known at close i
            if np.isfinite(r_now) and r_now > R1 and best90[i + 1] <= R0 and c[i] < m[i]:
                t, j = hold_short(a, i + 1, H, s); out.append(t); i = j
            else: i += 1
    return pm.cap(out, 10)


# ── 3. RSI-2 short ──
def rsi2_short_trades(A, top, T, trend, exit_rule):
    out = []
    for s, a in A.items():
        c = a["c"]; n = len(c)
        if n < 210: continue
        r2, m5, m200 = ts.rsi(c, 2), ts.sma(c, 5), ts.sma(c, 200)
        ex = (lambda j: c[j] < m5[j]) if exit_rule == "sma5" else (lambda j: r2[j] < 30)
        i = 200
        while i < n - 2:
            if a["rk"][i + 1] <= top and r2[i] > T and (not trend or c[i] < m200[i]):
                t, j = hold_short(a, i + 1, 10, s, ex); out.append(t); i = j
            else: i += 1
    return pm.cap(out, 10)


# ── 4. crash continuation ──
def crash_trades(A, top, R, V, H):
    out = []
    for s, a in A.items():
        c, v = a["c"], a["v"]; n = len(c)
        med = pd.Series(v).rolling(30).median().shift(1).values
        i = 31
        while i < n - 2:
            if a["rk"][i] <= top and c[i] / c[i - 1] - 1 <= -R and v[i] >= V * med[i]:   # rank before the crash day
                t, j = hold_short(a, i + 1, H, s); out.append(t); i = j
            else: i += 1
    return pm.cap(out, 10)


def run(name, fn, grid, A):
    rows = []
    for args in grid:
        tr = fn(A, *args); r = ss.summary(tr, f"{args}"); r["_trades"] = tr; rows.append(r)
    ok = sorted([r for r in rows if r["trades"] >= MIN_TRADES], key=lambda r: r["is_sharpe"], reverse=True)
    print(f"\n=== {name}: {len(ok)}/{len(rows)} variants with {MIN_TRADES}+ trades — positive before 2024 {sum(r['is_sharpe'] > 0 for r in ok)}, "
          f"after 2024 {sum(r['oos_sharpe'] > 0 for r in ok)}; median Sharpe {np.median([r['is_sharpe'] for r in ok]) if ok else 0:.2f} / "
          f"{np.median([r['oos_sharpe'] for r in ok]) if ok else 0:.2f} ===")
    print(f"{'variant':<34}{'trades':>7}{'win%':>6}{'pnl':>8}{'maxDD':>7}{'IS':>7}{'OOS':>7}{'oosPnL':>8}{'open':>6}")
    for r in ok[:6]:
        print(f"{r['variant']:<34}{r['trades']:>7}{r['win%']:>6}{r['pnl']:>8}{r['maxDD']:>7}{r['is_sharpe']:>7}{r['oos_sharpe']:>7}{r['oos_pnl']:>8}{r['max_open']:>6}")
    if ok:
        b = ok[0]; print("  pick by year: " + "  ".join(f"{y}: {b.get(str(y), 0):+d}" for y in range(2020, 2027)))
    return ok[0] if ok else None


def main():
    data = pickle.loads((ts.CACHE / "universe_daily.pkl").read_bytes())
    fund_raw = pickle.loads((ts.CACHE / "universe_funding.pkl").read_bytes())
    fund = {s: fund_raw.get(s, {}) for s in data}
    A = ts.coin_arrays(data, fund, pm.rank_table(data, 60))
    picks = {
        "2 dying coin": run("dying coin (R0, R1, ma, days)", dying_trades,
                            list(itertools.product((50, 100), (150, 250), (100, 200), (30, 60))), A),
        "3 RSI-2 short": run("RSI-2 short (top, T, downtrend, exit)", rsi2_short_trades,
                             list(itertools.product((10, 30), (90, 95, 98), (True, False), ("sma5", "rsi30"))), A),
        "4 crash continuation": run("crash continuation (top, drop, vol, days)", crash_trades,
                                    list(itertools.product((30, 100), (0.10, 0.15, 0.20), (2, 3), (1, 3, 7))), A),
    }
    rk10 = ranks(data); ever10 = [s for s in data if (rk10[s] <= 10).any()]
    new = [s for s, df in data.items() if pd.to_datetime(df.ts.iloc[0], unit="ms") >= pd.Timestamp("2021-01-01")]
    core = {k: ss.summary(v, k)["_daily"] for k, v in bs.trades_at(LEV, data, fund, rk10, ever10, pm.rank_table(data, 60), new).items()}
    core_sum = pd.DataFrame(core).fillna(0).sum(axis=1)
    sh = lambda d: round(float(d.mean() / d.std() * math.sqrt(365)), 2) if d.std() else 0.0
    print(f"\n=== next to the 3 core bots ===\n{'':<28}{'pnl':>8}{'maxDD':>8}{'IS':>7}{'OOS':>7}{'oosPnL':>8}{'corr OOS':>10}")
    for label, p in [("core only", None)] + list(picks.items()):
        if label != "core only" and not p: print(f"+ {label}: no variant with {MIN_TRADES}+ trades"); continue
        d = pd.concat([core_sum] + ([p["_daily"]] if p else []), axis=1).fillna(0).sum(axis=1); eq = d.cumsum()
        corr = "" if not p else f"{pd.concat([core_sum, p['_daily']], axis=1).fillna(0).loc[lambda x: x.index >= CUT].corr().iloc[0, 1]:>10.2f}"
        print(f"{('+ ' + label) if p else label:<28}{round(d.sum()):>8}{round(float((eq.cummax() - eq).max())):>8}{sh(d[d.index < CUT]):>7}"
              f"{sh(d[d.index >= CUT]):>7}{round(d[d.index >= CUT].sum()):>8}{corr}" + (f"   pick {p['variant']}" if p else ""))


if __name__ == "__main__":
    main()
