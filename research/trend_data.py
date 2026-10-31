"""
Daily candles + funding rates for the trend study (research/trend_study.py), from Binance USDT-M futures.
Cached in research/.cache/trend_<COIN>.pkl. Run once: python research/trend_data.py
"""
import os
import json, pickle, time, urllib.request
from pathlib import Path
import pandas as pd

CACHE = Path(os.getenv("RAQM_RESEARCH_CACHE") or Path(__file__).resolve().parent / ".cache")   # shared store: research/README.md
COINS = ["BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "LINK"]
API = "https://fapi.binance.com/fapi/v1"


def get(url):
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=20) as r: return json.loads(r.read())
        except Exception:
            time.sleep(2 + attempt * 3)
    raise RuntimeError(url)


def fetch(coin):
    sym = f"{coin}USDT"; rows = []; start = 0
    while True:
        k = get(f"{API}/klines?symbol={sym}&interval=1d&startTime={start}&limit=1500")
        if not k: break
        rows += k; start = k[-1][0] + 1
        if len(k) < 1500: break
    df = pd.DataFrame([[r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])] for r in rows],
                      columns=["ts", "open", "high", "low", "close", "vol"]).drop_duplicates("ts")
    df = df[df.ts < int(time.time() * 1000) - 86_400_000]          # closed candles only
    fr = []; start = int(df.ts.iloc[0])
    while True:
        f = get(f"{API}/fundingRate?symbol={sym}&startTime={start}&limit=1000")
        if not f: break
        fr += f; start = f[-1]["fundingTime"] + 1
        if len(f) < 1000: break
    funding = pd.DataFrame({"ts": [x["fundingTime"] for x in fr], "rate": [float(x["fundingRate"]) for x in fr]})
    # funding paid during each daily candle (sum of the 8h payments inside it)
    funding["day"] = funding.ts // 86_400_000 * 86_400_000
    daily = funding.groupby("day").rate.sum()
    df["funding"] = df.ts.map(daily).fillna(0.0)
    df["ts"] = pd.to_datetime(df.ts, unit="ms")
    return df.reset_index(drop=True)


if __name__ == "__main__":
    CACHE.mkdir(exist_ok=True)
    for coin in COINS:
        df = fetch(coin)
        (CACHE / f"trend_{coin}.pkl").write_bytes(pickle.dumps(df))
        print(f"{coin}: {len(df)} days {df.ts.iloc[0].date()} -> {df.ts.iloc[-1].date()}, funding avg {df.funding.mean() * 365 * 100:.1f}%/yr", flush=True)
