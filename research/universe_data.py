"""
Daily candles (with USDT volume) for every Binance USDT-M perpetual, including delisted ones ("SETTLING"),
so a volume-ranked universe can be tested without survivorship bias. Funding is not fetched per coin
(rate limits); research/universe_study.py uses the daily median funding of the 8 coins in trend_*.pkl.

  python research/universe_data.py     # ~10 minutes -> research/.cache/universe_daily.pkl
"""
import json, pickle, time, urllib.request
from pathlib import Path
import pandas as pd

CACHE = Path(__file__).resolve().parent / ".cache"
API = "https://fapi.binance.com/fapi/v1"
SKIP = {"USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "USDPUSDT", "BUSDUSDT", "DAIUSDT", "PAXGUSDT", "XAUTUSDT"}  # stablecoins, gold


def get(url):
    for attempt in range(6):
        try:
            with urllib.request.urlopen(url, timeout=20) as r: return json.loads(r.read())
        except Exception:
            time.sleep(3 + attempt * 5)
    return None


def main():
    info = get(f"{API}/exchangeInfo")
    syms = [s["symbol"] for s in info["symbols"] if s["contractType"] == "PERPETUAL" and s["quoteAsset"] == "USDT"
            and s["status"] in ("TRADING", "SETTLING") and s["symbol"] not in SKIP]
    out = {}
    for n, sym in enumerate(syms):
        rows = []; start = 0
        while True:
            k = get(f"{API}/klines?symbol={sym}&interval=1d&startTime={start}&limit=1500")
            if not k: break
            rows += k; start = k[-1][0] + 1
            if len(k) < 1500: break
            time.sleep(0.3)
        if len(rows) >= 60:
            df = pd.DataFrame([[r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[7])] for r in rows],
                              columns=["ts", "open", "high", "low", "close", "qvol"]).drop_duplicates("ts")
            df = df[df.ts < int(time.time() * 1000) - 86_400_000].reset_index(drop=True)
            out[sym] = df
        if n % 50 == 0: print(f"{n}/{len(syms)} {sym}", flush=True)
        time.sleep(0.25)
    (CACHE / "universe_daily.pkl").write_bytes(pickle.dumps(out))
    print(f"saved {len(out)} symbols")


if __name__ == "__main__":
    main()
