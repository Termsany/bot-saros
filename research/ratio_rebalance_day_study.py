"""
The ratio trend switching only on a set day (owner, 2026-11-17): what if the pairs change once a week, or on chosen
days, instead of at every daily close?

Today the signal (each pair's price ratio against its 50-day mean) is read at every daily close and the book changes
the next open. Here the same daily signal is read only on the switching days: on those, the book takes that day's
pairs, members and sides; in between it keeps them. A coin whose 40% stop fires stays flat until its units change
(as live). Schedules (the weekday is the one the trades happen on, at 00:00 UTC — the close of the day before):
  daily (today) · weekly on each of the 7 days · twice a week (Mon + Thu) · every 14 days (from a Monday)

Two books, both universes (30-day top 7 by volume, with and without BTC/ETH):
  NETTED as the live bot trades it — one position per coin, a change closed and reopened (ratio_net_live_study, §34);
  PAIRS as the paper bot trades it (ratio_netting_study.simulate "pairs").
The rule, fixed before the run: a schedule is adopted only if it beats daily's NETTED Sharpe before 2024 on the
no-BTC universe and is not lower after, and the other weekdays agree (one good weekday alone is luck).

  python -X utf8 research/ratio_rebalance_day_study.py
"""
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ratio_netting_study as rn
import ratio_universe_study as ru
import ratio_net_live_study as rl

DAYS = "Mon Tue Wed Thu Fri Sat Sun".split()


def on_schedule(sig, days, switch):
    """The daily signal read only on switching days; `switch(trade_day)` says whether the book may change."""
    out, cur = {}, {}
    for i, d in enumerate(days):
        if i == 0 or switch(d + pd.Timedelta(days=1)): cur = sig.get(d, {})
        out[d] = cur
    return out


def schedules(days):
    first_monday = next(d for d in days if (d + pd.Timedelta(days=1)).weekday() == 0) + pd.Timedelta(days=1)
    s = [("daily (today)", lambda t: True)]
    s += [(f"weekly, {DAYS[w]}", lambda t, w=w: t.weekday() == w) for w in range(7)]
    s += [("twice a week, Mon + Thu", lambda t: t.weekday() in (0, 3)),
          ("every 14 days, Mon", lambda t: t.weekday() == 0 and (t - first_monday).days % 14 == 0)]
    return s


def main():
    data, O, C, F, _ = rn.load()
    H, L = (pd.DataFrame({s: df.set_index(pd.to_datetime(df.ts, unit="ms"))[k] for s, df in data.items()}).sort_index()
            for k in ("high", "low"))
    days = O.index[O.index >= rn.START]
    r30 = ru.vol_rank(data, 30, 120)
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    print(f"ratio trend, 30-day top 7, ${rn.AMOUNT} x{rn.LEV} a unit, {days[0].date()} → {days[-1].date()}")
    for label, members in (("no BTC/ETH (the real-money choice)", ru.members_top_excluding(r30, days, 7)),
                           ("with BTC/ETH (the paper bot)", ru.members_top(r30, days, 7))):
        daily_sig = rn.signals(C, days, members)
        rows = []
        for name, switch in schedules(days):
            sig = on_schedule(daily_sig, days, switch)
            net, changes = rl.simulate(O, H, L, F, days, sig, reopen=True)
            pairs, trades = rn.simulate(O, F, days, sig, "pairs")
            s = ru.stats(net, name)
            p = rn.stats(pairs, trades, name)
            rows.append({"schedule": name, "NET pnl $": s["pnl $"], "NET DD $": s["worst DD $"],
                         "NET Sharpe <2024": s["Sharpe <2024"], "NET Sharpe 2024→": s["Sharpe 2024→"],
                         "NET pnl 2024→ $": s["pnl 2024→ $"], "NET fees $": round(net.fees.sum()),
                         "changes/yr": round(changes / (len(days) / 365)), "2022 $": s["2022 $"], "2026 $": s["2026 $"],
                         "PAIRS pnl $": p["pnl $"], "PAIRS DD $": p["worst DD $"], "PAIRS Sharpe <2024": p["Sharpe <2024"],
                         "PAIRS Sharpe 2024→": p["Sharpe 2024→"], "pair trades": p["pair trades"], "win%": p["win%"], "PF": p["PF"]})
        print(f"\n{label}\n" + pd.DataFrame(rows).set_index("schedule").to_string())


if __name__ == "__main__":
    main()
