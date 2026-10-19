"""
Wave Flats reference trades from strategies_wave.py for research/wave_parity.ts (browser port check),
plus a check that the live bot's signal (last closed candle) matches every backtest entry.

  python research/wave_parity_export.py && node research/wave_parity.ts
"""
import sys, json, pickle
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import strategies_wave as wf

CACHE = Path(__file__).resolve().parent / ".cache"
bad = n = 0
for f in sorted(CACHE.glob("data_*USDT_*.pkl")):
    tf = f.stem.rsplit("_", 1)[1]
    df = pickle.loads(f.read_bytes())
    candles = [{"ts": int(t.value // 10**6), "open": o, "high": h, "low": l, "close": c, "vol": v}
               for t, o, h, l, c, v in zip(df.ts, df.open, df.high, df.low, df.close, df.vol)]
    cols = [[x[k] for x in candles] for k in ("open", "high", "low", "close", "ts")]
    trades = wf.run_wave_flats(*cols, tf)
    (CACHE / f"wave_{f.stem[5:]}.json").write_text(json.dumps({"tf": tf, "candles": candles, "trades": trades}), encoding="utf-8")
    # live signal: the bot sees candles up to the signal candle and enters at market on the next one
    ts = cols[4]
    for t in trades:
        k = ts.index(t["entry_ts"]) - 1
        sig = {}
        wf.run_wave_flats(*[col[:k + 1] for col in cols], tf, last_signal=sig)
        n += 1
        if sig.get("ts") != ts[k] or sig.get("dir") != (1 if t["side"] == "long" else -1) or sig.get("kind") != t["kind"]:
            bad += 1; print("live signal differs", f.stem, t, sig)
print(f"wrote wave_*.json; live signal matches {n - bad}/{n} backtest entries")
sys.exit(1 if bad else 0)
