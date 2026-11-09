"""
Daily open interest and positioning for research/oi_study.py (owner, 2026-11-07: "open-interest signals").

Binance publishes 5-minute "metrics" per USDT-M perpetual, one file a day (data.binance.vision, from 2020-09):
open interest (coins and USDT), top traders' long/short ratio (accounts and positions), all accounts' long/short
ratio and the taker buy/sell volume ratio. This keeps one row per coin per UTC day, from 2021, for the 215 coins
ever in the top 20 by 30-day volume since then (delisted included; RAQM_OI_TOP changes the 20). Kept on the server:

  RAQM_RESEARCH_CACHE=/opt/raqm-data/research python research/oi_data.py      # resumable: only missing days

Saves <cache>/oi/<SYMBOL>.pkl: ts (UTC day, ms), oi (coins, last), oi_usd (last), top_pos (top traders' position
long/short ratio, last), top_acc (their account ratio, last), ls_acc (all accounts' ratio, mean), taker (mean).
"""
import io, os, pickle, re, sys, time, urllib.request, zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m5_data import ranks, CACHE, START

OUT = CACHE / "oi"
BASE = "https://data.binance.vision/"
LIST = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?prefix=data/futures/um/daily/metrics/{s}/&marker={m}"


def get(url, tries=5):
    for a in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r: return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
        except Exception:
            pass
        time.sleep(2 + a * 4)
    return None


def listing(sym):
    keys, marker = [], ""
    while True:
        x = get(LIST.format(s=sym, m=marker))
        if x is None: break
        x = x.decode()
        ks = re.findall(r"<Key>([^<]+\.zip)</Key>", x); keys += ks
        if "<IsTruncated>true" not in x: break
        marker = re.findall(r"<Key>([^<]+)</Key>", x)[-1]
    return keys


def mean(xs):
    v = [x for x in xs if x == x]
    return sum(v) / len(v) if v else float("nan")


def day_row(key):
    raw = get(BASE + key)
    if not raw: return None
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z: txt = z.read(z.namelist()[0]).decode()
    except Exception:
        return None
    rows = [l.split(",") for l in txt.splitlines() if l and l[0].isdigit()]
    if not rows: return None
    def f(r, i):
        try: return float(r[i].strip('"'))
        except (IndexError, ValueError): return float("nan")
    last = rows[-1]
    return {"ts": int(pd.Timestamp(rows[0][0][:10]).value // 1_000_000), "oi": f(last, 2), "oi_usd": f(last, 3),
            "top_acc": f(last, 4), "top_pos": f(last, 5),
            "ls_acc": mean(f(r, 6) for r in rows), "taker": mean(f(r, 7) for r in rows)}


def update(sym, pool):
    p = OUT / f"{sym}.pkl"
    old = pickle.loads(p.read_bytes()) if p.exists() else pd.DataFrame(columns=["ts"])
    have = set(pd.to_datetime(old.ts, unit="ms").dt.strftime("%Y-%m-%d")) if len(old) else set()
    keys = [k for k in listing(sym) if (d := k[-14:-4]) >= START.strftime("%Y-%m-%d") and d not in have]
    rows = [r for r in pool.map(day_row, keys) if r]
    if not rows: return sym, 0
    df = pd.concat([old, pd.DataFrame(rows)]).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    tmp = p.with_suffix(".tmp"); tmp.write_bytes(pickle.dumps(df)); tmp.replace(p)
    return sym, len(rows)


def main():
    OUT.mkdir(exist_ok=True)
    data = pickle.loads((CACHE / "universe_daily.pkl").read_bytes())
    rk = ranks(data)
    top = int(os.getenv("RAQM_OI_TOP") or 20)
    syms = [s for s in data if (rk[s][rk.index >= START - pd.Timedelta(days=31)] <= top).any()]
    print(f"{len(syms)} symbols", flush=True)
    with ThreadPoolExecutor(int(os.getenv("RAQM_OI_THREADS") or 32)) as pool:
        for n, s in enumerate(syms):
            print(f"  {n + 1}/{len(syms)} {s}: +{update(s, pool)[1]} days", flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()
