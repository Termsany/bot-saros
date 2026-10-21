"""
Numbers the site shows for the four paper bots (lib/bot-stats.json) — never edit that file by hand.
Same data and rules as the studies: every Binance USDT-M perpetual since 2019 (delisted included), coins chosen by
volume at the time, real funding, fees 0.04%, $20 margin x2 per position (per leg). "Out-of-sample" = from 2024.

  python research/bots_stats.py
"""
import sys, json, pickle, math
from datetime import datetime, timezone
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import short_study as ss
import pump_momentum_study as pm
import ratio_fairness as rf
import strategies_trend as st
from universe_study import ranks

ROOT = Path(__file__).resolve().parent.parent
CACHE = ss.CACHE
AMOUNT, LEV, FEE, CUT = ss.AMOUNT, ss.LEV, ss.FEE, ss.CUT


def stats(trades, daily):
    p = np.array([t["pnl"] for t in trades]); gw, gl = p[p > 0].sum(), -p[p <= 0].sum()
    eq = daily.cumsum(); sh = lambda x: round(float(x.mean() / x.std() * math.sqrt(365)), 2) if x.std() else 0.0
    monthly = eq.resample("MS").last().ffill()
    return {"trades": int(len(p)), "winRate": round(float((p > 0).mean() * 100), 1), "pf": round(float(gw / gl), 2) if gl else 99.0,
            "pnl": round(float(daily.sum()), 2), "maxDD": round(float((eq.cummax() - eq).max()), 2),
            "sharpeIn": sh(daily[daily.index < CUT]), "sharpeOut": sh(daily[daily.index >= CUT]),
            "pnlOut": round(float(daily[daily.index >= CUT].sum()), 2),
            "years": {str(y): round(float(v), 2) for y, v in daily.groupby(daily.index.year).sum().items() if y >= 2020},
            "equity": [[m.strftime("%Y-%m"), round(float(v), 2)] for m, v in monthly.items() if m.year >= 2020]}


def main():
    data = pickle.loads((CACHE / "universe_daily.pkl").read_bytes())
    fund_raw = pickle.loads((CACHE / "universe_funding.pkl").read_bytes())
    fund = {s: fund_raw.get(s, {}) for s in data}
    rk10 = ranks(data); ever10 = [s for s in data if (rk10[s] <= 10).any()]; rk100 = pm.rank_table(data, 60)

    long_tr = []
    for s in ever10:
        df = data[s]; top10 = list((rk10[s].reindex(pd.to_datetime(df.ts, unit="ms")) <= 10).fillna(False))
        long_tr += st.run_trend_daily(list(df.open), list(df.high), list(df.low), list(df.close), list(df.ts),
                                      [fund[s].get(int(t), 0.0) for t in df.ts], AMOUNT, LEV, FEE, 0, top10)
    new = [s for s, df in data.items() if pd.to_datetime(df.ts.iloc[0], unit="ms") >= pd.Timestamp("2021-01-01")]
    lst = []
    for s in new: lst += ss.run_listing_short(data[s], [fund[s].get(int(t), 0.0) for t in data[s].ts], 30, 90, 0.4)
    bots = {
        "trend_daily": long_tr,
        "momentum_ls": [t for s, d, side in pm.momentum_positions(data, rk100, 2, True) if (t := pm.momentum_trade(data[s], fund[s], d, side))],
        "listing_short": pm.cap(lst, 10),
        "ratio_trend": rf.dynamic_trades(data, fund, pm.rank_table(data, 120), 7, 50)[0],
    }
    out, dailies = {}, {}
    for k, tr in bots.items():
        d = ss.summary(tr, k)["_daily"]; dailies[k] = d; out[k] = stats(tr, d)
    core = pd.DataFrame({k: dailies[k] for k in ("trend_daily", "momentum_ls", "listing_short")}).fillna(0).sum(axis=1)
    allf = pd.DataFrame(dailies).fillna(0).sum(axis=1)
    combo = {"core": stats([{"pnl": x} for x in core.values if x], core), "all": stats([{"pnl": x} for x in allf.values if x], allf)}
    for c in combo.values():
        for k in ("trades", "winRate", "pf"): c.pop(k)
    meta = {"generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "from": str(min(d.index.min() for d in dailies.values()).date()),
            "to": str(max(d.index.max() for d in dailies.values()).date()), "marginUsdt": AMOUNT, "leverage": LEV, "feePct": FEE,
            "outOfSampleFrom": str(CUT.date()), "universe": "all Binance USDT-M perpetuals since 2019, delisted included",
            "symbolsTested": len(data)}
    path = ROOT / "lib" / "bot-stats.json"
    path.write_text(json.dumps({"meta": meta, "bots": out, "combined": combo}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {path}")
    for k, v in out.items(): print(f"  {k:<14} trades {v['trades']:>5} WR {v['winRate']:>5}% PF {v['pf']:>5} pnl {v['pnl']:>9} DD {v['maxDD']:>7} sharpe {v['sharpeIn']}/{v['sharpeOut']}")
    for k, v in combo.items(): print(f"  combined {k:<5} pnl {v['pnl']:>9} DD {v['maxDD']:>7} sharpe {v['sharpeIn']}/{v['sharpeOut']}")


if __name__ == "__main__":
    main()
