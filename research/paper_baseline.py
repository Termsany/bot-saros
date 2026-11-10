"""
The backtest baseline of the paper candidates (owner, 2026-11-08), in the Demo baseline's units (baseline_stats.stats:
trades per month, win rate, average win / loss as % of a trade's margin, profit factor, worst drawdown in margins), so
scripts/demo_weekly.py can say whether each paper bot runs like its backtest:

  rsi2_btc     RSI-2 with BTC above its 200-day average (§28: core_improve_study.run_rsi2, top 10, RSI-2 < 5, out above
               the 5-day average) — the paper bot raqm-rsi2-btc
  retail_fade  X3 L3, against the crowd's long/short ratio (§29: oi_study.baskets, top 20, 3 + 3 weekly) — the paper
               bot raqm-retail-fade

  python research/paper_baseline.py        -> lib/paper-baseline.json (a strategy whose data isn't here is kept as it was)

The OI files are on the server only (/opt/raqm-data/research/oi): run it there with RAQM_RESEARCH_CACHE set, or
here for rsi2_btc alone.
"""
import json, os, pickle, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import baseline_stats as bls

CACHE = Path(os.getenv("RAQM_RESEARCH_CACHE") or Path(__file__).resolve().parent / ".cache")
OUT = Path(os.getenv("RAQM_PAPER_BASELINE") or ROOT / "lib" / "paper-baseline.json")


def rsi2_btc(data, fund):
    import core_improve_study as ci, pump_momentum_study as pm, traders_study as ts
    btc = {200: ci.btc_above(data, 200)}
    return ci.run_rsi2(ts.coin_arrays(data, fund, pm.rank_table(data, 60)), btc, 5, "sma5", 1, 10)


def retail_fade(data, fund):
    import oi_study as oi_s
    from universe_study import ranks
    oi = {p.stem: pickle.loads(p.read_bytes()) for p in (CACHE / "oi").glob("*.pkl")}
    if not oi:
        return None
    member = (ranks(data) <= oi_s.TOP).shift(1, fill_value=False)
    P = {c: oi_s.panel(oi, c) for c in ("oi", "ls_acc", "top_pos", "taker")}
    import pandas as pd
    P["close"] = pd.DataFrame({s: d.set_index(pd.to_datetime(d.ts, unit="ms")).close for s, d in data.items() if s in oi}).sort_index()
    P = {k: v.reindex(P["close"].index) for k, v in P.items()}
    return oi_s.baskets(data, fund, member, oi_s.scores("X3", 3, P))


def main():
    data = pickle.loads((CACHE / "universe_daily.pkl").read_bytes())
    fund_raw = pickle.loads((CACHE / "universe_funding.pkl").read_bytes())
    fund = {s: fund_raw.get(s, {}) for s in data}
    try:
        doc = json.loads(OUT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = {"strategies": {}}
    for name, fn in (("rsi2_btc", rsi2_btc), ("retail_fade", retail_fade)):
        trades = fn(data, fund)
        if not trades:
            print(f"{name}: no data here, kept as it was"); continue
        doc["strategies"][name] = bls.stats(trades)
        print(name, json.dumps(doc["strategies"][name], ensure_ascii=False))
    doc["meta"] = {"generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"), "margin_usdt": bls.MARGIN,
                   "note": "research/paper_baseline.py; same units as lib/demo-baseline.json"}
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
