"""
Daily trend on a volume-ranked universe: each day, new entries only for the top N coins by average USDT
volume over the last 30 days (among coins with >= 150 days of history). Compared with the fixed 8 coins.

  python research/universe_data.py && python research/universe_study.py

All Binance USDT-M perpetuals, delisted ones included (no survivorship bias in the ranking).
Funding: the daily median of the 8 coins' real funding (per-coin funding history isn't fetched).
$20 margin x2 per trade, fees 0.04% per side. In-sample before 2024-01-01, out-of-sample after.
"""
import sys, pickle
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import strategies_trend as st

CACHE = Path(__file__).resolve().parent / ".cache"
EIGHT = ["BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "LINK"]
SIZES = [5, 10, 15, 20, 30]
MIN_HISTORY, VOL_WINDOW, LEV, CUT = 150, 30, 2, pd.Timestamp("2024-01-01")


def funding_proxy():
    f = pd.concat([pickle.loads((CACHE / f"trend_{c}.pkl").read_bytes()).set_index("ts").funding.rename(c) for c in EIGHT], axis=1)
    return f.median(axis=1)


def ranks(data):
    """DataFrame (day x symbol) of the 30-day average USDT volume rank, NaN where the coin isn't eligible."""
    vol = {}
    for sym, df in data.items():
        v = df.set_index(pd.to_datetime(df.ts, unit="ms")).qvol.rolling(VOL_WINDOW).mean()
        v.iloc[:MIN_HISTORY - 1] = np.nan
        vol[sym] = v
    return pd.DataFrame(vol).rank(axis=1, ascending=False)


def run_set(data, fund, allowed_of):
    trades = []
    for sym, df in data.items():
        idx = pd.to_datetime(df.ts, unit="ms")
        allowed = allowed_of(sym, idx)
        if allowed is not None and not any(allowed): continue
        fu = list(fund.reindex(idx).fillna(0.0))
        for t in st.run_trend_daily(list(df.open), list(df.high), list(df.low), list(df.close), list(df.ts), fu, 20, LEV, 0.0004, 0, allowed):
            trades.append({**t, "symbol": sym})
    return trades


def summary(trades):
    t = pd.DataFrame(trades)
    t["exit"] = pd.to_datetime(t.exit_ts, unit="ms"); t["entry_d"] = pd.to_datetime(t.entry_ts, unit="ms")
    daily = t.groupby(t.exit.dt.floor("D")).pnl.sum()
    daily = daily.reindex(pd.date_range(daily.index.min(), daily.index.max()), fill_value=0)
    eq = daily.cumsum(); dd = (eq.cummax() - eq).max()
    # most positions open at once -> margin needed
    ev = pd.concat([pd.Series(1, index=t.entry_d), pd.Series(-1, index=t.exit)]).sort_index().cumsum()
    def part(mask):
        d = daily[mask(daily.index)]
        return d.sum(), (d.mean() / d.std() * np.sqrt(365) if d.std() else 0)
    pi, si = part(lambda x: x < CUT); po, so = part(lambda x: x >= CUT)
    years = daily.groupby(daily.index.year).sum().round(0).astype(int).to_dict()
    return {"trades": len(t), "pnl": round(daily.sum()), "maxDD": round(dd), "max_open": int(ev.max()),
            "is_pnl": round(pi), "is_sharpe": round(si, 2), "oos_pnl": round(po), "oos_sharpe": round(so, 2),
            "symbols": t.symbol.nunique(), **{str(y): v for y, v in years.items()}}


def main():
    data = pickle.loads((CACHE / "universe_daily.pkl").read_bytes())
    fund = funding_proxy(); rk = ranks(data)
    rows = {}
    eight = {f"{c}USDT": data[f"{c}USDT"] for c in EIGHT if f"{c}USDT" in data}
    rows["fixed 8"] = summary(run_set(eight, fund, lambda s, idx: None))
    for n in SIZES:
        def allowed_of(sym, idx, n=n):
            r = rk[sym].reindex(idx)
            return list((r <= n).fillna(False))
        rows[f"top {n} by volume"] = summary(run_set(data, fund, allowed_of))
    pd.set_option("display.width", 250)
    print(pd.DataFrame(rows).T.to_string())
    # who would be in the top list today
    last = rk.iloc[-1].dropna().sort_values()
    print("\ntop 20 by 30-day volume now:", " ".join(s.replace("USDT", "") for s in last.index[:20]))


if __name__ == "__main__":
    main()
