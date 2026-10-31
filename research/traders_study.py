"""
Three trader methods on every Binance USDT-M perpetual since 2019 (delisted included), coins picked by 30-day volume
at the time, 0.04% fee per side + 0.05% slippage on breakout entries, real per-coin funding (longs pay positive).
$20 margin x2 per trade. Variants ranked by Sharpe of daily PnL before 2024-01-01; 2024 onwards is out-of-sample.

1. Volatility breakout — Larry Williams (Long-Term Secrets to Short-Term Trading, 1999; 1987 Robbins World Cup):
   buy when the day trades k x yesterday's range above the open, sell at the next open. k fixed (0.3/0.5/0.7) or
   the Korean "noise" k (20-day average of 1 - |close-open| / range). Optional filter: yesterday's close above its
   n-day average.
2. RSI-2 pullback — Larry Connors (Short Term Trading Strategies That Work, 2008): in an uptrend (close above its
   200-day average) buy the next open after the 2-day RSI closes below T; sell the next open after a close above the
   5-day average (or RSI-2 above 70), 10 days at most; stop 0.8 / leverage below entry.
3. Volatility contraction breakout — Minervini (VCP, 1997 US Investing Championship) / Darvas (box): a stage-2
   uptrend (close > 50 > 150 > 200-day averages), 10-day ATR shrunk below c x its 50-day level, then a close above
   the L-day high on volume above 1.5x its 50-day average -> buy the next open. Stop at the box low (or 8% / 40%),
   exit on a close below the 20- or 50-day average.

Then the in-sample pick of each method is added to the three core paper bots (trend, momentum, new-listing short)
to see whether it improves the combination after 2024.

  python research/traders_study.py
"""
import os
import sys, pickle, itertools, math
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import short_study as ss
import pump_momentum_study as pm
import bots_stats as bs
from universe_study import ranks

CACHE = Path(os.getenv("RAQM_RESEARCH_CACHE") or Path(__file__).resolve().parent / ".cache")   # shared store: research/README.md
AMOUNT, LEV, FEE, CUT = 20, 2, 0.0004, pd.Timestamp("2024-01-01")
SLIP = 0.0005
MIN_TRADES = 60


def sma(x, n): return pd.Series(x).rolling(n).mean().values


def rsi(c, n=2):
    d = np.diff(c, prepend=c[0]); up = np.clip(d, 0, None); dn = np.clip(-d, 0, None)
    au = pd.Series(up).ewm(alpha=1 / n, adjust=False).mean().values
    ad = pd.Series(dn).ewm(alpha=1 / n, adjust=False).mean().values
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(ad == 0, 100.0, 100 - 100 / (1 + au / ad))


def atr(h, l, c, n):
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    return pd.Series(tr).rolling(n).mean().values


def coin_arrays(data, fund, rk):
    out = {}
    for s, df in data.items():
        if s not in rk: continue
        r = rk[s].reindex(pd.to_datetime(df.ts, unit="ms")).values
        out[s] = dict(o=df.open.values.astype(float), h=df.high.values.astype(float), l=df.low.values.astype(float),
                      c=df.close.values.astype(float), v=df.qvol.values.astype(float), ts=df.ts.values.astype("int64"),
                      rk=np.r_[np.nan, r[:-1]],                      # rank known at the previous close
                      f=np.array([fund.get(s, {}).get(int(t), 0.0) for t in df.ts]))
    return out


def long_trade(a, i_entry, entry, j_exit, exit_px, reason, sym):
    q = AMOUNT * LEV / entry
    fu = -sum(q * a["c"][k] * a["f"][k] for k in range(i_entry, j_exit))     # longs pay positive funding
    return dict(symbol=sym, entry_ts=int(a["ts"][i_entry]), exit_ts=int(a["ts"][min(j_exit, len(a["ts"]) - 1)]), side="long",
                entry=entry, exit=exit_px, qty=q, reason=reason, pnl=(exit_px - entry) * q - (entry + exit_px) * q * FEE + fu)


# ── 1. Williams volatility breakout ──
def vb_trades(A, top, k, ma):
    out = []
    for s, a in A.items():
        o, h, l, c = a["o"], a["h"], a["l"], a["c"]; n = len(c)
        rng = h - l
        if k == "noise":
            with np.errstate(divide="ignore", invalid="ignore"):
                nz = np.where(rng > 0, 1 - abs(c - o) / rng, np.nan)
            kk = pd.Series(nz).rolling(20).mean().shift(1).values
        else:
            kk = np.full(n, k)
        m = sma(c, ma) if ma else None
        for i in range(21, n - 1):
            if not (a["rk"][i] <= top) or not np.isfinite(kk[i]): continue
            if m is not None and not (c[i - 1] > m[i - 1]): continue
            trig = o[i] + kk[i] * rng[i - 1]
            if rng[i - 1] <= 0 or h[i] < trig: continue
            e = max(o[i], trig) * (1 + SLIP)
            out.append(long_trade(a, i, e, i + 1, o[i + 1], "next open", s))
    return out


# ── 2. Connors RSI-2 ──
def rsi2_trades(A, top, T, trend, exit_rule):
    out = []
    for s, a in A.items():
        o, h, l, c = a["o"], a["h"], a["l"], a["c"]; n = len(c)
        if n < 210: continue
        r2, m5, m200 = rsi(c, 2), sma(c, 5), sma(c, 200)
        i = 200
        while i < n - 2:
            ok = a["rk"][i + 1] <= top and r2[i] < T and (not trend or c[i] > m200[i])
            if not ok: i += 1; continue
            k = i + 1; e = o[k]; stop = e * (1 - 0.8 / LEV); done = None
            for j in range(k, min(n, k + 10)):
                if l[j] <= stop: done = (j, min(o[j], stop), "stop"); break
                if j + 1 < n and ((exit_rule == "sma5" and c[j] > m5[j]) or (exit_rule == "rsi70" and r2[j] > 70)):
                    done = (j + 1, o[j + 1], "signal"); break
            if done is None:
                j = min(n - 1, k + 10); done = (j, o[j], "time")
            j, x, why = done
            out.append(long_trade(a, k, e, j, x, why, s)); i = j
    return out


# ── 3. Minervini / Darvas volatility contraction breakout ──
def vcp_trades(A, top, L, cmax, stop_rule, exit_ma):
    out = []
    for s, a in A.items():
        o, h, l, c, v = a["o"], a["h"], a["l"], a["c"], a["v"]; n = len(c)
        if n < 210: continue
        m50, m150, m200, mx = sma(c, 50), sma(c, 150), sma(c, 200), sma(c, exit_ma)
        a10, a50, v50 = atr(h, l, c, 10), atr(h, l, c, 50), sma(v, 50)
        box_hi = pd.Series(h).rolling(L).max().shift(1).values
        box_lo = pd.Series(l).rolling(L).min().shift(1).values
        i = 200
        while i < n - 2:
            setup = (a["rk"][i + 1] <= top and c[i] > m50[i] > m150[i] > m200[i]
                     and a10[i - 1] < cmax * a50[i - 1] and c[i] > box_hi[i] and v[i] > 1.5 * v50[i - 1])
            if not setup: i += 1; continue
            k = i + 1; e = o[k] * (1 + SLIP)
            stop = {"box": box_lo[i], "8pct": e * 0.92, "40pct": e * (1 - 0.8 / LEV)}[stop_rule]
            stop = max(stop, e * (1 - 0.8 / LEV))                       # never past the liquidation guard
            done = None
            for j in range(k, n):
                if l[j] <= stop: done = (j, min(o[j], stop), "stop"); break
                if j + 1 < n and c[j] < mx[j]: done = (j + 1, o[j + 1], f"below {exit_ma}d avg"); break
            if done is None: done = (n - 1, c[-1], "open")
            j, x, why = done
            out.append(long_trade(a, k, e, j, x, why, s)); i = j
    return out


def run(name, fn, grid, A):
    rows = []
    for args in grid:
        tr = fn(A, *args)
        r = ss.summary(tr, f"{name} {args}"); r["_trades"] = tr; rows.append(r)
    ok = [r for r in rows if r["trades"] >= MIN_TRADES]
    ok.sort(key=lambda r: r["is_sharpe"], reverse=True)
    print(f"\n=== {name}: {len(rows)} variants, {sum(r['oos_sharpe'] > 0 for r in ok)}/{len(ok)} positive after 2024 ===")
    print(f"{'variant':<40}{'trades':>7}{'win%':>6}{'pnl':>8}{'maxDD':>7}{'IS':>7}{'OOS':>7}{'oosPnL':>8}{'open':>6}")
    for r in ok[:8]:
        print(f"{r['variant']:<40}{r['trades']:>7}{r['win%']:>6}{r['pnl']:>8}{r['maxDD']:>7}{r['is_sharpe']:>7}{r['oos_sharpe']:>7}{r['oos_pnl']:>8}{r['max_open']:>6}")
    return ok[0] if ok else None


def combo(core, extra=None):
    d = pd.DataFrame({k: v for k, v in core.items()} | ({"x": extra} if extra is not None else {})).fillna(0).sum(axis=1)
    sh = lambda x: round(float(x.mean() / x.std() * math.sqrt(365)), 2) if x.std() else 0.0
    eq = d.cumsum()
    return {"pnl": round(float(d.sum())), "maxDD": round(float((eq.cummax() - eq).max())),
            "IS": sh(d[d.index < CUT]), "OOS": sh(d[d.index >= CUT]), "oosPnL": round(float(d[d.index >= CUT].sum()))}


def main():
    data = pickle.loads((CACHE / "universe_daily.pkl").read_bytes())
    fund_raw = pickle.loads((CACHE / "universe_funding.pkl").read_bytes())
    fund = {s: fund_raw.get(s, {}) for s in data}
    rk = pm.rank_table(data, 60)
    A = coin_arrays(data, fund, rk)
    print(f"{len(A)} coins, {min(pd.to_datetime(a['ts'][0], unit='ms') for a in A.values()).date()} .. "
          f"{max(pd.to_datetime(a['ts'][-1], unit='ms') for a in A.values()).date()}")

    picks = {
        "1 volatility breakout": run("volatility breakout (top, k, ma)", vb_trades,
                                     list(itertools.product((10, 30), (0.3, 0.5, 0.7, "noise"), (0, 5, 20))), A),
        "2 RSI-2 pullback": run("RSI-2 (top, T, trend, exit)", rsi2_trades,
                                list(itertools.product((10, 30), (5, 10, 15), (True, False), ("sma5", "rsi70"))), A),
        "3 VCP / Darvas": run("VCP breakout (top, L, atr, stop, exit)", vcp_trades,
                              list(itertools.product((30, 100), (20, 40), (0.6, 0.8), ("box", "8pct", "40pct"), (20, 50))), A),
    }

    rk10 = ranks(data); ever10 = [s for s in data if (rk10[s] <= 10).any()]
    new = [s for s, df in data.items() if pd.to_datetime(df.ts.iloc[0], unit="ms") >= pd.Timestamp("2021-01-01")]
    core_tr = bs.trades_at(LEV, data, fund, rk10, ever10, pm.rank_table(data, 60), new)
    core = {k: ss.summary(v, k)["_daily"] for k, v in core_tr.items()}
    base = combo(core)
    print(f"\n=== added to the 3 core bots (trend + momentum + new-listing short) ===")
    print(f"{'':<26}{'pnl':>8}{'maxDD':>8}{'IS':>7}{'OOS':>7}{'oosPnL':>8}{'corr OOS':>10}")
    print(f"{'core only':<26}{base['pnl']:>8}{base['maxDD']:>8}{base['IS']:>7}{base['OOS']:>7}{base['oosPnL']:>8}")
    core_sum = pd.DataFrame(core).fillna(0).sum(axis=1)
    for name, p in picks.items():
        if not p: print(f"{name:<26} (no variant with {MIN_TRADES}+ trades)"); continue
        r = combo(core, p["_daily"])
        x = pd.concat([core_sum, p["_daily"]], axis=1).fillna(0); x = x[x.index >= CUT]
        print(f"{'+ ' + name:<26}{r['pnl']:>8}{r['maxDD']:>8}{r['IS']:>7}{r['OOS']:>7}{r['oosPnL']:>8}{x.corr().iloc[0, 1]:>10.2f}"
              f"   pick: {p['variant']}")


if __name__ == "__main__":
    main()
