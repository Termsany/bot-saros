"""
Does an intraday stop help the Williams volatility breakout (research/traders_study.py: top 10 by volume, k 0.7,
yesterday's close above its 20-day average, sell at the next daily open)? Daily candles can't say whether the low
came before or after the fill, so each trade is replayed on hourly candles (research/hourly_data.py — every coin
that was ever in the top 10): the fill is the first hour whose high reaches the trigger, the stop counts only in the
hours after it. Inside the fill hour the order is still unknown, so it is shown both ways:
  best  = the fill hour's low came before the fill (no stop in that hour)
  worst = the fill hour's low came after the fill (stopped if it reaches the stop)
Stops: none, 2% / 4% / 6% below the fill, back to the day's open (Williams' own idea of a failed breakout),
half of yesterday's range below the fill. Slippage 0.1% on the fill and on a stop exit, 0.04% fee per side, funding.

  python research/breakout_stop_hourly.py
"""
import sys, pickle, math
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import traders_study as ts
import short_study as ss
import pump_momentum_study as pm

H = ts.CACHE / "hourly"
TOP, K, MA, SLIP = 10, 0.7, 20, 0.001
DAY = 86_400_000
STOPS = ("none", "2%", "4%", "6%", "day open", "half range")


def stop_price(kind, fill, day_open, prev_range):
    return {"none": None, "2%": fill * 0.98, "4%": fill * 0.96, "6%": fill * 0.94,
            "day open": day_open, "half range": fill - 0.5 * prev_range}[kind]


def main():
    data = pickle.loads((ts.CACHE / "universe_daily.pkl").read_bytes())
    fund_raw = pickle.loads((ts.CACHE / "universe_funding.pkl").read_bytes())
    A = ts.coin_arrays(data, {s: fund_raw.get(s, {}) for s in data}, pm.rank_table(data, 60))

    trades = {(k, m): [] for k in STOPS for m in ("best", "worst")}
    daily_ref, missing = [], 0
    for s, a in A.items():
        o, h, l, c = a["o"], a["h"], a["l"], a["c"]; n = len(c); rng = h - l; m = ts.sma(c, MA)
        hp = H / f"{s}.pkl"
        hr = pickle.loads(hp.read_bytes()) if hp.exists() else None
        if hr is not None:
            hr = hr.sort_values("ts"); hts = hr.ts.values.astype("int64")
            ho, hh, hl = hr.open.values.astype(float), hr.high.values.astype(float), hr.low.values.astype(float)
        for i in range(21, n - 1):
            if not (a["rk"][i] <= TOP) or rng[i - 1] <= 0 or not (c[i - 1] > m[i - 1]): continue
            trig = o[i] + K * rng[i - 1]
            if h[i] < trig: continue
            daily_ref.append(ts.long_trade(a, i, max(o[i], trig) * (1 + SLIP), i + 1, o[i + 1], "next open", s))
            if hr is None: missing += 1; continue
            a0, a1 = np.searchsorted(hts, [a["ts"][i], a["ts"][i] + DAY])
            if a1 - a0 < 20: missing += 1; continue                 # the day isn't in the hourly data
            hit = next((j for j in range(a0, a1) if hh[j] >= trig), None)
            if hit is None: missing += 1; continue                  # hourly and daily highs disagree (source differences)
            fill = max(ho[hit], trig) * (1 + SLIP)
            for kind in STOPS:
                sp = stop_price(kind, fill, o[i], rng[i - 1])
                for mode in ("best", "worst"):
                    out = None
                    if sp is not None and sp < fill:
                        first = hit if mode == "worst" else hit + 1
                        for j in range(first, a1):
                            if hl[j] <= sp:
                                out = (min(ho[j], sp) if j > hit else sp) * (1 - SLIP); break
                    tr = ts.long_trade(a, i, fill, i + 1, out if out is not None else o[i + 1], "stop" if out else "next open", s)
                    trades[(kind, mode)].append(tr)

    ref = ss.summary(daily_ref, "daily candles (reference)")
    print(f"{len(daily_ref)} breakout trades on daily candles; {missing} without matching hourly data (left out below)\n")
    print(f"{'':<34}{'trades':>7}{'win%':>6}{'pnl':>8}{'maxDD':>7}{'IS':>7}{'OOS':>7}{'oosPnL':>8}{'stopped':>9}")
    print(f"{ref['variant']:<34}{ref['trades']:>7}{ref['win%']:>6}{ref['pnl']:>8}{ref['maxDD']:>7}{ref['is_sharpe']:>7}{ref['oos_sharpe']:>7}{ref['oos_pnl']:>8}")
    for kind in STOPS:
        for mode in (("best",) if kind == "none" else ("best", "worst")):
            tr = trades[(kind, mode)]; r = ss.summary(tr, "")
            label = "hourly, no stop" if kind == "none" else f"stop {kind} ({mode})"
            st = sum(t["reason"] == "stop" for t in tr) / max(1, len(tr)) * 100
            print(f"{label:<34}{r['trades']:>7}{r['win%']:>6}{r['pnl']:>8}{r['maxDD']:>7}{r['is_sharpe']:>7}{r['oos_sharpe']:>7}{r['oos_pnl']:>8}{st:>8.0f}%")
            if kind != "none" and mode == "worst":
                print(f"{'':<34}by year: " + "  ".join(f"{y}: {r.get(str(y), 0):+d}" for y in range(2020, 2027)))


if __name__ == "__main__":
    main()
