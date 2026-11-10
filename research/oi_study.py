"""
Open-interest and positioning signals (owner, 2026-11-07). Data: research/oi_data.py (Binance daily metrics since
2021 for every coin ever in the top 20 by volume, delisted included). Universe each day: the previous day's top 20
by 30-day volume — every one of them has data, so no hindsight in the coin list. Every variant fixed before any result.

X. Weekly long/short baskets (as momentum_ls: rank at the daily close, 3 long + 3 short, held 7 days, 40% guard):
   X1 open-interest growth (coins, so price doesn't count) over L days — long the fastest growth (Hong & Yogo 2012:
      open-interest growth predicts futures returns)
   X2 OI up while the price is down — rank(OI growth) − rank(return): long the crowded shorts (squeeze), short the
      crowded longs
   X3 retail contrarian — long the lowest all-accounts long/short ratio, short the highest (sentiment as a contrarian
      signal; Baker & Wurgler 2006, crypto positioning studies)
   X4 top traders — long the biggest rise in their position long/short ratio ("smart money")
   X5 taker flow — long the highest average taker buy/sell ratio (order-flow persistence; Chordia & Subrahmanyam 2004)
   L = 3 or 7 days -> 10 variants
   (from 2021-12: Binance publishes these files for most coins only since then)
F. Liquidation flush (long only): open interest down k% in a day and the price down 5%+ -> buy the next open, hold
   H days, 40% guard. k = 10 / 20 %, H = 3 / 7 -> 4 variants.

$20 margin x2 a leg, fees 0.04% a side, real per-coin funding. Pick: best Sharpe before 2024 (60+ trades); then
after 2024, and next to momentum_ls (does it add to the bot that runs?).

  RAQM_RESEARCH_CACHE=/opt/raqm-data/research python research/oi_study.py
"""
import itertools, math, os, pickle, sys
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import strategies_trend as st
import pump_momentum_study as pm
from universe_study import ranks

CACHE = Path(os.getenv("RAQM_RESEARCH_CACHE") or Path(__file__).resolve().parent / ".cache")
AMOUNT, LEV, FEE, CUT, MIN_TRADES, TOP, N = 20, 2, 0.0004, pd.Timestamp("2024-01-01"), 60, 20, 3
START = pd.Timestamp("2021-12-01")                     # Binance metrics files start 2021-12 for most coins


def hold_trade(df, fund, d, side, H):
    """pm.momentum_trade with H days instead of 7: the next open after d's close, the 40% guard, out at the open H days on."""
    idx = pd.to_datetime(df.ts, unit="ms"); k = idx.searchsorted(d) + 1
    if k >= len(df): return None
    o, h, l, c, ts = df.open.values, df.high.values, df.low.values, df.close.values, df.ts.values
    sg = 1 if side == "long" else -1
    e = o[k]; q = AMOUNT * LEV / e; stop = e * (1 - sg * st.STOP_SHARE / LEV); fu = 0.0
    for j in range(k, min(len(df), k + H)):
        if (sg == -1 and h[j] >= stop) or (sg == 1 and l[j] <= stop):
            x = max(o[j], stop) if sg == -1 else min(o[j], stop)
            return dict(entry_ts=int(ts[k]), exit_ts=int(ts[j]), side=side, entry=e, exit=x, pnl=sg * (x - e) * q - (e + x) * q * FEE + fu)
        fu += -sg * q * c[j] * fund.get(int(ts[j]), 0.0)
    j = k + H
    x, t = (o[j], ts[j]) if j < len(df) else (c[-1], ts[-1])
    return dict(entry_ts=int(ts[k]), exit_ts=int(t), side=side, entry=e, exit=x, pnl=sg * (x - e) * q - (e + x) * q * FEE + fu)


def panel(oi, col):
    return pd.DataFrame({s: d.set_index(pd.to_datetime(d.ts, unit="ms"))[col] for s, d in oi.items() if col in d}).sort_index()


def scores(kind, L, P):
    if kind == "X1": return P["oi"] / P["oi"].shift(L) - 1
    if kind == "X2":
        g = (P["oi"] / P["oi"].shift(L) - 1).rank(axis=1, pct=True); r = (P["close"] / P["close"].shift(L) - 1).rank(axis=1, pct=True)
        return g - r
    if kind == "X3": return -P["ls_acc"].rolling(L).mean()
    if kind == "X4": return P["top_pos"] - P["top_pos"].shift(L)
    if kind == "X5": return P["taker"].rolling(L).mean()


def baskets(data, fund, member, score, n=N):
    out = []
    days = [d for d in score.index if d >= START][::7]
    for d in days:
        if d not in member.index: continue
        m = member.loc[d]; p = score.loc[d, [s for s in m[m].index if s in score.columns]].dropna()
        if len(p) < 2 * n + 2: continue
        p = p.sort_values()
        for s, side in [(x, "short") for x in p.index[:n]] + [(x, "long") for x in p.index[-n:]]:
            if (t := hold_trade(data[s], fund[s], d, side, 7)): out.append(dict(t, symbol=s))
    return out


def flush(data, fund, member, P, k, H):
    doi = P["oi"] / P["oi"].shift(1) - 1; ret = P["close"] / P["close"].shift(1) - 1
    ev = (doi <= -k) & (ret <= -0.05)
    out = []
    for s in ev.columns:
        last_exit = 0
        for d in ev.index[ev[s].fillna(False).to_numpy()]:
            if d < START or d not in member.index or not member.at[d, s]: continue
            if int(d.value // 1_000_000) < last_exit: continue                     # one trade at a time per coin
            if (t := hold_trade(data[s], fund[s], d, "long", H)):
                out.append(dict(t, symbol=s)); last_exit = t["exit_ts"]
    return out


def daily(trades):
    t = pd.DataFrame(trades); t["d"] = pd.to_datetime(t.exit_ts, unit="ms").dt.floor("D")
    x = t.groupby("d").pnl.sum()
    return x.reindex(pd.date_range(START, x.index.max()), fill_value=0)


def summary(trades):
    if len(trades) < 10: return None
    t = pd.DataFrame(trades); dd = daily(trades); eq = dd.cumsum()
    a = t[pd.to_datetime(t.exit_ts, unit="ms") >= CUT]
    def sh(x): return round(float(x.mean() / x.std() * math.sqrt(365)), 2) if x.std() else 0.0
    def pf(p): return round(float(p[p > 0].sum() / -p[p <= 0].sum()), 2) if (p <= 0).any() else None
    return {"trades": len(t), "win": round(float((t.pnl > 0).mean() * 100), 1), "pf": pf(t.pnl), "pf_after": pf(a.pnl),
            "pnl": round(float(t.pnl.sum())), "max_dd": round(float((eq.cummax() - eq).max())),
            "is": sh(dd[dd.index < CUT]), "oos": sh(dd[dd.index >= CUT]), "pnl_after": round(float(a.pnl.sum())), "_daily": dd}


def main():
    data = pickle.loads((CACHE / "universe_daily.pkl").read_bytes())
    fund_raw = pickle.loads((CACHE / "universe_funding.pkl").read_bytes())
    fund = {s: fund_raw.get(s, {}) for s in data}
    oi = {p.stem: pickle.loads(p.read_bytes()) for p in (CACHE / "oi").glob("*.pkl")}
    member = (ranks(data) <= TOP).shift(1, fill_value=False)              # yesterday's top 20
    cover = member.loc[member.index >= START].sum().pipe(lambda s: s[s > 0])
    missing = [s for s in cover.index if s not in oi]
    print(f"{len(oi)} coins with OI data; top-20 members since 2021 without it: {missing}")
    P = {c: panel(oi, c) for c in ("oi", "ls_acc", "top_pos", "taker")}
    P["close"] = pd.DataFrame({s: d.set_index(pd.to_datetime(d.ts, unit="ms")).close for s, d in data.items() if s in oi}).sort_index()
    idx = P["close"].index
    P = {k: v.reindex(idx) for k, v in P.items()}

    rows = {}
    for kind, L in itertools.product(("X1", "X2", "X3", "X4", "X5"), (3, 7)):
        rows[f"{kind} L{L}"] = summary(baskets(data, fund, member, scores(kind, L, P)))
    for k, H in itertools.product((0.10, 0.20), (3, 7)):
        rows[f"F flush OI-{int(k * 100)}% hold{H}"] = summary(flush(data, fund, member, P, k, H))
    rows["(ref) momentum 2w, same top 20, 3+3"] = summary(baskets(data, fund, member, P["close"] / P["close"].shift(14) - 1))

    print("variant | trades | win% | PF | PF 2024-> | PnL | maxDD | Sharpe<2024 | Sharpe 2024-> | PnL 2024->")
    for k, r in rows.items():
        if r: print(f"{k} | {r['trades']} | {r['win']} | {r['pf']} | {r['pf_after']} | {r['pnl']} | {r['max_dd']} | {r['is']} | {r['oos']} | {r['pnl_after']}")
    ok = {k: r for k, r in rows.items() if r and r["trades"] >= MIN_TRADES and not k.startswith("(ref)")}
    pick = max(ok, key=lambda k: ok[k]["is"])
    print(f"\nin-sample pick: {pick} -> Sharpe after 2024 {ok[pick]['oos']}, PnL after {ok[pick]['pnl_after']}")
    print(f"variants positive after 2024: {sum(r['pnl_after'] > 0 for r in ok.values())} / {len(ok)}")

    rk60 = pm.rank_table(data, 60)
    mom = [dict(t, symbol=s) for s, d, side in pm.momentum_positions(data, rk60, 2, True) if (t := pm.momentum_trade(data[s], fund[s], d, side))]
    m = daily(mom); x = ok[pick]["_daily"].reindex(m.index, fill_value=0)
    def sh(v): return round(float(v.mean() / v.std() * math.sqrt(365)), 2)
    both = m + x
    print(f"momentum_ls alone: Sharpe <2024 {sh(m[m.index < CUT])} / 2024-> {sh(m[m.index >= CUT])}; "
          f"+ pick: {sh(both[both.index < CUT])} / {sh(both[both.index >= CUT])}; correlation after 2024 {m[m.index >= CUT].corr(x[x.index >= CUT]):.2f}")
    # after the fact (not the pick rule): every variant with a positive Sharpe in both periods, next to momentum_ls
    for k, r in ok.items():
        if r["is"] > 0 and r["oos"] > 0:
            x = r["_daily"].reindex(m.index, fill_value=0); both = m + x
            print(f"  both periods positive: {k} -> + momentum_ls: {sh(both[both.index < CUT])} / {sh(both[both.index >= CUT])}; "
                  f"correlation {m.corr(x):.2f}; max DD together {round(float((both.cumsum().cummax() - both.cumsum()).max()))} "
                  f"(momentum alone {round(float((m.cumsum().cummax() - m.cumsum()).max()))})")


if __name__ == "__main__":
    main()
