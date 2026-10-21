"""
Real funding history for every symbol in research/.cache/universe_daily.pkl (Binance USDT-M, delisted included),
summed per daily candle. Shorts receive positive funding and pay negative funding — new listings often have
strongly negative funding, which the 8-coin median would hide.

  python research/universe_funding.py    # ~10 minutes: only what short_study.py trades (Binance allows 500 funding requests / 5 min)
"""
import json, pickle, time, urllib.request
from pathlib import Path

CACHE = Path(__file__).resolve().parent / ".cache"
API = "https://fapi.binance.com/fapi/v1/fundingRate"


def get(url):
    for attempt in range(6):
        try:
            with urllib.request.urlopen(url, timeout=20) as r: return json.loads(r.read())
        except Exception:
            time.sleep(5 + attempt * 10)
    return None


def needed(data):
    """Only what research/short_study.py trades: the full history of every coin that was ever in the top 10 by
    volume (trend long/short), and the first LISTING_DAYS of every listing since 2021 (new-listing short)."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import pandas as pd
    from universe_study import ranks
    rk = ranks(data)
    want = {}
    for sym, df in data.items():
        start, last = int(df.ts.iloc[0]), int(df.ts.iloc[-1]) + 86_400_000
        if (rk[sym] <= 10).any(): want[sym] = (start, last)
        elif pd.to_datetime(start, unit="ms") >= pd.Timestamp("2021-01-01"):
            want[sym] = (start, min(last, start + LISTING_DAYS * 86_400_000))
    return want


LISTING_DAYS = 130   # skip <= 30 days + hold <= 90 days, with margin


def main():
    data = pickle.loads((CACHE / "universe_daily.pkl").read_bytes())
    out_path = CACHE / "universe_funding.pkl"
    out = pickle.loads(out_path.read_bytes()) if out_path.exists() else {}   # resumable
    want = needed(data)
    print(f"{len(want)} symbols needed, {sum(s in out for s in want)} already fetched", flush=True)
    for n, (sym, (start, end)) in enumerate(want.items()):
        if sym in out: continue
        day = {}
        while start < end:
            f = get(f"{API}?symbol={sym}&startTime={start}&endTime={end}&limit=1000")
            if not f: break
            for x in f:
                d = x["fundingTime"] // 86_400_000 * 86_400_000
                day[d] = day.get(d, 0.0) + float(x["fundingRate"])
            start = f[-1]["fundingTime"] + 1
            time.sleep(0.65)   # stay under 500 requests / 5 minutes
            if len(f) < 1000: break
        out[sym] = day
        if n % 50 == 0:
            out_path.write_bytes(pickle.dumps(out)); print(f"{n}/{len(want)} {sym}", flush=True)
    out_path.write_bytes(pickle.dumps(out)); print(f"saved funding for {len(out)} symbols", flush=True)


if __name__ == "__main__":
    main()
