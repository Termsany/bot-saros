"""
Improving the new-listing short (research/short_study.py idea 2, the listing_short paper and Demo bot).

Baseline = what runs: short a Binance USDT-M perpetual listed since 2021 on the open 30 days after its first candle,
hold 90 days, stop 40% above entry (before liquidation at x2), at most 10 open; $20 x2, 0.04% fee per side, real
per-coin funding (shorts receive positive funding, pay negative). 2024 lost (new coins rallied); the drawdown is large.

Part 1 — where it loses: by year, by exit reason, and by the conditions at entry.
Part 2 — four filters, fixed before any result was seen, every combination (3 x 3 x 2 x 2 = 36 variants):
  regime:  none | BTC below its 200-day average | BTC's 30-day return below 0      (a falling market lifts shorts)
  prior:   none | the coin is already below its listing-day open | it is not up 50%+ since listing (squeeze risk)
  funding: none | skip when the coin's average funding over the 7 days before entry is negative (crowded shorts)
  take:    none | cover when the price is 60% below entry (most of a short's possible gain, locked)
Chosen on Sharpe before 2024-01-01 with at least 60 trades; 2024 on is out-of-sample. Same cap of 10 open.

  python research/listing_improve_study.py
"""
import sys, pickle, itertools, math
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import short_study as ss
from pump_momentum_study import cap

AMOUNT, LEV, FEE, CUT, CACHE = ss.AMOUNT, ss.LEV, ss.FEE, ss.CUT, ss.CACHE
K, H, S, MAX_OPEN, MIN_TRADES = 30, 90, 0.40, 10, 60


def run(df, funding, take=None):
    """One short per coin: the bot's rule, with an optional cover at `take` below entry. Returns [] or [trade]."""
    o, h, l, c, ts = df.open.values, df.high.values, df.low.values, df.close.values, df.ts.values
    if len(df) <= K + 1: return []
    e = o[K]; q = AMOUNT * LEV / e; stop = e * (1 + S); fund = 0.0
    tp = e * (1 - take) if take else None
    def trade(x, t, why): return {"entry_ts": int(ts[K]), "exit_ts": int(t), "side": "short", "entry": e, "exit": x, "qty": q,
                                  "reason": why, "pnl": (e - x) * q - (e * q + x * q) * FEE + fund}
    for i in range(K, min(len(df), K + H)):
        if h[i] >= stop: return [trade(max(o[i], stop), ts[i], "stop")]
        if tp and l[i] <= tp: return [trade(min(o[i], tp), ts[i], "take")]
        fund += q * c[i] * funding[i]
    j = K + H
    return [trade(o[j], ts[j], "time")] if j < len(df) else [trade(c[-1], ts[-1], "delisted/end")]


def entry_facts(df, funding, btc, ma200, ret30):
    """What was true on the entry day (known at the open: the previous day's close and before)."""
    d = pd.to_datetime(df.ts.iloc[K - 1], unit="ms")                       # the day before entry
    return {"btc_below_200": bool(btc.get(d, np.nan) < ma200.get(d, np.nan)),
            "btc_ret30_neg": bool(ret30.get(d, np.nan) < 0),
            "prior_ret": float(df.close.iloc[K - 1] / df.open.iloc[0] - 1),
            "fund7": float(np.mean(funding[K - 7:K]))}


def keep(f, regime, prior, fund_rule):
    if regime == "btc<200d" and not f["btc_below_200"]: return False
    if regime == "btc30<0" and not f["btc_ret30_neg"]: return False
    if prior == "below_open" and not f["prior_ret"] < 0: return False
    if prior == "not_up50" and not f["prior_ret"] < 0.5: return False
    if fund_rule == "no_neg7" and f["fund7"] < 0: return False
    return True


def main():
    data = pickle.loads((CACHE / "universe_daily.pkl").read_bytes())
    fund_raw = pickle.loads((CACHE / "universe_funding.pkl").read_bytes())
    first = {s: pd.to_datetime(df.ts.iloc[0], unit="ms") for s, df in data.items()}
    new = [s for s in data if first[s] >= pd.Timestamp("2021-01-01")]
    fund = {s: [fund_raw.get(s, {}).get(int(t), 0.0) for t in data[s].ts] for s in new}
    b = data["BTCUSDT"]; btc = pd.Series(b.close.values, index=pd.to_datetime(b.ts, unit="ms"))
    ma200, ret30 = btc.rolling(200).mean(), btc / btc.shift(30) - 1

    facts, base_tr = {}, {}
    for s in new:
        if len(data[s]) <= K + 1: continue
        facts[s] = entry_facts(data[s], fund[s], btc, ma200, ret30)
        base_tr[s] = run(data[s], fund[s])
    pd.set_option("display.width", 260); pd.set_option("display.max_columns", 30); pd.set_option("display.max_rows", 80)

    # ── part 1: the baseline, and where it loses ──
    base = cap([t for tr in base_tr.values() for t in tr], MAX_OPEN)
    r0 = ss.summary(base, "baseline: 30d / hold 90 / stop 40% / max 10")
    t = pd.DataFrame(base); t["year"] = pd.to_datetime(t.entry_ts, unit="ms").dt.year
    sym = {(tr[0]["entry_ts"], round(tr[0]["entry"], 12)): s for s, tr in base_tr.items() if tr}
    t["sym"] = [sym.get((a, round(e, 12))) for a, e in zip(t.entry_ts, t.entry)]
    for k in ("btc_below_200", "btc_ret30_neg", "prior_ret", "fund7"): t[k] = [facts[s][k] for s in t.sym]
    print(f"new listings since 2021: {len(new)} | traded after the cap: {len(t)}\n")
    print("== part 1: baseline by year of entry")
    print(t.groupby("year").agg(trades=("pnl", "size"), pnl=("pnl", "sum"), win=("pnl", lambda x: round((x > 0).mean() * 100)),
                                stops=("reason", lambda x: int((x == "stop").sum()))).round(0).to_string())
    print("\n== by exit reason"); print(t.groupby("reason").pnl.agg(["size", "sum", "mean"]).round(1).to_string())
    print("\n== by conditions at entry (all years)")
    for col, cut in [("btc_below_200", None), ("btc_ret30_neg", None), ("prior_ret", [-1, -0.3, 0, 0.5, 100]), ("fund7", [-1, 0, 0.0003, 1])]:
        g = t[col] if cut is None else pd.cut(t[col], cut)
        print(t.groupby(g, observed=True).pnl.agg(trades="size", pnl="sum", avg="mean").round(1).to_string(), "\n")

    # ── part 2: the 36 variants, chosen before 2024 ──
    rows = []
    for regime, prior, fund_rule, take in itertools.product(["none", "btc<200d", "btc30<0"], ["none", "below_open", "not_up50"],
                                                            ["none", "no_neg7"], [None, 0.60]):
        tr = []
        for s in facts:
            if not keep(facts[s], regime, prior, fund_rule): continue
            tr += base_tr[s] if take is None else run(data[s], fund[s], take)
        r = ss.summary(cap(tr, MAX_OPEN), f"{regime} | {prior} | {fund_rule} | take {'60%' if take else '-'}")
        rows.append(r)
    out = pd.DataFrame([{k: v for k, v in r.items() if k != "_daily"} for r in rows]).set_index("variant")
    cols = [c for c in ["trades", "win%", "pnl", "maxDD", "is_sharpe", "oos_sharpe", "oos_pnl", "2021", "2022", "2023", "2024", "2025", "2026"] if c in out]
    print("== part 2: every variant (is = before 2024, oos = 2024 on)")
    print(out[cols].sort_values("is_sharpe", ascending=False).to_string())
    ok = out[out.trades >= MIN_TRADES]
    pick = ok.is_sharpe.idxmax()
    print(f"\nbaseline:  {r0['trades']} trades | pnl {r0['pnl']} | maxDD {r0['maxDD']} | is {r0['is_sharpe']} | oos {r0['oos_sharpe']} | oos pnl {r0['oos_pnl']}")
    p = out.loc[pick]
    print(f"in-sample pick: {pick}\n           {int(p.trades)} trades | pnl {int(p.pnl)} | maxDD {int(p.maxDD)} | is {p.is_sharpe} | oos {p.oos_sharpe} | oos pnl {int(p.oos_pnl)}")
    print(f"variants beating the baseline out-of-sample (Sharpe): {int((out.oos_sharpe > r0['oos_sharpe']).sum())} of {len(out)}")


if __name__ == "__main__":
    main()
