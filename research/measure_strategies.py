"""
Measure every strategy with the bot's own engine and write lib/strategy-stats.json (the numbers the site shows).

  python research/measure_strategies.py score BTC/USDT   # signals for one symbol (both timeframes); run symbols in parallel
  python research/measure_strategies.py report           # run the engine on the cached signals, write the stats file

Data: last CANDLES closed candles per symbol/timeframe from Bybit (cached in research/.cache).
Signals: backtest.score_at on the last 300 candles at each bar — what the live bot sees.
Trades: backtest.run_backtest with the CONFIG in backtest.py (same rules as bot.py and lib/strategy-engine.ts).
Wave Flats has its own entries, stops and targets: strategies_wave.run_wave_flats on the same candles.
"Out-of-sample" = the last 40% of each series; engine settings were chosen without looking at it (README.md).
"""
import sys, json, pickle, time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import numpy as np, pandas as pd
import backtest as bt
import strategies_wave as wf

CACHE = Path(__file__).resolve().parent / ".cache"
SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT"]
TIMEFRAMES = {"1h": 3600_000, "4h": 4 * 3600_000}
CANDLES = 2000
OOS_SPLIT = 0.6
STRATEGIES = ["ichimoku", "dow", "gann", "elliott", "classical", "sr", "rsi_macd", "smc", "vwap", "supertrend",
              "bollinger", "harmonic", "ict", "heikin", "ai", "wave_flats"]
AMOUNT, LEVERAGE, FEE = 20, 5, 0.0004


def key(sym, tf): return f"{sym.replace('/', '')}_{tf}"


def candles(sym, tf):
    path = CACHE / f"data_{key(sym, tf)}.pkl"
    if path.exists(): return pickle.loads(path.read_bytes())
    import ccxt
    ex = ccxt.bybit({"enableRateLimit": True}); step = TIMEFRAMES[tf]
    since = ex.milliseconds() - (CANDLES + 5) * step; rows = []
    while len(rows) < CANDLES:
        chunk = ex.fetch_ohlcv(sym, tf, since=since, limit=1000)
        if not chunk: break
        rows += chunk; since = chunk[-1][0] + step
        if len(chunk) < 2: break
    df = pd.DataFrame(rows[-CANDLES:], columns=["ts", "open", "high", "low", "close", "vol"]).drop_duplicates("ts")
    df["ts"] = pd.to_datetime(df.ts, unit="ms"); df = df.reset_index(drop=True)
    CACHE.mkdir(exist_ok=True); path.write_bytes(pickle.dumps(df)); return df


def signals(sym, tf):
    path = CACHE / f"scores_{key(sym, tf)}.pkl"
    if path.exists(): return pickle.loads(path.read_bytes())
    df = candles(sym, tf); out = []
    for i in range(len(df)):
        if i < 60: out.append({k: 0.0 for k in STRATEGIES}); continue
        _, base = bt.score_at(df.iloc[max(0, i - 299):i + 1])
        out.append({k: float(base[k]) for k in STRATEGIES if k in base})
    path.write_bytes(pickle.dumps(out)); return out


def run(df, scores, name):
    if name == "wave_flats":
        ts = [int(t.value // 10**6) for t in df.ts]
        tr = wf.run_wave_flats(list(df.open), list(df.high), list(df.low), list(df.close), ts, df.attrs["tf"], AMOUNT, LEVERAGE, FEE)
        return [{**t, "entry_ts": pd.to_datetime(t["entry_ts"], unit="ms")} for t in tr]
    bt.score_at = lambda window, enabled=None: (scores[window.index[-1]][name], {})   # one strategy: total = its score
    return bt.run_backtest(df, amount_usdt=AMOUNT, leverage=LEVERAGE, fee_pct=FEE, enabled=[name])["trades"]


def summarize(trades):
    p = [t["pnl"] for t in trades]; gw = sum(x for x in p if x > 0); gl = -sum(x for x in p if x <= 0)
    eq = np.cumsum([0.0] + p)
    return {"trades": len(p), "wins": sum(x > 0 for x in p), "gross_win": gw, "gross_loss": gl, "pnl": sum(p),
            "max_dd": float(np.max(np.maximum.accumulate(eq) - eq))}


def report():
    per = {s: [] for s in STRATEGIES}; sets = []
    for sym in SYMBOLS:
        for tf in TIMEFRAMES:
            df, sc = candles(sym, tf), signals(sym, tf)
            df.attrs["tf"] = tf
            cut = df.ts.iloc[int(len(df) * OOS_SPLIT)]
            sets.append({"symbol": sym, "timeframe": tf, "from": str(df.ts.iloc[0])[:10], "to": str(df.ts.iloc[-1])[:10]})
            for s in STRATEGIES:
                tr = run(df, sc, s)
                per[s].append({"all": summarize(tr), "oos": summarize([t for t in tr if pd.Timestamp(t["entry_ts"]) >= cut])})
    stats = {}
    for s, rows in per.items():
        a = [r["all"] for r in rows]; o = [r["oos"] for r in rows]
        t = sum(x["trades"] for x in a); gw = sum(x["gross_win"] for x in a); gl = sum(x["gross_loss"] for x in a)
        stats[s] = {
            "trades": t, "winRate": round(sum(x["wins"] for x in a) / t * 100, 1) if t else 0,
            "pf": round(gw / gl, 2) if gl else (99.0 if gw else 0), "pnl": round(gw - gl, 2),
            "setsWon": sum(x["pnl"] > 0 for x in a), "oosPnl": round(sum(x["pnl"] for x in o), 2),
            "oosSetsWon": sum(x["pnl"] > 0 for x in o), "maxDD": round(max(x["max_dd"] for x in a), 2),
        }
    meta = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "sets": len(sets),
        "symbols": SYMBOLS, "timeframes": list(TIMEFRAMES), "candlesPerSet": CANDLES,
        "from": min(x["from"] for x in sets), "to": max(x["to"] for x in sets),
        "engine": {"entryThreshold": bt.CONFIG["buy_threshold"], "cooldownBars": bt.CONFIG.get("cooldown_bars", 0),
                   "stopLossPct": bt.CONFIG["stop_loss_pct"], "takeProfitPct": bt.CONFIG["take_profit_pct"],
                   "marginUsdt": AMOUNT, "leverage": LEVERAGE, "feePct": FEE},
    }
    out = ROOT / "lib" / "strategy-stats.json"
    out.write_text(json.dumps({"meta": meta, "strategies": stats}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    for s, v in sorted(stats.items(), key=lambda kv: (kv[1]["setsWon"] + kv[1]["oosSetsWon"], kv[1]["pnl"]), reverse=True):
        print(f"  {s:<11} trades {v['trades']:>5}  WR {v['winRate']:>5}%  PF {v['pf']:>5}  pnl {v['pnl']:>8}  won {v['setsWon']}/8  oos {v['oosPnl']:>8} ({v['oosSetsWon']}/8)")


if __name__ == "__main__":
    CACHE.mkdir(exist_ok=True)
    if sys.argv[1:2] == ["score"]:
        for tf in TIMEFRAMES:
            t0 = time.time(); signals(sys.argv[2], tf); print("scored", sys.argv[2], tf, f"{time.time() - t0:.0f}s", flush=True)
    elif sys.argv[1:2] == ["report"]:
        report()
    else:
        print(__doc__)
