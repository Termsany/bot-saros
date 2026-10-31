"""
Hourly candles + exact-time funding for research/hourly_study.py, from Binance USDT-M (delisted included):
every coin that was ever in the top 10 by 30-day volume (research/universe_study.py ranks).

  python research/hourly_data.py      # resumable; candles from Bybit (fast) with Binance for the rest
Saves research/.cache/hourly/<SYMBOL>.pkl (ts, open, high, low, close, qvol) and research/.cache/funding8h/<SYMBOL>.pkl.
"""
import os
import sys, json, pickle, time, urllib.request, threading
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from universe_study import ranks

CACHE = Path(os.getenv("RAQM_RESEARCH_CACHE") or Path(__file__).resolve().parent / ".cache")   # shared store: research/README.md
H, F = CACHE / "hourly", CACHE / "funding8h"
API = "https://fapi.binance.com/fapi/v1"


def get(url):
    for attempt in range(6):
        try:
            with urllib.request.urlopen(url, timeout=25) as r: return json.loads(r.read())
        except Exception:
            time.sleep(5 + attempt * 10)
    return None


def bybit_klines(sym, start, end):
    """Bybit linear hourly candles (1000 per call, fast). Newest first — walk back from end."""
    rows, e = [], end
    while e > start:
        try:
            with urllib.request.urlopen(f"https://api.bybit.com/v5/market/kline?category=linear&symbol={sym}&interval=60&start={start}&end={e}&limit=1000", timeout=25) as r:
                lst = (json.loads(r.read()).get("result") or {}).get("list") or []
        except Exception:
            time.sleep(3); continue
        if not lst: break
        rows += [[int(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[6])] for x in lst]
        oldest = int(lst[-1][0])
        if len(lst) < 1000 or oldest <= start: break
        e = oldest - 1; time.sleep(0.05)
    return pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "qvol"])


def klines(sym, start, end):
    """Bybit first; Binance for coins Bybit doesn't list and for the period before Bybit listed them."""
    by = bybit_klines(sym, start, end)
    if len(by):
        first = int(by.ts.min())
        if first - start > 7 * 86_400_000:
            by = pd.concat([binance_klines(sym, start, first - 3_600_000), by])
        df = by.drop_duplicates("ts").sort_values("ts")
        return df[df.ts < int(time.time() * 1000) - 3_600_000].reset_index(drop=True)
    return binance_klines(sym, start, end)


def binance_klines(sym, start, end):
    rows = []
    while start < end:
        k = get(f"{API}/klines?symbol={sym}&interval=1h&startTime={start}&endTime={end}&limit=1500")
        if not k: break
        rows += k; start = k[-1][0] + 3_600_000
        time.sleep(0.3)                          # ~200 requests/min, weight 10 each: under Binance's 2400/min
        if len(k) < 1500: break
    df = pd.DataFrame([[r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[7])] for r in rows],
                      columns=["ts", "open", "high", "low", "close", "qvol"]).drop_duplicates("ts")
    return df[df.ts < int(time.time() * 1000) - 3_600_000].reset_index(drop=True)


def funding(sym, start, end):
    rows = []
    while start < end:
        f = get(f"{API}/fundingRate?symbol={sym}&startTime={start}&endTime={end}&limit=1000")
        if not f: break
        rows += [(x["fundingTime"], float(x["fundingRate"])) for x in f]; start = f[-1]["fundingTime"] + 1
        time.sleep(0.65)                         # funding endpoint: 500 requests / 5 minutes
        if len(f) < 1000: break
    return pd.DataFrame(rows, columns=["ts", "rate"]).drop_duplicates("ts")


def main():
    H.mkdir(exist_ok=True); F.mkdir(exist_ok=True)
    data = pickle.loads((CACHE / "universe_daily.pkl").read_bytes())
    rk = ranks(data)
    syms = [s for s in data if (rk[s] <= 10).any()]
    print(f"{len(syms)} symbols (ever in the top 10 by volume)", flush=True)

    def do_funding():
        for s in syms:
            p = F / f"{s}.pkl"
            if p.exists(): continue
            df = data[s]; p.write_bytes(pickle.dumps(funding(s, int(df.ts.iloc[0]), int(df.ts.iloc[-1]) + 86_400_000)))
    t = threading.Thread(target=do_funding); t.start()           # separate rate limit — run alongside the candles
    for n, s in enumerate(syms):
        p = H / f"{s}.pkl"
        if p.exists(): continue
        df = data[s]; p.write_bytes(pickle.dumps(klines(s, int(df.ts.iloc[0]), int(df.ts.iloc[-1]) + 86_400_000)))
        if n % 10 == 0: print(f"  candles {n}/{len(syms)} {s}", flush=True)
    t.join()
    print("done", flush=True)


if __name__ == "__main__":
    main()
