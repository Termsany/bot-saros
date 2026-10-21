"""
Daily trend reference trades from strategies_trend.py for research/trend_parity.ts (browser port check),
at leverage 1, 2 and 5, with and without funding.

  python research/trend_data.py && python research/trend_parity_export.py && node research/trend_parity.ts
"""
import sys, json, pickle
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import strategies_trend as st

CACHE = Path(__file__).resolve().parent / ".cache"
for f in sorted(CACHE.glob("trend_*.pkl")):
    if f.stem == "trend_results": continue
    df = pickle.loads(f.read_bytes())
    candles = [{"ts": int(t.value // 10**6), "open": o, "high": h, "low": l, "close": c, "vol": v}
               for t, o, h, l, c, v in zip(df.ts, df.open, df.high, df.low, df.close, df.vol)]
    cols = [[x[k] for x in candles] for k in ("open", "high", "low", "close", "ts")]
    funding = [float(x) for x in df.funding]
    runs = {f"{lev}{'f' if fu else ''}": st.run_trend_daily(*cols, funding if fu else None, 20, lev)
            for lev in (1, 2, 5) for fu in (False, True)}
    (CACHE / f"trendparity_{f.stem[6:]}.json").write_text(json.dumps({"candles": candles, "funding": funding, "runs": runs}), encoding="utf-8")
print("wrote trendparity_*.json")
