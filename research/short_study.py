"""
Two short ideas next to the daily long trend, on every Binance USDT-M perpetual since 2019 (delisted included),
with real per-coin funding (shorts receive positive funding, pay negative) and 0.04% fees. $20 margin x2.

1. Bear-trend short: short a top-10-by-volume coin when it is below its close 20/60/120 days ago
   (all 3, or 2 of 3), optionally only while BTC is below its 200-day average; cover when that ends.
   Literature: Moskowitz, Ooi & Pedersen (2012); Faber (2007) for the 200-day regime filter.
2. New-listing short: short a newly listed perpetual K days after its first candle, hold H days,
   stop S above entry. Literature: Benedetti & Kostovetsky (2021) "Digital Tulips?" (new tokens underperform).
   "New listing" = a new Binance USDT-M perpetual from 2021 on (older coins added to futures count too).

Variants are ranked by Sharpe of daily realised PnL before 2024-01-01; 2024 onwards is out-of-sample.

  python research/universe_data.py && python research/universe_funding.py && python research/short_study.py
"""
import os
import sys, pickle, itertools, math
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import strategies_trend as st
from universe_study import ranks

CACHE = Path(os.getenv("RAQM_RESEARCH_CACHE") or Path(__file__).resolve().parent / ".cache")   # shared store: research/README.md
AMOUNT, LEV, FEE, CUT = 20, 2, 0.0004, pd.Timestamp("2024-01-01")
STOP_SHARE = st.STOP_SHARE


# ── idea 1: bear-trend short ──
def run_trend_short(o, h, l, c, ts, funding, allowed, regime, rule, exit_on_regime):
    n = len(c); trades = []; pos = None; pending = None; size = 1.0
    def close(price, t, reason):
        q = pos["qty"]
        return {"entry_ts": pos["ts"], "exit_ts": t, "side": "short", "entry": pos["entry"], "exit": price, "qty": q, "reason": reason,
                "pnl": (pos["entry"] - price) * q - (pos["entry"] * q + price * q) * FEE + pos["funding"]}
    for i in range(n):
        if pending == "sell":
            q = AMOUNT * LEV * size / o[i]
            pos = {"entry": o[i], "qty": q, "ts": ts[i], "funding": 0.0, "stop": o[i] * (1 + STOP_SHARE / LEV)}
        elif pending == "cover" and pos:
            trades.append(close(o[i], ts[i], "signal off")); pos = None
        pending = None
        if pos:
            if h[i] >= pos["stop"]:
                trades.append(close(max(o[i], pos["stop"]), ts[i], "stop")); pos = None
            else:
                pos["funding"] += pos["qty"] * c[i] * funding[i]      # positive funding: shorts receive
        if i + 1 < n and i >= max(st.LOOKBACKS):
            ups = sum(c[i] > c[i - L] for L in st.LOOKBACKS)
            down = ups == 0 if rule == "all3" else ups <= 1
            on = down and (regime is None or regime[i])
            if pos is None and on and allowed[i]:
                pending, size = "sell", st.size_factor(c, i)
            elif pos is not None and (not down or (exit_on_regime and regime is not None and not regime[i])):
                pending = "cover"
    if pos: trades.append(close(c[-1], ts[-1], "close"))
    return trades


# ── idea 2: new-listing short ──
def run_listing_short(df, funding, K, H, S):
    o, h, c, ts = df.open.values, df.high.values, df.close.values, df.ts.values
    if len(df) <= K + 1: return []
    e = o[K]; q = AMOUNT * LEV / e; stop = e * (1 + S); fund = 0.0
    for i in range(K, min(len(df), K + H)):
        if h[i] >= stop:
            x = max(o[i], stop)
            return [{"entry_ts": int(ts[K]), "exit_ts": int(ts[i]), "side": "short", "entry": e, "exit": x, "qty": q, "reason": "stop",
                     "pnl": (e - x) * q - (e * q + x * q) * FEE + fund}]
        fund += q * c[i] * funding[i]
    j = K + H
    x, t, why = (o[j], ts[j], "time") if j < len(df) else (c[-1], ts[-1], "delisted/end")
    return [{"entry_ts": int(ts[K]), "exit_ts": int(t), "side": "short", "entry": e, "exit": x, "qty": q, "reason": why,
             "pnl": (e - x) * q - (e * q + x * q) * FEE + fund}]


def summary(trades, label):
    if not trades: return {"variant": label, "trades": 0}
    t = pd.DataFrame(trades)
    t["exit"] = pd.to_datetime(t.exit_ts, unit="ms").dt.floor("D"); t["entry_d"] = pd.to_datetime(t.entry_ts, unit="ms")
    daily = t.groupby("exit").pnl.sum()
    daily = daily.reindex(pd.date_range("2019-09-01", daily.index.max()), fill_value=0)
    eq = daily.cumsum(); dd = float((eq.cummax() - eq).max())
    ev = pd.concat([pd.Series(1, index=t.entry_d), pd.Series(-1, index=t.exit)]).sort_index().cumsum()
    def sh(d): return round(d.mean() / d.std() * math.sqrt(365), 2) if d.std() else 0.0
    years = daily.groupby(daily.index.year).sum().round(0).astype(int)
    return {"variant": label, "trades": len(t), "win%": round((t.pnl > 0).mean() * 100), "pnl": round(daily.sum()), "maxDD": round(dd),
            "is_sharpe": sh(daily[daily.index < CUT]), "oos_sharpe": sh(daily[daily.index >= CUT]),
            "oos_pnl": round(daily[daily.index >= CUT].sum()), "max_open": int(ev.max()),
            **{str(y): int(v) for y, v in years.items() if y >= 2020}, "_daily": daily}


def main():
    data = pickle.loads((CACHE / "universe_daily.pkl").read_bytes())
    fund_raw = pickle.loads((CACHE / "universe_funding.pkl").read_bytes())
    fund = {s: [fund_raw.get(s, {}).get(int(t), 0.0) for t in df.ts] for s, df in data.items()}
    rk = ranks(data)
    top10 = {s: list((rk[s].reindex(pd.to_datetime(df.ts, unit="ms")) <= 10).fillna(False)) for s, df in data.items()}

    btc = data["BTCUSDT"].set_index(pd.to_datetime(data["BTCUSDT"].ts, unit="ms")).close
    bear = (btc < btc.rolling(200).mean())
    rows = []

    # baseline: the bot's long trend (top 10 by volume), real funding
    long_tr = []
    for s, df in data.items():
        if not any(top10[s]): continue
        long_tr += st.run_trend_daily(list(df.open), list(df.high), list(df.low), list(df.close), list(df.ts), fund[s], AMOUNT, LEV, FEE, 0, top10[s])
    base = summary(long_tr, "LONG trend top10 (the bot)"); rows.append(base)

    # idea 1
    best1 = None
    for rule, use_regime, exit_reg in itertools.product(["all3", "2of3"], [True, False], [False, True]):
        if not use_regime and exit_reg: continue
        tr = []
        for s, df in data.items():
            if not any(top10[s]): continue
            idx = pd.to_datetime(df.ts, unit="ms")
            reg = list(bear.reindex(idx).fillna(False)) if use_regime else None
            tr += run_trend_short(df.open.values, df.high.values, df.low.values, df.close.values, list(df.ts), fund[s], top10[s], reg, rule, exit_reg)
        r = summary(tr, f"1 SHORT trend {rule}{' +BTC<200d' if use_regime else ''}{' exit-on-regime' if exit_reg else ''}")
        rows.append(r)
        if r["trades"] and (best1 is None or r["is_sharpe"] > best1["is_sharpe"]): best1 = r

    # idea 2
    best2 = None
    first = {s: pd.to_datetime(df.ts.iloc[0], unit="ms") for s, df in data.items()}
    new = [s for s in data if first[s] >= pd.Timestamp("2021-01-01")]
    for K, H, S in itertools.product([3, 14, 30], [30, 60, 90], [0.25, STOP_SHARE / LEV]):
        tr = []
        for s in new: tr += run_listing_short(data[s], fund[s], K, H, S)
        r = summary(tr, f"2 SHORT new listing skip {K}d hold {H}d stop {S:.0%}")
        rows.append(r)
        if r["trades"] and (best2 is None or r["is_sharpe"] > best2["is_sharpe"]): best2 = r

    # combinations with the long trend (chosen on in-sample Sharpe)
    for name, parts in [("LONG + best idea 1", [base, best1]), ("LONG + best idea 2", [base, best2]), ("LONG + both", [base, best1, best2])]:
        d = parts[0]["_daily"]
        for p in parts[1:]: d = d.add(p["_daily"], fill_value=0)   # different date ranges: missing days = 0
        eq = d.cumsum()
        rows.append({"variant": name, "pnl": round(d.sum()), "maxDD": round(float((eq.cummax() - eq).max())),
                     "is_sharpe": round(d[d.index < CUT].mean() / d[d.index < CUT].std() * math.sqrt(365), 2),
                     "oos_sharpe": round(d[d.index >= CUT].mean() / d[d.index >= CUT].std() * math.sqrt(365), 2),
                     "oos_pnl": round(d[d.index >= CUT].sum()), **{str(y): int(v) for y, v in d.groupby(d.index.year).sum().round(0).items() if y >= 2020}})
    out = pd.DataFrame([{k: v for k, v in r.items() if k != "_daily"} for r in rows]).set_index("variant")
    pd.set_option("display.width", 260); pd.set_option("display.max_columns", 30); pd.set_option("display.max_rows", 60)
    cols = [c for c in ["trades", "win%", "pnl", "maxDD", "is_sharpe", "oos_sharpe", "oos_pnl", "max_open", "2020", "2021", "2022", "2023", "2024", "2025", "2026"] if c in out]
    print(out[cols].to_string())
    print(f"\nchosen on in-sample Sharpe: idea 1 = {best1['variant']} | idea 2 = {best2['variant']}")
    print(f"new listings tested: {len(new)} (since 2021, delisted included)")


if __name__ == "__main__":
    main()
