"""
Export cached candles + the bot's Python signals and reference trades for the browser-engine parity test.

  python research/parity_export.py            # needs research/.cache from measure_strategies.py
  node research/parity.ts                     # must report 0 differences

Reference trades use backtest.run_backtest with the CONFIG in backtest.py, for every strategy alone,
a 3-strategy mix and all 15 together.
"""
import os
import sys, json, math, pickle
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import backtest as bt

CACHE = Path(os.getenv("RAQM_RESEARCH_CACHE") or Path(__file__).resolve().parent / ".cache")   # shared store: research/README.md
NAMES = ["ichimoku", "dow", "gann", "elliott", "classical", "sr", "rsi_macd", "smc", "vwap", "supertrend",
         "bollinger", "harmonic", "ict", "heikin", "ai"]
ENGINE_SETS = ["BTCUSDT_1h", "XRPUSDT_4h"]

ref = {}
for f in sorted(CACHE.glob("scores_*.pkl")):
    tag = f.stem[len("scores_"):]
    df = pickle.loads((CACHE / f"data_{tag}.pkl").read_bytes()); sc = pickle.loads(f.read_bytes())
    candles = [{"ts": int(t.value // 10**6), "open": o, "high": h, "low": l, "close": c, "vol": v}
               for t, o, h, l, c, v in zip(df.ts, df.open, df.high, df.low, df.close, df.vol)]
    scores = [{k: (None if isinstance(x, float) and math.isnan(x) else x) for k, x in row.items()} for row in sc]
    (CACHE / f"parity_{tag}.json").write_text(json.dumps({"candles": candles, "scores": scores}), encoding="utf-8")
    if tag in ENGINE_SETS:
        W = bt.CONFIG["weights"]
        def cached(window, enabled=None):
            row = sc[window.index[-1]]; ws = sum(W[k] for k in enabled) or 1
            return sum(row[k] * W[k] for k in enabled) / ws, {}
        bt.score_at = cached
        for combo in [[n] for n in NAMES] + [["ict", "dow", "smc"], NAMES]:
            trades = bt.run_backtest(df, amount_usdt=20, leverage=5, fee_pct=0.0004, enabled=combo)["trades"]
            ref[f"{tag}|{'+'.join(combo)}"] = {"n": len(trades), "pnl": sum(t["pnl"] for t in trades)}
    print("exported", tag)
(CACHE / "engine_ref.json").write_text(json.dumps(ref), encoding="utf-8")
print("reference runs:", len(ref))
