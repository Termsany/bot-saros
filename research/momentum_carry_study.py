"""
Improving the momentum bot, and a carry strategy — every Binance USDT-M perpetual since 2019 (delisted included),
real per-coin funding, fees 0.04%, $20 x2 per position, weekly, chosen on Sharpe before 2024.

Baseline: the third paper bot — every 7 days long the strongest 5 / short the weakest 5 of the top 50 by volume
on their 2-week return (research/pump_momentum_study.py).
1. Risk-managed momentum — Barroso & Santa-Clara (2015) "Momentum Has Its Moments" (JFE); Daniel & Moskowitz (2016)
   "Momentum Crashes" (JFE): scale each week's positions by ref / (the strategy's realised volatility over the past
   W weeks), ref = the median of that volatility so far (no look-ahead), capped at 1x or 1.5x, floor 0.25x.
2. Residual momentum — Blitz, Huij & Martens (2011) (J. Empirical Finance): rank on the 2/4-week return left after
   removing BTC's move (beta over the past 60/120 days).
3. Cross-sectional carry — Schmeling, Schrimpf & Todorov (2023) "Crypto Carry" (BIS): every 7 days short the 5 top-50
   coins with the highest average funding over the last D days and long the 5 with the lowest; earn the funding gap.

  python research/momentum_carry_study.py      # downloads the top-50 funding it needs first (Bybit, Binance fallback)
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


def weekly_dates(closes, start_offset):
    return closes.index[start_offset::7]


def residual_positions(data, rk, L, beta_win):
    closes = pd.DataFrame({s: df.set_index(pd.to_datetime(df.ts, unit="ms")).close for s, df in data.items()})
    rets = closes.pct_change(); btc = rets["BTCUSDT"]
    pos = []
    for d in weekly_dates(closes, 7 * L + 30):
        if d not in rk.index: continue
        r = rk.loc[d]; elig = list(r[r <= 50].index)
        win = rets.loc[:d].iloc[-beta_win:]; recent = rets.loc[:d].iloc[-7 * L:]
        score = {}
        for s in elig:
            x = win[s]; ok = x.notna() & win["BTCUSDT"].notna()
            if ok.sum() < beta_win * 0.8 or recent[s].isna().any(): continue
            beta = np.cov(x[ok], win["BTCUSDT"][ok])[0, 1] / win["BTCUSDT"][ok].var()
            score[s] = float((recent[s] - beta * recent["BTCUSDT"]).sum())
        if len(score) < 20: continue
        p = pd.Series(score).sort_values()
        pos += [(s, d, "short") for s in p.index[:5]] + [(s, d, "long") for s in p.index[-5:]]
    return pos


def carry_positions(data, rk, fund, D):
    closes = pd.DataFrame({s: df.set_index(pd.to_datetime(df.ts, unit="ms")).close for s, df in data.items()})
    pos = []
    for d in weekly_dates(closes, 60):
        if d not in rk.index: continue
        r = rk.loc[d]; elig = r[r <= 50].index
        days = [int((d - pd.Timedelta(days=k)).value // 10**6) for k in range(D)]
        score = {}
        for s in elig:
            f = fund.get(s, {})
            if all(t in f for t in days): score[s] = sum(f[t] for t in days) / D * 365   # only coins with full funding data
        if len(score) < 20: continue
        p = pd.Series(score).sort_values()
        pos += [(s, d, "long") for s in p.index[:5]] + [(s, d, "short") for s in p.index[-5:]]   # long lowest, short highest
    return pos


def trades_of(data, fund, positions):
    return [t for s, d, side in positions if (t := pm.momentum_trade(data[s], fund.get(s, {}), d, side))]


def vol_managed(trades, W, cap):
    """Scale every trade of week t by clip(ref / sigma_{t-1..t-W}, 0.25, cap); sigma = std of weekly strategy PnL."""
    t = pd.DataFrame(trades); t["week"] = pd.to_datetime(t.entry_ts, unit="ms").dt.floor("D")
    wk = t.groupby("week").pnl.sum()
    sig = wk.rolling(W, min_periods=max(4, W // 2)).std().shift(1)       # only past weeks
    ref = sig.expanding().median()
    scale = (ref / sig).clip(0.25, cap).fillna(1.0)
    out = []
    for _, r in t.iterrows():
        k = scale.get(r.week, 1.0); d = r.to_dict(); d["pnl"] = r.pnl * k; out.append(d)
    return out, round(float(scale.mean()), 2)


def main():
    data = pickle.loads((CACHE / "universe_daily.pkl").read_bytes())
    fund_raw = pickle.loads((CACHE / "universe_funding.pkl").read_bytes())
    rk100 = pm.rank_table(data, 60)

    # funding for every coin while it is in the top 50 (carry ranks all of them), +15 days of look-back
    windows = {}
    for s in rk100.columns:
        days = rk100.index[(rk100[s] <= 50).fillna(False).values]
        for d in days[::7]:
            t0 = int(d.value // 10**6); windows.setdefault(s, []).append((t0 - 15 * DAY, t0 + 9 * DAY))
    pm.fetch_windows(windows, fund_raw)
    fund = {s: fund_raw.get(s, {}) for s in data}

    base_tr = trades_of(data, fund, pm.momentum_positions(data, rk100, 2, True))
    rows = [ss.summary(base_tr, "PAPER 3 now: momentum 2w long/short")]
    best1 = best2 = best3 = None

    for W, cap in itertools.product([13, 26], [1.0, 1.5]):
        tr, avg = vol_managed(base_tr, W, cap)
        r = ss.summary(tr, f"1 risk-managed momentum: vol {W}w, max {cap}x (avg size {avg}x)"); rows.append(r)
        if best1 is None or r["is_sharpe"] > best1["is_sharpe"]: best1 = r
    resid = {}
    for L, B in itertools.product([2, 4], [60, 120]):
        resid[(L, B)] = trades_of(data, fund, residual_positions(data, rk100, L, B))
        r = ss.summary(resid[(L, B)], f"2 residual momentum {L}w, beta {B}d"); rows.append(r)
        if best2 is None or r["is_sharpe"] > best2["is_sharpe"]: best2 = r; best2_key = (L, B)
    for W, cap in itertools.product([13, 26], [1.0, 1.5]):
        tr, avg = vol_managed(resid[best2_key], W, cap)
        rows.append(ss.summary(tr, f"1+2 risk-managed residual {best2_key[0]}w/{best2_key[1]}d: vol {W}w, max {cap}x (avg {avg}x)"))
    for D in [3, 7, 14]:
        r = ss.summary(trades_of(data, fund, carry_positions(data, rk100, fund, D)), f"3 carry: short highest / long lowest funding, {D}d avg")
        rows.append(r)
        if r["trades"] and (best3 is None or r["is_sharpe"] > best3["is_sharpe"]): best3 = r

    # the other two paper bots
    rk10 = ranks(data); ever10 = [s for s in data if (rk10[s] <= 10).any()]
    long_tr = []
    for s in ever10:
        df = data[s]; top10 = list((rk10[s].reindex(pd.to_datetime(df.ts, unit="ms")) <= 10).fillna(False))
        long_tr += st.run_trend_daily(list(df.open), list(df.high), list(df.low), list(df.close), list(df.ts),
                                      [fund[s].get(int(t), 0.0) for t in df.ts], AMOUNT, LEV, FEE, 0, top10)
    p1 = ss.summary(long_tr, "PAPER 1: long trend top10")
    new = [s for s, df in data.items() if pd.to_datetime(df.ts.iloc[0], unit="ms") >= pd.Timestamp("2021-01-01")]
    lst = []
    for s in new: lst += ss.run_listing_short(data[s], [fund[s].get(int(t), 0.0) for t in data[s].ts], 30, 90, 0.4)
    p2 = ss.summary(pm.cap(lst, 10), "PAPER 2: short new listings max 10")
    p3 = rows[0]

    # best in-sample momentum version overall (baseline, 1, 2 or 1+2)
    mom_rows = [r for r in rows if r["variant"].startswith(("PAPER 3", "1 ", "2 ", "1+2 "))]
    best_mom = max(mom_rows, key=lambda r: r["is_sharpe"])

    def combo(name, parts):
        d = parts[0]["_daily"]
        for p in parts[1:]: d = d.add(p["_daily"], fill_value=0)
        eq = d.cumsum(); sh = lambda x: round(x.mean() / x.std() * math.sqrt(365), 2)
        return {"variant": name, "pnl": round(d.sum()), "maxDD": round(float((eq.cummax() - eq).max())),
                "is_sharpe": sh(d[d.index < CUT]), "oos_sharpe": sh(d[d.index >= CUT]), "oos_pnl": round(d[d.index >= CUT].sum()),
                **{str(y): int(v) for y, v in d.groupby(d.index.year).sum().round(0).items() if y >= 2020}}
    rows = [p1, p2] + rows + [combo("THREE PAPER BOTS NOW", [p1, p2, p3]),
                              combo(f"bots 1+2 + best momentum version", [p1, p2, best_mom]),
                              combo("three bots + best carry", [p1, p2, p3, best3]),
                              combo("bots 1+2 + best momentum version + best carry", [p1, p2, best_mom, best3])]
    out = pd.DataFrame([{k: v for k, v in r.items() if k != "_daily"} for r in rows]).set_index("variant")
    pd.set_option("display.width", 290); pd.set_option("display.max_columns", 30); pd.set_option("display.max_rows", 80)
    cols = [c for c in ["trades", "win%", "pnl", "maxDD", "is_sharpe", "oos_sharpe", "oos_pnl", "2020", "2021", "2022", "2023", "2024", "2025", "2026"] if c in out]
    print(out[cols].to_string())
    print(f"\nbest momentum version on in-sample Sharpe: {best_mom['variant']}")
    print(f"best carry on in-sample Sharpe: {best3['variant']}")


if __name__ == "__main__":
    main()
