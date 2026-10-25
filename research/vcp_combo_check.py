"""Is the best breakout variant from research/vcp_deep.py a new source of profit, or the daily trend bot again?"""
import sys, pickle, math
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent.parent)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import traders_study as ts, short_study as ss, pump_momentum_study as pm, bots_stats as bs, vcp_deep as vd
from universe_study import ranks

data = pickle.loads((ts.CACHE / "universe_daily.pkl").read_bytes())
fr = pickle.loads((ts.CACHE / "universe_funding.pkl").read_bytes()); fund = {s: fr.get(s, {}) for s in data}
A = ts.coin_arrays(data, fund, pm.rank_table(data, 60))
pick = ss.summary(vd.vcp(A, 100, "full", None, None, 20, "ma20", "40pct"), "pick")["_daily"]
rk10 = ranks(data); ever10 = [s for s in data if (rk10[s] <= 10).any()]
new = [s for s, df in data.items() if pd.to_datetime(df.ts.iloc[0], unit="ms") >= pd.Timestamp("2021-01-01")]
core = {k: ss.summary(v, k)["_daily"] for k, v in bs.trades_at(2, data, fund, rk10, ever10, pm.rank_table(data, 60), new).items()}
x = pd.concat([core["trend_daily"], pick], axis=1).fillna(0)
print(f"correlation with the daily trend bot: all {x.corr().iloc[0,1]:.2f}, after 2024 {x[x.index >= ts.CUT].corr().iloc[0,1]:.2f}")
sh = lambda d: round(float(d.mean() / d.std() * math.sqrt(365)), 2)
for label, ex in (("core only", {}), ("+ breakout (vcp_deep pick)", {"b": pick})):
    d = pd.DataFrame({**core, **ex}).fillna(0).sum(axis=1); eq = d.cumsum()
    print(f"{label:<30} pnl {round(d.sum()):>6}  maxDD {round(float((eq.cummax()-eq).max())):>5}  IS {sh(d[d.index < ts.CUT]):>5}  OOS {sh(d[d.index >= ts.CUT]):>5}")
