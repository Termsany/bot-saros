"""Dying-coin short, redefined: the volume rank (research/short_ideas_study.py idea 2) could not reach 150-250 before
2023 (Binance listed fewer perpetuals), so it never traded in-sample. Here 'dying' is the coin's own volume collapse:
30-day average volume at most D of its highest 30-day average over the last 180 days, after having been in the top
R0 by volume, while below its N-day average -> short the next open for H days. Same costs, stop and cap as before."""
import sys, pickle, itertools
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent.parent)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import traders_study as ts, short_study as ss, pump_momentum_study as pm, short_ideas_study as si


def dying2(A, R0, D, N, H):
    out = []
    for s, a in A.items():
        c, v = a["c"], a["v"]; n = len(c)
        if n < 200: continue
        v30 = pd.Series(v).rolling(30).mean().values; peak = pd.Series(v30).rolling(180, min_periods=60).max().values
        best = pd.Series(a["rk"]).rolling(180, min_periods=30).min().values; m = ts.sma(c, N)
        i = max(N, 60)
        while i < n - 2:
            if best[i + 1] <= R0 and np.isfinite(peak[i]) and v30[i] <= D * peak[i] and c[i] < m[i]:
                t, j = si.hold_short(a, i + 1, H, s); out.append(t); i = j
            else: i += 1
    return pm.cap(out, 10)


if __name__ == "__main__":
    data = pickle.loads((ts.CACHE / "universe_daily.pkl").read_bytes())
    fr = pickle.loads((ts.CACHE / "universe_funding.pkl").read_bytes())
    A = ts.coin_arrays(data, {s: fr.get(s, {}) for s in data}, pm.rank_table(data, 60))
    si.run("dying coin v2 (R0, volume left, ma, days)", dying2, list(itertools.product((50, 100), (0.1, 0.2, 0.3), (100, 200), (30, 60))), A)
