"""
Which coins should the ratio trend trade? (owner, 2026-11-07: "must the pairs be among high-volume coins?")

Every universe here is picked by a rule known at the time, re-picked every week; only "5 majors" is hindsight (the
reference the fair rules try to reach). Same strategy and costs as research/ratio_netting_study.py: every pair among
the members, long the stronger / short the weaker while their price ratio is above its 50-day mean, netted to one
position per coin with a 40% stop per coin, $26 margin x2 per unit, fees 0.04% per side, real funding, daily model.

Universes:
  vol30 top K       30-day average volume (what runs now with K = 7)
  vol90 / vol180    a longer average: a coin needs months of volume, not one pumped week
  persistent top K  among the coins in the 30-day top 10 in at least 8 of the last 12 weekly picks, the top K
  aged top K        vol30 top K among coins with at least 365 days of history
  aged vol90 top K  both

The pick: judged before 2024 only; 2024 -> is the check nobody chose with.

  python -X utf8 research/ratio_universe_study.py            the 13 universes
  python -X utf8 research/ratio_universe_study.py --no-btc   without BTC and ETH (a small account, §25)
"""
import sys, math
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ratio_netting_study as rn

START, CUT, AMOUNT = rn.START, rn.CUT, rn.AMOUNT
MAJORS = ("BTC", "ETH", "SOL", "BNB", "XRP")


def vol_rank(data, window, min_history):
    """day x coin rank by `window`-day average USDT volume (1 = most); NaN with < min_history days of history."""
    vol = {}
    for s, df in data.items():
        v = df.set_index(pd.to_datetime(df.ts, unit="ms")).qvol.rolling(window).mean()
        v.iloc[:max(min_history, window) - 1] = np.nan
        vol[s] = v
    return pd.DataFrame(vol).rank(axis=1, ascending=False)


def weekly(days):
    return days[days >= START][::7]


def members_top(rk, days, k):
    m = {d: tuple(sorted(rk.loc[d][rk.loc[d] <= k].index)) for d in weekly(days)}
    return pd.Series(m).reindex(days, method="ffill")


def members_persistent(rk, days, k, top=10, need=8, of=12):
    weeks = rk.index[rk.index >= START - pd.Timedelta(days=7 * of)][::7]
    weeks = [w for w in weeks]
    out = {}
    for d in weekly(days):
        past = [w for w in weeks if w <= d][-of:]
        if len(past) < of: continue
        count = sum((rk.loc[w] <= top).astype(int) for w in past)
        ok = count[count >= need].index
        r = rk.loc[d, ok].dropna().sort_values()
        out[d] = tuple(sorted(r.index[:k]))
    return pd.Series(out).reindex(days, method="ffill")


def members_fixed(days, coins, data):
    syms = {s.split("/")[0].replace("USDT", ""): s for s in data}
    pick = tuple(sorted(syms[c] for c in coins if c in syms))
    return pd.Series({d: pick for d in days})


def without(members, coins=("BTCUSDT", "ETHUSDT")):
    """The same weekly pick with these coins taken out and the next ones in line not added: what a small account can
    hold (Binance's smallest order: BTC $50, ETH $20, almost every other coin $5, checked 2026-11-07)."""
    return members.map(lambda ms: tuple(c for c in ms if c not in coins) if isinstance(ms, tuple) else ms)


def members_top_excluding(rk, days, k, coins=("BTCUSDT", "ETHUSDT")):
    """The top K by volume among the coins left once these are taken out (the next ones in line come in)."""
    return members_top(rk.drop(columns=[c for c in coins if c in rk.columns]).rank(axis=1), days, k)


def stats(df, label):
    d = df.pnl; eq = d.cumsum(); dd = float((eq.cummax() - eq).max())
    sh = lambda x: round(x.mean() / x.std() * math.sqrt(365), 2) if x.std() else 0.0
    yrs = d.groupby(d.index.year).sum()
    return {"universe": label, "pnl $": round(d.sum()), "worst DD $": round(dd), "DD margins": round(dd / AMOUNT, 1),
            "pnl/DD": round(d.sum() / dd, 2) if dd else None,
            "Sharpe <2024": sh(d[d.index < CUT]), "Sharpe 2024→": sh(d[d.index >= CUT]),
            "pnl 2024→ $": round(d[d.index >= CUT].sum()), "avg margin $": round(df.gross_units.mean() * AMOUNT),
            "worst year $": round(yrs.min()), "2022 $": round(yrs.get(2022, 0)), "2026 $": round(yrs.get(2026, 0)),
            "max units": int(df.gross_units.max()), "DD units": round(dd / AMOUNT)}


def main():
    data, O, C, F, _ = rn.load()
    H, L = (pd.DataFrame({s: df.set_index(pd.to_datetime(df.ts, unit="ms"))[k] for s, df in data.items()}).sort_index()
            for k in ("high", "low"))
    days = O.index[O.index >= START]
    r30, r90, r180 = vol_rank(data, 30, 120), vol_rank(data, 90, 120), vol_rank(data, 180, 180)
    a30, a90 = vol_rank(data, 30, 365), vol_rank(data, 90, 365)
    universes = [("5 majors (hindsight)", members_fixed(days, MAJORS, data))]
    for k in (5, 7):
        universes += [(f"vol30 top {k}" + (" (runs now)" if k == 7 else ""), members_top(r30, days, k)),
                      (f"vol90 top {k}", members_top(r90, days, k)),
                      (f"vol180 top {k}", members_top(r180, days, k)),
                      (f"persistent top {k}", members_persistent(r30, days, k)),
                      (f"aged top {k}", members_top(a30, days, k)),
                      (f"aged vol90 top {k}", members_top(a90, days, k))]
    if "--no-btc" in sys.argv:          # owner, 2026-11-07: can the ratio trend run on a small account?
        universes = []
        for k in (5, 7):
            universes += [(f"vol30 top {k}", members_top(r30, days, k)),
                          (f"vol30 top {k}, no BTC/ETH (next in line)", members_top_excluding(r30, days, k)),
                          (f"persistent top {k}", members_persistent(r30, days, k)),
                          (f"persistent top {k}, no BTC/ETH (next in line)",
                           members_persistent(r30.drop(columns=["BTCUSDT", "ETHUSDT"]).rank(axis=1), days, k))]
    rows, churn = [], {}
    for label, members in universes:
        sig = rn.signals(C, days, members)
        df, _ = rn.simulate_netted_stop(O, H, L, F, days, sig)
        rows.append(stats(df, label))
        w = members.reindex(weekly(days)).dropna()
        ch = [len(set(a) ^ set(b)) / 2 for a, b in zip(w.iloc[:-1], w.iloc[1:])]
        coins = sorted({c for ms in w for c in ms})
        churn[label] = (round(float(np.mean(ch)), 2), len(coins), ", ".join(c.split("/")[0] for c in coins[:40]))
    out = pd.DataFrame(rows).set_index("universe")
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    print(f"ratio trend, netted + 40% stop per coin, ${AMOUNT} x{rn.LEV} per unit, {days[0].date()} → {days[-1].date()}\n")
    print(out.to_string())
    print("\nmembers changed per week (avg) · distinct coins ever · coins")
    for k, (c, n, names) in churn.items():
        print(f"  {k:24s} {c:5}  {n:3}  {names}")


if __name__ == "__main__":
    main()
