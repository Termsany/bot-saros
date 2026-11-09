"""
momentum_ls: the best day to open and the best day to close (owner's question, 2026-11-06). Every entry weekday (7)
× every hold of 1–7 days (the basket is flat from the exit until the next entry day) = 49 variants of the live rule:
rank the top 50 by 30-day volume on their last 2 weeks' return at the close before the entry day, long the strongest 5
and short the weakest 5 at the entry day's 00:00 UTC open, stop 40% of the price (x2), $26 margin, fees 0.04% per
side, real funding.

Picking the best of 49 on the whole history would pick luck. So the variant is chosen on before 2024 only (Sharpe of
daily PnL), and judged on 2024 → 2026-10, which played no part in the choice. The rank correlation between the two
periods across all 49 says whether a "best day" carries over at all.

  python -X utf8 research/momentum_day_grid_study.py
"""
import sys, pickle, math
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import short_study as ss
import pump_momentum_study as pm
import strategies_trend as st

CACHE = ss.CACHE
AMOUNT, LEV, FEE = 26, 2, 0.0004
CUT = pd.Timestamp("2024-01-01")
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
STOP = st.STOP_SHARE / LEV                    # 40% of the price


class Coin:
    """One coin's daily arrays, built once (the grid runs 49 × ~3,400 trades)."""
    def __init__(self, df, fund):
        self.idx = pd.to_datetime(df.ts, unit="ms").values
        self.o, self.h, self.l, self.c, self.ts = (df[k].values for k in ("open", "high", "low", "close", "ts"))
        self.f = np.array([fund.get(int(t), 0.0) for t in df.ts])

    def trade(self, d, side, hold):
        k = int(np.searchsorted(self.idx, np.datetime64(d))) + 1        # the open after the ranking close
        if k >= len(self.o): return None
        sg = 1 if side == "long" else -1
        e = self.o[k]; q = AMOUNT * LEV / e; stop = e * (1 - sg * STOP); fu = 0.0
        for j in range(k, min(len(self.o), k + hold)):
            if (sg == -1 and self.h[j] >= stop) or (sg == 1 and self.l[j] <= stop):
                x = max(self.o[j], stop) if sg == -1 else min(self.o[j], stop)
                return int(self.ts[j]), sg * (x - e) * q - (e * q + x * q) * FEE + fu
            fu += -sg * q * self.c[j] * self.f[j]
        j = k + hold
        x, t = (self.o[j], self.ts[j]) if j < len(self.o) else (self.c[-1], self.ts[-1])
        return int(t), sg * (x - e) * q - (e * q + x * q) * FEE + fu


def baskets(data, rk, past, entry_wd):
    """(symbol, ranking day, side) for every week, entering on weekday `entry_wd` (0 = Monday)."""
    rank_wd = (entry_wd - 1) % 7
    out = []
    for d in past.index[44:]:
        if d.weekday() != rank_wd or d not in rk.index: continue
        r = rk.loc[d]; elig = r[r <= 50].index
        p = past.loc[d, elig].dropna()
        if len(p) < 20: continue
        p = p.sort_values()
        out += [(s, d, "short") for s in p.index[:5]] + [(s, d, "long") for s in p.index[-5:]]
    return out


def stats(rows):
    t = pd.DataFrame(rows, columns=["exit_ts", "pnl"])
    t["day"] = pd.to_datetime(t.exit_ts, unit="ms").dt.floor("D")
    daily = t.groupby("day").pnl.sum()
    daily = daily.reindex(pd.date_range(daily.index.min(), daily.index.max()), fill_value=0)
    eq = daily.cumsum(); dd = float((eq.cummax() - eq).max())
    sh = lambda x: x.mean() / x.std() * math.sqrt(365) if x.std() else 0.0
    pf = lambda x: x[x > 0].sum() / -x[x < 0].sum()
    a, b = daily[daily.index < CUT], daily[daily.index >= CUT]
    return {"net $": t.pnl.sum(), "DD $": dd, "PF": pf(t.pnl), "PF 2024→": pf(t[t.day >= CUT].pnl),
            "Sharpe <2024": sh(a), "Sharpe 2024→": sh(b), "net <2024": a.sum(), "net 2024→": b.sum()}


def main():
    data = pickle.loads((CACHE / "universe_daily.pkl").read_bytes())
    fund_raw = pickle.loads((CACHE / "universe_funding.pkl").read_bytes())
    coins = {s: Coin(df, fund_raw.get(s, {})) for s, df in data.items()}
    rk = pm.rank_table(data, 60)
    closes = pd.DataFrame({s: df.set_index(pd.to_datetime(df.ts, unit="ms")).close for s, df in data.items()}).sort_index()
    past = closes / closes.shift(14) - 1
    res = []
    for wd in range(7):
        b = baskets(data, rk, past, wd)
        for hold in range(1, 8):
            rows = [x for s, d, side in b if (x := coins[s].trade(d, side, hold))]
            r = stats(rows)
            exit_wd = (wd + hold) % 7
            res.append({"open": DAYS[wd], "hold": hold, "close (00:00)": DAYS[exit_wd], **r})
    out = pd.DataFrame(res)
    pd.set_option("display.width", 220)
    fmt = out.copy()
    for k in ("net $", "DD $", "net <2024", "net 2024→"): fmt[k] = fmt[k].round(0).astype(int)
    for k in ("PF", "PF 2024→", "Sharpe <2024", "Sharpe 2024→"): fmt[k] = fmt[k].round(2)
    print(f"momentum_ls, every open day × hold, ${AMOUNT} margin x{LEV}\n")
    print("Sharpe before 2024 (rows: open day, columns: days held):")
    print(out.pivot(index="open", columns="hold", values="Sharpe <2024").reindex(DAYS).round(2).to_string())
    print("\nSharpe 2024 → (the period not used to choose):")
    print(out.pivot(index="open", columns="hold", values="Sharpe 2024→").reindex(DAYS).round(2).to_string())
    print("\nnet $, whole history:")
    print(out.pivot(index="open", columns="hold", values="net $").reindex(DAYS).round(0).astype(int).to_string())
    rho = out["Sharpe <2024"].rank().corr(out["Sharpe 2024→"].rank())
    print(f"\nrank correlation of Sharpe before 2024 vs after, all 49: {rho:+.2f}")
    top = fmt.sort_values("Sharpe <2024", ascending=False)
    print("\ntop 5 chosen on before 2024, and what they did after:")
    print(top.head(5).to_string(index=False))
    now = fmt[(fmt.open == "Mon") & (fmt.hold == 7)]
    print("\nthe live rule (Mon, 7 days):"); print(now.to_string(index=False))
    pos = (out["Sharpe 2024→"] > now["Sharpe 2024→"].iloc[0]).sum()
    print(f"\nafter 2024, {pos} of 49 variants beat the live rule's Sharpe; the rank of the in-sample best after 2024: "
          f"{int(out['Sharpe 2024→'].rank(ascending=False)[top.index[0]])} of 49")


if __name__ == "__main__":
    main()
