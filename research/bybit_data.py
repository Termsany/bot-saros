"""
Bybit's USDT perpetuals, for checking a strategy on a second exchange: daily candles and real funding (summed per
UTC day) for every crypto USDT perpetual Bybit lists now *and* every one it has closed (delisted included — a short
study without the dead coins would be biased). Stocks, ETFs, commodities and forex contracts are left out.

Public endpoints, no keys. Resumable: what is already in the cache is kept and only the missing symbols are fetched.

  python research/bybit_data.py            # -> $RAQM_RESEARCH_CACHE (or research/.cache)/bybit_daily.pkl, bybit_funding.pkl

bybit_daily.pkl:   {symbol: DataFrame(ts ms, open, high, low, close, volume, turnover)}  closed days only
bybit_funding.pkl: {symbol: {day ts ms: sum of that day's funding rates}}
bybit_meta.pkl:    {symbol: {"base", "status", "launch" ms, "type"}}
"""
import json, os, pickle, sys, time, urllib.request, urllib.error
from pathlib import Path
import pandas as pd

CACHE = Path(os.getenv("RAQM_RESEARCH_CACHE") or Path(__file__).resolve().parent / ".cache")
API = "https://api.bybit.com"
DAY = 86_400_000
NOT_CRYPTO = {"stock", "ETF", "commodity", "forex"}
PAUSE = float(os.getenv("RAQM_BYBIT_PAUSE", "0.12"))   # seconds between requests: 0.12 ≈ 8/s; Bybit allows ~120/s per IP


def get(path, tries=5):
    for k in range(tries):
        try:
            req = urllib.request.Request(API + path, headers={"User-Agent": "Mozilla/5.0 (research script)"})
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.loads(r.read())
            if d.get("retCode") == 0:
                time.sleep(PAUSE); return d["result"]
            if d.get("retCode") in (10006, 10018):          # rate limited
                time.sleep(2 + 2 * k); continue
            raise RuntimeError(f"{path}: {d.get('retCode')} {d.get('retMsg')}")
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(2 + 2 * k)
    raise RuntimeError(f"{path}: gave up after {tries} tries")


def instruments():
    out = {}
    for status in ("Trading", "Closed"):
        cursor = ""
        while True:
            r = get(f"/v5/market/instruments-info?category=linear&status={status}&limit=1000" + (f"&cursor={cursor}" if cursor else ""))
            for i in r["list"]:
                if i.get("quoteCoin") != "USDT" or i.get("contractType") != "LinearPerpetual": continue
                if (i.get("symbolType") or "") in NOT_CRYPTO: continue
                out[i["symbol"]] = {"base": i["baseCoin"], "status": status, "launch": int(i.get("launchTime") or 0), "type": i.get("symbolType") or ""}
            cursor = r.get("nextPageCursor") or ""
            if not cursor: break
    return out


def candles(sym):
    rows, end = [], None
    while True:
        r = get(f"/v5/market/kline?category=linear&symbol={sym}&interval=D&limit=1000" + (f"&end={end}" if end else ""))["list"]
        if not r: break
        rows += r; oldest = int(r[-1][0]); end = oldest - 1
        if len(r) < 1000: break
    if not rows: return None
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume", "turnover"]).astype(float)
    df["ts"] = df.ts.astype("int64")
    df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    today = int(time.time() * 1000) // DAY * DAY
    return df[df.ts < today].reset_index(drop=True)          # closed days only


def funding(sym, since):
    out, end = {}, None
    while True:
        r = get(f"/v5/market/funding/history?category=linear&symbol={sym}&limit=200" + (f"&endTime={end}" if end else ""))["list"]
        if not r: break
        for x in r:
            t = int(x["fundingRateTimestamp"]); d = t // DAY * DAY
            out[d] = out.get(d, 0.0) + float(x["fundingRate"])
        oldest = int(r[-1]["fundingRateTimestamp"])
        if len(r) < 200 or oldest <= since: break
        end = oldest - 1
    return out


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    fd, ff, fm = CACHE / "bybit_daily.pkl", CACHE / "bybit_funding.pkl", CACHE / "bybit_meta.pkl"
    daily = pickle.loads(fd.read_bytes()) if fd.exists() else {}
    fund = pickle.loads(ff.read_bytes()) if ff.exists() else {}
    meta = instruments()
    todo = [s for s in meta if s not in daily]
    print(f"Bybit crypto USDT perpetuals: {len(meta)} ({sum(m['status'] == 'Closed' for m in meta.values())} closed) | to fetch: {len(todo)}", flush=True)
    t0 = time.time()
    for n, s in enumerate(todo, 1):
        try:
            df = candles(s)
            daily[s] = df if df is not None else pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume", "turnover"])
            fund[s] = funding(s, int(df.ts.iloc[0]) if df is not None and len(df) else 0) if df is not None and len(df) else {}
        except Exception as e:
            print(f"  {s}: {e}", flush=True); continue
        if n % 50 == 0 or n == len(todo):
            fd.write_bytes(pickle.dumps(daily)); ff.write_bytes(pickle.dumps(fund)); fm.write_bytes(pickle.dumps(meta))
            print(f"  {n}/{len(todo)} saved ({(time.time() - t0) / 60:.1f} min)", flush=True)
    fm.write_bytes(pickle.dumps(meta))
    print("done:", len(daily), "symbols with candles,", sum(len(v) > 0 for v in fund.values()), "with funding")


if __name__ == "__main__":
    main()
