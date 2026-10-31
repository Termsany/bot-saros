"""
Real funding for every coin in universe_daily.pkl on every day it traded: the store the studies read
(universe_funding.pkl, {symbol: {day_ms: summed rate}}), so no backtest has to download funding windows first.
Incremental: each coin is fetched from the day after its last stored day. Bybit first (fast, its own limits), Binance
for what Bybit doesn't have, $RAQM_FUNDING_PAUSE seconds between Binance requests (pump_momentum_study.fetch_windows).

  python research/universe_data.py && python research/funding_store.py
"""
import pickle, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pump_momentum_study as pm

CHUNK = 365 * pm.DAY        # one Bybit window holds ~4,000 rates: a year of 8-hour funding, so long histories go by year


def main():
    data = pickle.loads((pm.CACHE / "universe_daily.pkl").read_bytes())
    path = pm.CACHE / "universe_funding.pkl"
    fund = pickle.loads(path.read_bytes()) if path.exists() else {}
    todo = {}
    for s, df in data.items():
        if not len(df): continue
        have = fund.get(s) or {}
        start, last = (max(have) + pm.DAY if have else int(df.ts.iloc[0])), int(df.ts.iloc[-1])
        if start <= last: todo[s] = (start, last)
    print(f"funding store: {len(todo)} coins to update", flush=True)
    # one pass per year-long slice: fetch_windows merges touching windows, so slices must go in separate calls
    for k in range(max((((b - a) // CHUNK) + 1 for a, b in todo.values()), default=0)):
        windows = {s: [(a + k * CHUNK, min(b, a + (k + 1) * CHUNK - pm.DAY))] for s, (a, b) in todo.items() if a + k * CHUNK <= b}
        pm.fetch_windows(windows, fund)
    path.write_bytes(pickle.dumps(fund))
    print(f"funding store: {len(fund)} coins", flush=True)


if __name__ == "__main__":
    main()
