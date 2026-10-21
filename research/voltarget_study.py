"""
Volatility-targeted size on the bot's current strategies (1h/4h, the cached sets of measure_strategies.py).

Exits are % of price (SL 3% / TP 6%), so a trade's PnL scales with its size: each trade is re-sized by
k = clip(ref / vol, 0.25, 1) at entry — vol = std of the last 30 candle returns, ref = median of that
over the previous 500 candles (no look-ahead). k never exceeds 1: never bigger than the bot's $20 x5 today.
Moreira & Muir (2017) "Volatility-Managed Portfolios", JF.

  python research/voltarget_study.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np, pandas as pd
import measure_strategies as ms

STRATS = [s for s in ms.STRATEGIES if s != "wave_flats"]


def stats(p):
    p = np.array(p); eq = np.cumsum(np.r_[0, p]); dd = float(np.max(np.maximum.accumulate(eq) - eq))
    gw, gl = p[p > 0].sum(), -p[p <= 0].sum()
    return {"pnl": p.sum(), "dd": dd, "pf": gw / gl if gl else 0}


def main():
    rows = []
    for sym in ms.SYMBOLS:
        for tf in ms.TIMEFRAMES:
            df, sc = ms.candles(sym, tf), ms.signals(sym, tf)
            vol = df.close.pct_change().rolling(30).std()
            ref = vol.rolling(500, min_periods=100).median().shift(1)
            k = (ref / vol).clip(0.25, 1.0).fillna(1.0)
            pos_of = {t: i for i, t in enumerate(df.ts)}
            cut = df.ts.iloc[int(len(df) * ms.OOS_SPLIT)]
            for s in STRATS:
                tr = ms.run(df, sc, s)
                for t in tr:
                    i = pos_of[pd.Timestamp(t["entry_ts"])]
                    rows.append({"s": s, "set": f"{sym} {tf}", "oos": pd.Timestamp(t["entry_ts"]) >= cut,
                                 "fixed": t["pnl"], "vol": t["pnl"] * k.iloc[i], "k": k.iloc[i]})
    r = pd.DataFrame(rows)
    out = []
    for s, g in r.groupby("s"):
        row = {"strategy": s, "avg_size": round(g.k.mean(), 2)}
        for part, gg in (("all", g), ("oos", g[g.oos])):
            for mode in ("fixed", "vol"):
                st_sets = [stats(x[mode].tolist()) for _, x in gg.groupby("set")]
                pnl = sum(x["pnl"] for x in st_sets); dd = np.median([x["dd"] for x in st_sets])
                row[f"{part}_{mode}_pnl"] = round(pnl, 1); row[f"{part}_{mode}_dd"] = round(dd, 1)
                row[f"{part}_{mode}_won"] = sum(x["pnl"] > 0 for x in st_sets)
                row[f"{part}_{mode}_pnl/dd"] = round(pnl / dd, 2) if dd else 0
        out.append(row)
    o = pd.DataFrame(out).sort_values("all_fixed_pnl", ascending=False)
    pd.set_option("display.width", 250)
    print(o[["strategy", "avg_size", "all_fixed_pnl", "all_vol_pnl", "all_fixed_dd", "all_vol_dd", "all_fixed_pnl/dd", "all_vol_pnl/dd",
             "oos_fixed_pnl", "oos_vol_pnl", "oos_fixed_won", "oos_vol_won", "oos_fixed_pnl/dd", "oos_vol_pnl/dd"]].to_string(index=False))
    better = (o["all_vol_pnl/dd"] > o["all_fixed_pnl/dd"]).sum(), (o["oos_vol_pnl/dd"] > o["oos_fixed_pnl/dd"]).sum()
    print(f"PnL/drawdown better with vol sizing: whole period {better[0]}/{len(o)}, out-of-sample {better[1]}/{len(o)}")


if __name__ == "__main__":
    main()
