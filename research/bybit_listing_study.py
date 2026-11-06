"""
The new-listing short on a second exchange: Bybit (research/bybit_data.py — every crypto USDT perpetual Bybit has
listed, delisted included, real funding). Nothing is tuned here: the exact rule that runs on Binance
(research/short_study.py idea 2, research/listing_improve_study.py's baseline):

  short the open 30 days after the first daily candle, hold 90 days, stop 40% above entry, at most 10 open,
  $20 x2, 0.04% fee per side, real funding (shorts receive positive, pay negative); listings since 2021.

Two questions:
  1. Does the rule work on another exchange's listings? (an out-of-exchange check of the Binance result)
  2. Do the coins Bybit lists that Binance's USDT-M never did add to it, or only add risk?
Each group is shown with every listing and with only the tradable ones (average daily turnover over the 30 days
before entry at least $1M — a short on a coin trading less is hard to fill at the test's prices). Before 2024 / 2024
on as in the other studies.

  python research/bybit_data.py && python research/bybit_listing_study.py
"""
import sys, pickle
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import short_study as ss
from pump_momentum_study import cap
from listing_improve_study import run, K, MAX_OPEN

CACHE = ss.CACHE
TRADABLE = 1_000_000            # $ average daily turnover over the 30 days before entry
PREFIXES = ("1000000", "10000", "1000")


def strip(b):
    return next((b[len(p):] for p in PREFIXES if b.startswith(p)), b)


def main():
    daily = pickle.loads((CACHE / "bybit_daily.pkl").read_bytes())
    fund_raw = pickle.loads((CACHE / "bybit_funding.pkl").read_bytes())
    meta = pickle.loads((CACHE / "bybit_meta.pkl").read_bytes())
    binance = {strip(s[:-4]) for s in pickle.loads((CACHE / "universe_daily.pkl").read_bytes())}

    groups = {"all": [], "on Binance too": [], "Bybit only": []}
    tradable = {"all": [], "on Binance too": [], "Bybit only": []}
    counts = {"listings since 2021": 0, "of them delisted": 0}
    for s, df in daily.items():
        if df is None or len(df) <= K + 1: continue
        first = pd.to_datetime(df.ts.iloc[0], unit="ms")
        if first < pd.Timestamp("2021-01-01"): continue
        counts["listings since 2021"] += 1; counts["of them delisted"] += meta.get(s, {}).get("status") == "Closed"
        fund = [fund_raw.get(s, {}).get(int(t), 0.0) for t in df.ts]
        tr = run(df.reset_index(drop=True), fund)
        if not tr: continue
        g = "on Binance too" if strip(meta.get(s, {}).get("base") or s[:-4]) in binance else "Bybit only"
        liquid = float(df.turnover.iloc[:K].mean()) >= TRADABLE
        for key in ("all", g):
            groups[key] += tr
            if liquid: tradable[key] += tr
    print(counts)

    rows = []
    for name, tr in groups.items():
        rows.append(ss.summary(cap(tr, MAX_OPEN), f"Bybit · {name} · every listing"))
        rows.append(ss.summary(cap(tradable[name], MAX_OPEN), f"Bybit · {name} · turnover >= $1M"))
    out = pd.DataFrame([{k: v for k, v in r.items() if k != "_daily"} for r in rows]).set_index("variant")
    pd.set_option("display.width", 260); pd.set_option("display.max_columns", 30)
    cols = [c for c in ["trades", "win%", "pnl", "maxDD", "is_sharpe", "oos_sharpe", "oos_pnl", "max_open", "2021", "2022", "2023", "2024", "2025", "2026"] if c in out]
    print(out[cols].to_string())
    print("\nBinance, the same rule (research/README.md section 19): 251 trades | pnl +775 | maxDD 358 | Sharpe before 2024 0.64 | 2024 on 1.30")


if __name__ == "__main__":
    main()
