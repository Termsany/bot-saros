"""
Daily candles (with USDT volume) for every Binance USDT-M perpetual, including delisted ones ("SETTLING"),
so a volume-ranked universe can be tested without survivorship bias. Funding is not fetched per coin
(rate limits); research/universe_study.py uses the daily median funding of the 8 coins in trend_*.pkl.

Incremental: an existing universe_daily.pkl is kept and only the days after each coin's last candle are fetched
(the first run downloads everything, ~10 minutes; a daily update takes a few). Coins Binance stops listing stay.
Copy the store from the server once, then this adds only what's missing (research/README.md).

  python research/universe_data.py     # -> $RAQM_RESEARCH_CACHE (default research/.cache)/universe_daily.pkl
"""
import os
import json, pickle, time, urllib.error, urllib.request
from pathlib import Path
import pandas as pd

CACHE = Path(os.getenv("RAQM_RESEARCH_CACHE") or Path(__file__).resolve().parent / ".cache")   # shared store: research/README.md
API = "https://fapi.binance.com/fapi/v1"
SKIP = {"USDCUSDT", "FDUSDUSDT", "TUSDUSDT", "USDPUSDT", "BUSDUSDT", "DAIUSDT", "PAXGUSDT", "XAUTUSDT"}  # stablecoins, gold
DAY = 86_400_000
COLS = ["ts", "open", "high", "low", "close", "qvol"]


def get(url):
    """On the server this shares the trading bots' IP with Binance: a 429 backs off as told, a 418 (IP banned) stops."""
    for attempt in range(6):
        try:
            with urllib.request.urlopen(url, timeout=20) as r: return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 418:
                raise SystemExit(f"Binance banned this IP (418), retry after {e.headers.get('Retry-After')}s — run stopped")
            time.sleep(int(e.headers.get("Retry-After") or 60) + 5 if e.code == 429 else 3 + attempt * 5)
        except Exception:
            time.sleep(3 + attempt * 5)
    return None


def save(out, path):
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(pickle.dumps(out)); tmp.replace(path)


def candles(sym, start):
    """Closed daily candles from `start` (ms) on; None when Binance didn't answer."""
    rows = []
    while True:
        k = get(f"{API}/klines?symbol={sym}&interval=1d&startTime={start}&limit=1000")    # weight 5 (1500 costs 10)
        if k is None: return None
        rows += k
        if len(k) < 1000: break
        start = k[-1][0] + 1; time.sleep(0.3)
    df = pd.DataFrame([[r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[7])] for r in rows], columns=COLS)
    return df[df.ts < int(time.time() * 1000) - DAY]          # only closed candles


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / "universe_daily.pkl"
    out = pickle.loads(path.read_bytes()) if path.exists() else {}
    info = get(f"{API}/exchangeInfo")
    if not info: raise SystemExit("Binance exchangeInfo unavailable — nothing changed")
    syms = [s["symbol"] for s in info["symbols"] if s["contractType"] == "PERPETUAL" and s["quoteAsset"] == "USDT"
            and s["status"] in ("TRADING", "SETTLING") and s["symbol"] not in SKIP]
    added = 0
    for n, sym in enumerate(syms):
        have = out.get(sym)
        new = candles(sym, int(have.ts.iloc[-1]) + 1 if have is not None and len(have) else 0)
        if new is not None and len(new):
            df = new if have is None else pd.concat([have, new])
            df = df.drop_duplicates("ts", keep="last").sort_values("ts").reset_index(drop=True)
            if len(df) >= 60:
                added += len(df) - (0 if have is None else len(have)); out[sym] = df
        if n % 50 == 0: print(f"{n}/{len(syms)} {sym}", flush=True)
        if n % 100 == 99: save(out, path)
        time.sleep(0.25)
    save(out, path)
    last = max((int(df.ts.iloc[-1]) for df in out.values() if len(df)), default=0)
    print(f"saved {len(out)} symbols, {added} new candles, last day {pd.Timestamp(last, unit='ms').date()}")


if __name__ == "__main__":
    main()
