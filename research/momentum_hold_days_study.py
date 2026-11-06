"""
momentum_ls with the weekend off (owner's question, 2026-11-06): open the basket Monday 00:00 UTC as now, but close it
earlier in the week and stay flat until the next Monday, against holding the full week (what runs).

Same rules as the live bot and research/pump_momentum_study.py: every Monday, rank the top 50 by 30-day volume on
their last 2 weeks' return (Sunday's close), long the strongest 5 and short the weakest 5 at Monday's open, stop 40%
of the price (x2), fees 0.04% per side, real funding. Only the exit day changes:
  7 days  Monday → next Monday (what runs)
  5 days  close Saturday 00:00 (end of Friday) — flat Saturday and Sunday
  4 days  close Friday 00:00 (end of Thursday) — flat Friday to Sunday
  3 days  close Thursday 00:00 (end of Wednesday)

  python -X utf8 research/momentum_hold_days_study.py
"""
import sys, pickle, math
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import short_study as ss
import pump_momentum_study as pm
import strategies_trend as st

CACHE = ss.CACHE
AMOUNT, LEV, FEE = 26, 2, 0.0004            # the real account's margin
CUT = pd.Timestamp("2024-01-01")
HOLDS = (7, 5, 4, 3)


def trade(df, fund, d, side, hold):
    """momentum_trade with the exit `hold` days after the entry open (at that day's open)."""
    idx = pd.to_datetime(df.ts, unit="ms"); k = idx.searchsorted(d) + 1
    if k >= len(df): return None
    o, h, l, c, ts = df.open.values, df.high.values, df.low.values, df.close.values, df.ts.values
    sg = 1 if side == "long" else -1
    e = o[k]; q = AMOUNT * LEV / e; stop = e * (1 - sg * st.STOP_SHARE / LEV); fu = 0.0
    for j in range(k, min(len(df), k + hold)):
        if (sg == -1 and h[j] >= stop) or (sg == 1 and l[j] <= stop):
            x = max(o[j], stop) if sg == -1 else min(o[j], stop)
            return dict(exit_ts=int(ts[j]), side=side, pnl=sg * (x - e) * q - (e * q + x * q) * FEE + fu, stop=True)
        fu += -sg * q * c[j] * fund.get(int(ts[j]), 0.0)
    j = k + hold
    x, t = (o[j], ts[j]) if j < len(df) else (c[-1], ts[-1])
    return dict(exit_ts=int(t), side=side, pnl=sg * (x - e) * q - (e * q + x * q) * FEE + fu, stop=False)


def picks(data, rk):
    """(symbol, Sunday, side): the Monday basket, ranked on Sunday's close."""
    closes = pd.DataFrame({s: df.set_index(pd.to_datetime(df.ts, unit="ms")).close for s, df in data.items()}).sort_index()
    past = closes / closes.shift(14) - 1
    out = []
    for d in closes.index[44:]:
        if d.weekday() != 6 or d not in rk.index: continue          # Sunday's candle; the trade opens Monday 00:00
        r = rk.loc[d]; elig = r[r <= 50].index
        p = past.loc[d, elig].dropna()
        if len(p) < 20: continue
        p = p.sort_values()
        out += [(s, d, "short") for s in p.index[:5]] + [(s, d, "long") for s in p.index[-5:]]
    return out


def stats(trades, label):
    t = pd.DataFrame(trades)
    t["day"] = pd.to_datetime(t.exit_ts, unit="ms").dt.floor("D")
    daily = t.groupby("day").pnl.sum()
    daily = daily.reindex(pd.date_range(daily.index.min(), daily.index.max()), fill_value=0)
    eq = daily.cumsum(); dd = float((eq.cummax() - eq).max())
    sh = lambda x: round(x.mean() / x.std() * math.sqrt(365), 2) if x.std() else 0.0
    pf = lambda x: round(x[x > 0].sum() / -x[x < 0].sum(), 2)
    recent = t[t.day >= CUT]
    return {"hold": label, "trades": len(t), "win%": round((t.pnl > 0).mean() * 100), "PF": pf(t.pnl), "PF 2024→": pf(recent.pnl),
            "net $": round(t.pnl.sum()), "net margins": round(t.pnl.sum() / AMOUNT, 1), "worst DD $": round(dd),
            "worst DD margins": round(dd / AMOUNT, 1), "Sharpe <2024": sh(daily[daily.index < CUT]), "Sharpe 2024→": sh(daily[daily.index >= CUT]),
            "stops %": round(t["stop"].mean() * 100, 1), "longs $": round(t[t.side == "long"].pnl.sum()), "shorts $": round(t[t.side == "short"].pnl.sum()),
            **{str(y): round(v) for y, v in t.groupby(t.day.dt.year).pnl.sum().items()}}


def main():
    data = pickle.loads((CACHE / "universe_daily.pkl").read_bytes())
    fund_raw = pickle.loads((CACHE / "universe_funding.pkl").read_bytes())
    fund = {s: fund_raw.get(s, {}) for s in data}
    rk = pm.rank_table(data, 60)
    basket = picks(data, rk)
    rows = []
    for hold in HOLDS:
        tr = [x for s, d, side in basket if (x := trade(data[s], fund[s], d, side, hold))]
        rows.append(stats(tr, {7: "7 days (now)", 5: "5 (flat Sat–Sun)", 4: "4 (flat Fri–Sun)", 3: "3 (flat Thu–Sun)"}[hold]))
    out = pd.DataFrame(rows).set_index("hold").T
    pd.set_option("display.width", 200)
    print(f"momentum_ls, Monday 00:00 UTC entry, ${AMOUNT} margin x{LEV}, {len(basket) // 10} weeks\n")
    print(out.to_string())


if __name__ == "__main__":
    main()
