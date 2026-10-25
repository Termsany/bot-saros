"""
Daily collector of Binance USDT-M futures positioning data, for research that needs a history Binance doesn't keep
(its /futures/data endpoints only go back 30 days): open interest (+ the circulating supply it reports), the
long/short account ratio of all traders, the top traders' long/short position ratio, and taker buy/sell volume —
hourly, for every USDT perpetual that is trading (coins delisted later stay in the file: no survivorship bias).

Each run fills from the last stored hour up to now (the first run backfills the 30 days Binance still has), so a
missed day is caught up as long as the gap stays under ~29 days. Public endpoints, no keys.

  python collect_market_data.py [--db data/market_data.sqlite] [--symbols BTCUSDT,ETHUSDT]
"""
import argparse, json, sqlite3, sys, time, urllib.error, urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://fapi.binance.com"
HOUR = 3_600_000
LOOKBACK = 29 * 24 * HOUR          # Binance answers up to 30 days back
PAUSE = 0.35                       # ~170 requests/min, well under the 1000 per 5 minutes these endpoints allow

# table -> (endpoint, {column: field})
METRICS = {
    "oi":         ("/futures/data/openInterestHist",           {"oi": "sumOpenInterest", "oi_value": "sumOpenInterestValue", "cmc_supply": "CMCCirculatingSupply"}),
    "ls_global":  ("/futures/data/globalLongShortAccountRatio", {"ratio": "longShortRatio", "long_acc": "longAccount", "short_acc": "shortAccount"}),
    "ls_top_pos": ("/futures/data/topLongShortPositionRatio",   {"ratio": "longShortRatio", "long_acc": "longAccount", "short_acc": "shortAccount"}),
    "taker":      ("/futures/data/takerlongshortRatio",         {"ratio": "buySellRatio", "buy_vol": "buyVol", "sell_vol": "sellVol"}),
}


def get(path, params, tries=6):
    url = API + path + "?" + "&".join(f"{k}={v}" for k, v in params.items())
    for n in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=25) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (418, 429):                       # rate limited / banned for a while: back off hard
                time.sleep(int(e.headers.get("Retry-After") or 60) + 5); continue
            if e.code == 400: return []                    # symbol without this data (e.g. too new)
            time.sleep(3 * (n + 1))
        except Exception:
            time.sleep(3 * (n + 1))
    raise RuntimeError(f"no answer from {path} {params.get('symbol')}")


def open_db(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    for table, (_, cols) in METRICS.items():
        db.execute(f"CREATE TABLE IF NOT EXISTS {table} (symbol TEXT NOT NULL, ts INTEGER NOT NULL, "
                   + ", ".join(f"{c} REAL" for c in cols) + ", PRIMARY KEY (symbol, ts)) WITHOUT ROWID")
    db.execute("CREATE TABLE IF NOT EXISTS runs (started TEXT, symbols INTEGER, rows INTEGER, errors INTEGER, seconds REAL)")
    db.commit()
    return db


def symbols_trading():
    info = get("/fapi/v1/exchangeInfo", {})
    return sorted(s["symbol"] for s in info["symbols"]
                  if s.get("contractType") == "PERPETUAL" and s.get("quoteAsset") == "USDT" and s.get("status") == "TRADING")


def collect(db, symbols, fetch=get, now_ms=None, pause=PAUSE):
    now_ms = now_ms or int(time.time() * 1000)
    done_upto = now_ms // HOUR * HOUR - HOUR          # newest finished hour: Binance also returns the current one, still changing
    added = errors = 0
    for i, sym in enumerate(symbols):
        for table, (path, cols) in METRICS.items():
            last = db.execute(f"SELECT MAX(ts) FROM {table} WHERE symbol=?", (sym,)).fetchone()[0]
            start = max((last + HOUR) if last else 0, now_ms - LOOKBACK)
            try:
                while start <= done_upto:
                    # with startTime alone Binance returns the latest 500 hours, not the 500 after it: bound the page
                    rows = fetch(path, {"symbol": sym, "period": "1h", "limit": 500, "startTime": start, "endTime": min(done_upto, start + 499 * HOUR)})
                    if pause: time.sleep(pause)
                    if not rows:
                        start += 500 * HOUR; continue              # nothing in this window (coin listed later): next one
                    vals = [(sym, int(r["timestamp"]), *[float(r[f]) if r.get(f) not in (None, "") else None for f in cols.values()])
                            for r in rows if int(r["timestamp"]) <= done_upto]
                    if not vals: break
                    db.executemany(f"INSERT OR IGNORE INTO {table} (symbol, ts, {', '.join(cols)}) VALUES ({', '.join('?' * (2 + len(cols)))})", vals)
                    added += len(vals)
                    newest = max(v[1] for v in vals)
                    if newest + HOUR <= start: break
                    start = newest + HOUR                          # the next page starts right after the last hour received
            except Exception as e:
                errors += 1; print(f"{sym} {table}: {e}", flush=True)
        if i % 25 == 24:
            db.commit(); print(f"  {i + 1}/{len(symbols)} coins, {added} rows", flush=True)
    db.commit()
    return added, errors


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=str(Path(__file__).parent / "data" / "market_data.sqlite"))
    p.add_argument("--symbols", default="", help="comma-separated, default: every trading USDT perpetual")
    a = p.parse_args()
    t0 = time.time(); started = datetime.now(timezone.utc).isoformat()
    db = open_db(a.db)
    syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()] or symbols_trading()
    print(f"{started} collecting {len(syms)} coins -> {a.db}", flush=True)
    added, errors = collect(db, syms)
    db.execute("INSERT INTO runs VALUES (?, ?, ?, ?, ?)", (started, len(syms), added, errors, round(time.time() - t0, 1))); db.commit()
    print(f"done: {added} new rows, {errors} errors, {time.time() - t0:.0f}s", flush=True)
    sys.exit(1 if errors > len(syms) else 0)   # a few failures are retried next run; most of them failing is an outage


if __name__ == "__main__":
    main()
