"""
5-minute candles for research/intraday_study.py (owner, 2026-11-07: "a scientific bot on 5-15 minutes?").

Every Binance USDT-M perpetual that was ever in the top 10 by 30-day USDT volume (the same coins as
research/hourly_data.py, delisted included), from 2021-01, out of Binance's public monthly files
(data.binance.vision — far faster than the REST API). Kept on the server for good, next to the daily store:

  RAQM_RESEARCH_CACHE=/opt/raqm-data/research python research/m5_data.py     # resumable: only missing months

Saves <cache>/m5/<SYMBOL>.pkl: DataFrame ts (ms, int64), open, high, low, close, qvol (float32), sorted.
"""
import io, os, pickle, sys, time, urllib.request, zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np, pandas as pd

CACHE = Path(os.getenv("RAQM_RESEARCH_CACHE") or Path(__file__).resolve().parent / ".cache")
OUT = CACHE / "m5"
START = pd.Timestamp("2021-01-01")
BASE = "https://data.binance.vision/data/futures/um/monthly/klines"
MIN_HISTORY, VOL_WINDOW = 150, 30          # as research/universe_study.py


def ranks(data):
    vol = {}
    for sym, df in data.items():
        v = df.set_index(pd.to_datetime(df.ts, unit="ms")).qvol.rolling(VOL_WINDOW).mean()
        v.iloc[:MIN_HISTORY - 1] = np.nan
        vol[sym] = v
    return pd.DataFrame(vol).rank(axis=1, ascending=False)


def month_file(sym, month):
    """One month of 5m candles, or None (no file: the coin wasn't listed, or was delisted)."""
    url = f"{BASE}/{sym}/5m/{sym}-5m-{month}.zip"
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                raw = r.read()
            break
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
            time.sleep(3 + attempt * 5)
        except Exception:
            time.sleep(3 + attempt * 5)
    else:
        return None
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        txt = z.read(z.namelist()[0]).decode()
    lines = [l for l in txt.splitlines() if l and l[0].isdigit()]          # some files have a header row
    a = np.array([l.split(",")[:8] for l in lines])
    return pd.DataFrame({"ts": a[:, 0].astype(np.int64), "open": a[:, 1].astype(np.float32), "high": a[:, 2].astype(np.float32),
                         "low": a[:, 3].astype(np.float32), "close": a[:, 4].astype(np.float32), "qvol": a[:, 7].astype(np.float32)})


def months(first_ts, last_ts):
    a = max(START, pd.to_datetime(first_ts, unit="ms").normalize().replace(day=1))
    b = pd.Timestamp.now("UTC").tz_localize(None).normalize().replace(day=1) - pd.Timedelta(days=1)   # last full month
    b = min(b, pd.to_datetime(last_ts, unit="ms"))
    return [m.strftime("%Y-%m") for m in pd.date_range(a, b, freq="MS")]


def update(sym, first_ts, last_ts):
    p = OUT / f"{sym}.pkl"
    old = pickle.loads(p.read_bytes()) if p.exists() else None
    have = set(pd.to_datetime(old.ts, unit="ms").dt.strftime("%Y-%m")) if old is not None else set()
    want = [m for m in months(first_ts, last_ts) if m not in have]
    parts = [d for d in (month_file(sym, m) for m in want) if d is not None and len(d)]
    if not parts: return sym, 0
    df = pd.concat(([old] if old is not None else []) + parts).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    tmp = p.with_suffix(".tmp"); tmp.write_bytes(pickle.dumps(df)); tmp.replace(p)
    return sym, len(parts)


def main():
    OUT.mkdir(exist_ok=True)
    data = pickle.loads((CACHE / "universe_daily.pkl").read_bytes())
    rk = ranks(data)
    syms = [s for s in data if (rk[s][rk.index >= START - pd.Timedelta(days=31)] <= 10).any()]
    print(f"{len(syms)} symbols (in the top 10 by volume at some point since 2021)", flush=True)
    done = 0
    with ThreadPoolExecutor(6) as ex:
        for sym, n in ex.map(lambda s: update(s, int(data[s].ts.iloc[0]), int(data[s].ts.iloc[-1])), syms):
            done += 1
            print(f"  {done}/{len(syms)} {sym}: +{n} months", flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
