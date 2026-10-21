"""
1. Betting against beta — Frazzini & Pedersen (2014) "Betting Against Beta" (JFE): every 7 days among the top 50 by
   volume, beta vs BTC over the past B days (shrunk: 0.6 x beta + 0.4), long the 5 lowest-beta coins and short the
   5 highest; equal size, or beta-balanced (size x 1/beta, capped at 2x); hold a week, stop 40%.
2. Strategy momentum across the paper bots — Ehsani & Linnainmaa (2022) "Factor Momentum and the Momentum Factor"
   (JF): at each month start, weight each bot by its own past L months (only data known then):
   "on/off" = 0 if it lost over the period, else 1; "tilt" = 1.5x the best two, 0.5x the worst two.
Every Binance USDT-M perpetual since 2019 (delisted included), real funding, fees 0.04%, $20 x2 per position,
chosen on Sharpe before 2024.

  python research/bab_allocation_study.py
"""
import sys, pickle, itertools, math
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import short_study as ss
import pump_momentum_study as pm
import ratio_fairness as rf
import strategies_trend as st
from universe_study import ranks

CACHE = ss.CACHE
AMOUNT, LEV, FEE, CUT, DAY = ss.AMOUNT, ss.LEV, ss.FEE, ss.CUT, pm.DAY


def bab_positions(data, rk, B):
    """[(symbol, date, side, beta)] weekly; betas vs BTC over the past B daily returns, shrunk towards 1."""
    closes = pd.DataFrame({s: df.set_index(pd.to_datetime(df.ts, unit="ms")).close for s, df in data.items()})
    rets = closes.pct_change()
    pos = []
    for d in closes.index[B + 30::7]:
        if d not in rk.index: continue
        r = rk.loc[d]; elig = [s for s in r[r <= 50].index if s != "BTCUSDT"]
        win = rets.loc[:d].iloc[-B:]; m = win["BTCUSDT"]
        betas = {}
        for s in elig:
            x = win[s]; ok = x.notna() & m.notna()
            if ok.sum() < B * 0.8: continue
            betas[s] = 0.6 * np.cov(x[ok], m[ok])[0, 1] / m[ok].var() + 0.4
        if len(betas) < 20: continue
        b = pd.Series(betas).sort_values()
        pos += [(s, d, "long", b[s]) for s in b.index[:5]] + [(s, d, "short", b[s]) for s in b.index[-5:]]
    return pos


def bab_trades(data, fund, positions, balanced):
    out = []
    for s, d, side, beta in positions:
        t = pm.momentum_trade(data[s], fund.get(s, {}), d, side)
        if not t: continue
        k = min(2.0, 1.0 / max(beta, 0.05)) if balanced else 1.0     # pnl, fees and funding all scale with size
        t = dict(t); t["pnl"] *= k; out.append(t)
    return out


def allocate(series, L, mode):
    """series: {name: daily PnL}; monthly weights from each bot's past L months (no look-ahead)."""
    df = pd.DataFrame(series).fillna(0.0)
    monthly = df.resample("MS").sum()
    w = pd.DataFrame(1.0, index=monthly.index, columns=df.columns)
    for k, m in enumerate(monthly.index):
        past = monthly.iloc[max(0, k - L):k]
        if len(past) < L: continue
        tot = past.sum()
        if mode == "onoff":
            w.loc[m] = (tot > 0).astype(float)
        else:
            order = tot.sort_values()
            w.loc[m] = 1.0
            w.loc[m, order.index[-2:]] = 1.5; w.loc[m, order.index[:2]] = 0.5
    daily_w = w.reindex(df.index, method="ffill").fillna(1.0)
    return (df * daily_w).sum(axis=1), w


def stats_of(name, d):
    eq = d.cumsum(); sh = lambda x: round(x.mean() / x.std() * math.sqrt(365), 2) if x.std() else 0.0
    return {"variant": name, "pnl": round(d.sum()), "maxDD": round(float((eq.cummax() - eq).max())),
            "is_sharpe": sh(d[d.index < CUT]), "oos_sharpe": sh(d[d.index >= CUT]), "oos_pnl": round(d[d.index >= CUT].sum()),
            **{str(y): int(v) for y, v in d.groupby(d.index.year).sum().round(0).items() if y >= 2020}}


def main():
    data = pickle.loads((CACHE / "universe_daily.pkl").read_bytes())
    fund_raw = pickle.loads((CACHE / "universe_funding.pkl").read_bytes())
    rk100 = pm.rank_table(data, 60)
    babpos = {B: bab_positions(data, rk100, B) for B in (60, 120)}
    windows = {}
    for ps in babpos.values():
        for s, d, _, _ in ps:
            t0 = int(d.value // 10**6); windows.setdefault(s, []).append((t0, t0 + 9 * DAY))
    pm.fetch_windows(windows, fund_raw)
    fund = {s: fund_raw.get(s, {}) for s in data}

    rows, best1 = [], None
    for B, bal in itertools.product((60, 120), (False, True)):
        r = ss.summary(bab_trades(data, fund, babpos[B], bal), f"1 BAB beta {B}d, {'beta-balanced' if bal else 'equal size'}")
        rows.append(r)
        if r["trades"] and (best1 is None or r["is_sharpe"] > best1["is_sharpe"]): best1, best1_key = r, (B, bal)
    sides = {}
    for side in ("long", "short"):
        B, bal = best1_key
        sides[side] = ss.summary(bab_trades(data, fund, [p for p in babpos[B] if p[2] == side], bal), f"   {best1['variant']} — {side} side only")

    # the four paper bots
    rk10 = ranks(data); ever10 = [s for s in data if (rk10[s] <= 10).any()]
    long_tr = []
    for s in ever10:
        df = data[s]; top10 = list((rk10[s].reindex(pd.to_datetime(df.ts, unit="ms")) <= 10).fillna(False))
        long_tr += st.run_trend_daily(list(df.open), list(df.high), list(df.low), list(df.close), list(df.ts),
                                      [fund[s].get(int(t), 0.0) for t in df.ts], AMOUNT, LEV, FEE, 0, top10)
    new = [s for s, df in data.items() if pd.to_datetime(df.ts.iloc[0], unit="ms") >= pd.Timestamp("2021-01-01")]
    lst = []
    for s in new: lst += ss.run_listing_short(data[s], [fund[s].get(int(t), 0.0) for t in data[s].ts], 30, 90, 0.4)
    bots = {"trend": ss.summary(long_tr, "PAPER 1: long trend"),
            "listings": ss.summary(pm.cap(lst, 10), "PAPER 2: new-listing short"),
            "momentum": ss.summary([t for s, d, side in pm.momentum_positions(data, rk100, 2, True) if (t := pm.momentum_trade(data[s], fund[s], d, side))], "PAPER 3: momentum"),
            "ratio": ss.summary(rf.dynamic_trades(data, fund, pm.rank_table(data, 120), 7, 50)[0], "PAPER 4: ratio trend (HIGH RISK)")}
    series = {k: v["_daily"] for k, v in bots.items()}
    three = {k: series[k] for k in ("trend", "listings", "momentum")}

    combos = [stats_of("THREE BOTS, equal (now)", pd.DataFrame(three).fillna(0).sum(axis=1)),
              stats_of("FOUR BOTS, equal (now incl. HIGH RISK)", pd.DataFrame(series).fillna(0).sum(axis=1)),
              stats_of("three bots + best BAB", pd.DataFrame({**three, "bab": best1["_daily"]}).fillna(0).sum(axis=1))]
    alloc_rows, best2 = [], None
    for L, mode in itertools.product((3, 6, 12), ("onoff", "tilt")):
        for label, ser in (("four bots", series), ("three bots", three)):
            d, w = allocate(ser, L, mode)
            r = stats_of(f"2 {label}: {mode} by past {L} months", d); alloc_rows.append(r)
            if label == "four bots" and (best2 is None or r["is_sharpe"] > best2["is_sharpe"]): best2 = r; best2_w = w
    out = pd.DataFrame([{k: v for k, v in r.items() if k != "_daily"} for r in list(bots.values()) + rows + list(sides.values()) + combos + alloc_rows]).set_index("variant")
    pd.set_option("display.width", 290); pd.set_option("display.max_columns", 30); pd.set_option("display.max_rows", 80)
    cols = [c for c in ["trades", "win%", "pnl", "maxDD", "is_sharpe", "oos_sharpe", "oos_pnl", "2020", "2021", "2022", "2023", "2024", "2025", "2026"] if c in out]
    print(out[cols].to_string())
    print(f"\nbest BAB on in-sample Sharpe: {best1['variant']}")
    print(f"best allocation of the four bots on in-sample Sharpe: {best2['variant']}")
    print("its average weight per bot since 2024:", best2_w[best2_w.index >= CUT].mean().round(2).to_dict())


if __name__ == "__main__":
    main()
