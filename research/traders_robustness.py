"""
Robustness of the two methods that held up in research/traders_study.py, before running them as paper bots.

1. Williams volatility breakout (top 10, k=0.7, above the 20-day average):
   - slippage on the breakout fill 0.05% / 0.1% / 0.2% (fast coins jump through a stop order)
   - an intraday stop 2% / 4% below the fill — daily candles don't say whether the low came after the fill, so a
     day whose low reaches the stop counts as stopped (the worst case)
   - neighbouring settings (k 0.6/0.7/0.8, average 10/20/30, top 5/10/15/20): a real effect shouldn't hang on one value
   - every year on its own
2. Connors RSI-2: more coins (top 10/20/30/50), thresholds 5/10/15, with/without the 200-day trend, exit above the
   5-day average or RSI-2 > 70 — picked before 2024 among variants with 150+ trades, then every year on its own.
Finally both picks together with the three core paper bots.

  python research/traders_robustness.py
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

CUT = ts.CUT


def vb_stop_trades(A, top, k, ma, slip, stop):
    """traders_study.vb_trades with its own slippage and an optional intraday stop (worst case on daily candles)."""
    out = []
    for s, a in A.items():
        o, h, l, c = a["o"], a["h"], a["l"], a["c"]; n = len(c); rng = h - l
        m = ts.sma(c, ma) if ma else None
        for i in range(21, n - 1):
            if not (a["rk"][i] <= top) or rng[i - 1] <= 0: continue
            if m is not None and not (c[i - 1] > m[i - 1]): continue
            trig = o[i] + k * rng[i - 1]
            if h[i] < trig: continue
            e = max(o[i], trig) * (1 + slip)
            if stop and l[i] <= e * (1 - stop):
                out.append(ts.long_trade(a, i, e, i + 1, e * (1 - stop) * (1 - slip), "stop", s))
            else:
                out.append(ts.long_trade(a, i, e, i + 1, o[i + 1], "next open", s))
    return out


def row(label, tr):
    r = ss.summary(tr, label)
    return r, (f"{label:<46}{r['trades']:>7}{r['win%']:>6}{r['pnl']:>8}{r['maxDD']:>7}{r['is_sharpe']:>7}{r['oos_sharpe']:>7}{r['oos_pnl']:>8}")


HEAD = f"{'':<46}{'trades':>7}{'win%':>6}{'pnl':>8}{'maxDD':>7}{'IS':>7}{'OOS':>7}{'oosPnL':>8}"


def years(r):
    return "  ".join(f"{y}: {r.get(str(y), 0):+d}" for y in range(2020, 2027))


def main():
    data = pickle.loads((ts.CACHE / "universe_daily.pkl").read_bytes())
    fund_raw = pickle.loads((ts.CACHE / "universe_funding.pkl").read_bytes())
    fund = {s: fund_raw.get(s, {}) for s in data}
    A = ts.coin_arrays(data, fund, pm.rank_table(data, 60))

    print("=== 1. volatility breakout — slippage and intraday stop (top 10, k 0.7, 20-day average) ===\n" + HEAD)
    for slip in (0.0005, 0.001, 0.002):
        for stop in (0, 0.02, 0.04):
            print(row(f"slip {slip:.2%} stop {stop:.0%}" if stop else f"slip {slip:.2%} no stop", vb_stop_trades(A, 10, 0.7, 20, slip, stop))[1])

    print("\n=== 1. neighbouring settings (slip 0.1%, no stop) ===\n" + HEAD)
    nb = []
    for top, k, ma in itertools.product((5, 10, 15, 20), (0.6, 0.7, 0.8), (10, 20, 30)):
        r, line = row(f"top {top} k {k} ma {ma}", vb_stop_trades(A, top, k, ma, 0.001, 0)); nb.append(r)
    print(f"  {sum(r['oos_sharpe'] > 0 for r in nb)}/{len(nb)} positive after 2024; IS Sharpe median {np.median([r['is_sharpe'] for r in nb]):.2f}, "
          f"OOS median {np.median([r['oos_sharpe'] for r in nb]):.2f}, worst OOS {min(r['oos_sharpe'] for r in nb):.2f}")
    for r in sorted(nb, key=lambda r: r["is_sharpe"], reverse=True)[:5]:
        print(f"{r['variant']:<46}{r['trades']:>7}{r['win%']:>6}{r['pnl']:>8}{r['maxDD']:>7}{r['is_sharpe']:>7}{r['oos_sharpe']:>7}{r['oos_pnl']:>8}")

    vb_pick_tr = vb_stop_trades(A, 10, 0.7, 20, 0.001, 0)
    vb_pick = ss.summary(vb_pick_tr, "vb pick")
    print(f"\n  by year (top 10, k 0.7, ma 20, slip 0.1%): {years(vb_pick)}")

    print("\n=== 2. RSI-2 — wider grid, picked before 2024 among variants with 150+ trades ===\n" + HEAD)
    rr = []
    for top, T, trend, ex in itertools.product((10, 20, 30, 50), (5, 10, 15), (True, False), ("sma5", "rsi70")):
        tr = ts.rsi2_trades(A, top, T, trend, ex)
        r = ss.summary(tr, f"top {top} T {T} {'trend' if trend else 'any'} {ex}"); r["_trades"] = tr; rr.append(r)
    ok = sorted([r for r in rr if r["trades"] >= 150], key=lambda r: r["is_sharpe"], reverse=True)
    print(f"  {sum(r['oos_sharpe'] > 0 for r in rr)}/{len(rr)} positive after 2024")
    for r in ok[:8]:
        print(f"{r['variant']:<46}{r['trades']:>7}{r['win%']:>6}{r['pnl']:>8}{r['maxDD']:>7}{r['is_sharpe']:>7}{r['oos_sharpe']:>7}{r['oos_pnl']:>8}")
    rsi_pick = ok[0]
    print(f"\n  by year ({rsi_pick['variant']}): {years(rsi_pick)}")

    rk10 = ranks(data); ever10 = [s for s in data if (rk10[s] <= 10).any()]
    new = [s for s, df in data.items() if pd.to_datetime(df.ts.iloc[0], unit="ms") >= pd.Timestamp("2021-01-01")]
    core = {k: ss.summary(v, k)["_daily"] for k, v in bs.trades_at(ts.LEV, data, fund, rk10, ever10, pm.rank_table(data, 60), new).items()}
    print(f"\n=== with the 3 core bots (breakout at 0.1% slippage) ===")
    print(f"{'':<34}{'pnl':>8}{'maxDD':>8}{'IS':>7}{'OOS':>7}{'oosPnL':>8}")
    for label, extra in (("core only", {}), ("+ breakout", {"vb": vb_pick["_daily"]}), ("+ RSI-2", {"rsi": rsi_pick["_daily"]}),
                         ("+ breakout + RSI-2", {"vb": vb_pick["_daily"], "rsi": rsi_pick["_daily"]})):
        d = pd.DataFrame({**core, **extra}).fillna(0).sum(axis=1)
        sh = lambda x: round(float(x.mean() / x.std() * math.sqrt(365)), 2) if x.std() else 0.0
        eq = d.cumsum()
        print(f"{label:<34}{round(d.sum()):>8}{round(float((eq.cummax() - eq).max())):>8}{sh(d[d.index < CUT]):>7}{sh(d[d.index >= CUT]):>7}{round(d[d.index >= CUT].sum()):>8}")


if __name__ == "__main__":
    main()
