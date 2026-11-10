"""
Two strategies on one Binance account (docs/trend-daily-live-plan.md section 2): one-way mode holds one position per
coin and the risk gate refuses a second strategy on a coin another holds. Backtest both (trend_daily on the top 10,
momentum_ls weekly on the top 50, $26 x2, fees, real funding, from 2020) and count the trades the other one would
have blocked by holding the coin first, with what those trades made. Slot limits are not modelled.

  python -X utf8 research/shared_account_study.py
"""
import sys, pickle; from pathlib import Path; sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pandas as pd, short_study as ss, pump_momentum_study as pm, strategies_trend as st
from universe_study import ranks
data = pickle.loads((ss.CACHE / "universe_daily.pkl").read_bytes())
fr = pickle.loads((ss.CACHE / "universe_funding.pkl").read_bytes()); fund = {s: fr.get(s, {}) for s in data}
rk10 = ranks(data); ever10 = [s for s in data if (rk10[s] <= 10).any()]
trend = []
for s in ever10:
    df = data[s]; top10 = list((rk10[s].reindex(pd.to_datetime(df.ts, unit="ms")) <= 10).fillna(False))
    for t in st.run_trend_daily(list(df.open), list(df.high), list(df.low), list(df.close), list(df.ts),
                                [fund[s].get(int(x), 0.0) for x in df.ts], 26, 2, 0.0004, 0, top10):
        trend.append((s, t["entry_ts"], t["exit_ts"], t["pnl"]))
rk = pm.rank_table(data, 60); mom = []
for s, d, side in pm.momentum_positions(data, rk, 2, True):
    t = pm.momentum_trade(data[s], fund[s], d, side)
    if t: mom.append((s, t["entry_ts"], t["exit_ts"], t["pnl"] * 26 / pm.AMOUNT, side))
T = pd.DataFrame(trend, columns="s a b pnl".split()); M = pd.DataFrame(mom, columns="s a b pnl side".split())
cut = int(pd.Timestamp("2020-01-01").value // 10**6); T = T[T.a >= cut]; M = M[M.a >= cut]
def hits(X, Y):
    out = []
    for r in X.itertuples():
        y = Y[Y.s == r.s]; out.append(bool(((y.a < r.b) & (y.b > r.a)).any()))
    return pd.Series(out, index=X.index)
mh, th = hits(M, T), hits(T, M)
# who was there first: a momentum leg opening while trend holds the coin is refused, and vice versa
def first(X, Y):
    out = []
    for r in X.itertuples():
        y = Y[Y.s == r.s]; out.append(bool(((y.a <= r.a) & (y.b > r.a)).any()))
    return pd.Series(out, index=X.index)
m_blocked, t_blocked = first(M, T), first(T, M)
print(f"momentum legs {len(M)}: overlap a trend trade {mh.sum()} ({mh.mean():.1%}); refused because trend held the coin first {m_blocked.sum()} ({m_blocked.mean():.1%}), their pnl {M.pnl[m_blocked].sum():+.0f}$ of {M.pnl.sum():+.0f}$")
print(f"trend trades {len(T)}: overlap a momentum leg {th.sum()} ({th.mean():.1%}); refused because momentum held it first {t_blocked.sum()} ({t_blocked.mean():.1%}), their pnl {T.pnl[t_blocked].sum():+.0f}$ of {T.pnl.sum():+.0f}$")
print("momentum blocked by side:", M[m_blocked].side.value_counts().to_dict(), "coins:", M[m_blocked].s.value_counts().head(8).to_dict())
print("since 2024: momentum refused", int(m_blocked[M.a >= int(pd.Timestamp('2024-01-01').value//10**6)].sum()), "trend refused", int(t_blocked[T.a >= int(pd.Timestamp('2024-01-01').value//10**6)].sum()))
