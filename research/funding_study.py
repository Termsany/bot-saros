"""
Idea 3: short when funding is extreme (crowded leveraged longs), on the top 10 coins by volume.
Literature: Schmeling, Schrimpf & Todorov (2023) "Crypto Carry", BIS working paper — high funding/carry predicts
lower returns and crash risk. While short, the position also receives the high funding.

Rules (daily close, next open): short a top-10 coin when its average daily funding over the last W days, annualised,
is above T; cover when that average falls below T/3 or after H days at most; protective stop entry x (1 + 0.8/lev).
Optional filter: only if the close is below the close 7 days ago (the crowd is long but price already stalls).
Real per-coin funding, fees 0.04%, $20 x2; chosen on Sharpe before 2024 like the other studies.

  python research/universe_data.py && python research/universe_funding.py && python research/funding_study.py
"""
import sys, pickle, itertools, math
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import short_study as ss
import strategies_trend as st
from universe_study import ranks

AMOUNT, LEV, FEE, CUT = ss.AMOUNT, ss.LEV, ss.FEE, ss.CUT


def run_funding_short(df, fund, allowed, W, T, H, stall):
    o, h, c, ts = df.open.values, df.high.values, df.close.values, list(df.ts)
    f = pd.Series(fund).rolling(W).mean().values * 365          # annualised average funding, last W days
    n = len(c); trades = []; pos = None; pending = None
    def close(price, t, reason):
        q = pos["qty"]
        return {"entry_ts": pos["ts"], "exit_ts": t, "side": "short", "entry": pos["entry"], "exit": price, "qty": q, "reason": reason,
                "pnl": (pos["entry"] - price) * q - (pos["entry"] * q + price * q) * FEE + pos["funding"]}
    for i in range(n):
        if pending == "sell":
            q = AMOUNT * LEV / o[i]
            pos = {"entry": o[i], "qty": q, "ts": ts[i], "i": i, "funding": 0.0, "stop": o[i] * (1 + st.STOP_SHARE / LEV)}
        elif pending == "cover" and pos:
            trades.append(close(o[i], ts[i], "funding normal" if pend_reason == "f" else "time")); pos = None
        pending = None
        if pos:
            if h[i] >= pos["stop"]:
                trades.append(close(max(o[i], pos["stop"]), ts[i], "stop")); pos = None
            else:
                pos["funding"] += pos["qty"] * c[i] * fund[i]
        if i + 1 < n and i >= 7 and not np.isnan(f[i]):
            if pos is None and f[i] > T and allowed[i] and (not stall or c[i] < c[i - 7]):
                pending = "sell"
            elif pos is not None and (f[i] < T / 3 or i - pos["i"] >= H):
                pending, pend_reason = "cover", ("f" if f[i] < T / 3 else "t")
    if pos: trades.append(close(c[-1], ts[-1], "close"))
    return trades


def main():
    C = ss.CACHE
    data = pickle.loads((C / "universe_daily.pkl").read_bytes())
    fr = pickle.loads((C / "universe_funding.pkl").read_bytes())
    rk = ranks(data)
    ever10 = [s for s in data if (rk[s] <= 10).any()]
    top10 = {s: list((rk[s].reindex(pd.to_datetime(data[s].ts, unit="ms")) <= 10).fillna(False)) for s in ever10}
    fund = {s: [fr.get(s, {}).get(int(t), 0.0) for t in data[s].ts] for s in ever10}

    # baselines: the long trend and the capped new-listing short (as running on paper)
    long_tr = []
    for s in ever10:
        df = data[s]
        long_tr += st.run_trend_daily(list(df.open), list(df.high), list(df.low), list(df.close), list(df.ts), fund[s], AMOUNT, LEV, FEE, 0, top10[s])
    base = ss.summary(long_tr, "LONG trend top10 (the bot)")
    new = [s for s, df in data.items() if pd.to_datetime(df.ts.iloc[0], unit="ms") >= pd.Timestamp("2021-01-01")]
    cands = []
    for s in new:
        fu = [fr.get(s, {}).get(int(t), 0.0) for t in data[s].ts]
        cands += ss.run_listing_short(data[s], fu, 30, 90, 0.4)
    cands.sort(key=lambda t: t["entry_ts"]); listing, open_ = [], []
    for t in cands:
        open_ = [x for x in open_ if x > t["entry_ts"]]
        if len(open_) < 10: listing.append(t); open_.append(t["exit_ts"])
    lst = ss.summary(listing, "SHORT new listings, max 10 (paper bot)")

    rows = [base, lst]; best = None
    for W, T, H, stall in itertools.product([1, 3, 7], [0.3, 0.6, 1.0], [10, 30], [False, True]):
        tr = []
        for s in ever10: tr += run_funding_short(data[s], fund[s], top10[s], W, T, H, stall)
        r = ss.summary(tr, f"3 SHORT funding>{T:.0%}/yr avg {W}d, max {H}d{' +price stalls' if stall else ''}")
        rows.append(r)
        if r["trades"] and (best is None or r["is_sharpe"] > best["is_sharpe"]): best = r

    def combo(name, parts):
        d = parts[0]["_daily"]
        for p in parts[1:]: d = d.add(p["_daily"], fill_value=0)
        eq = d.cumsum(); sh = lambda x: round(x.mean() / x.std() * math.sqrt(365), 2)
        return {"variant": name, "pnl": round(d.sum()), "maxDD": round(float((eq.cummax() - eq).max())),
                "is_sharpe": sh(d[d.index < CUT]), "oos_sharpe": sh(d[d.index >= CUT]), "oos_pnl": round(d[d.index >= CUT].sum()),
                **{str(y): int(v) for y, v in d.groupby(d.index.year).sum().round(0).items() if y >= 2020}}
    rows += [combo("LONG + new listings (running now)", [base, lst]), combo("LONG + best funding short", [base, best]),
             combo("LONG + new listings + best funding short", [base, lst, best])]
    out = pd.DataFrame([{k: v for k, v in r.items() if k != "_daily"} for r in rows]).set_index("variant")
    pd.set_option("display.width", 260); pd.set_option("display.max_columns", 30); pd.set_option("display.max_rows", 80)
    cols = [c for c in ["trades", "win%", "pnl", "maxDD", "is_sharpe", "oos_sharpe", "oos_pnl", "max_open", "2020", "2021", "2022", "2023", "2024", "2025", "2026"] if c in out]
    print(out[cols].to_string())
    print(f"\nchosen on in-sample Sharpe: {best['variant']}")
    # how often is funding that high at all (top-10 coin-days)
    allf = pd.concat([pd.Series(fund[s]).rolling(3).mean() * 365 for s in ever10])
    print("share of coin-days with 3-day funding above 30% / 60% / 100% a year:",
          " / ".join(f"{(allf > t).mean() * 100:.1f}%" for t in (0.3, 0.6, 1.0)))


if __name__ == "__main__":
    main()
