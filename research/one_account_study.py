"""
The three strategies on ONE Binance account vs each on its own sub-account (owner, 2026-11-09: "test what that costs").

One-way mode holds one position per coin, and the risk gate refuses a coin another strategy already holds. So on one
account a trade is refused when, at its entry, another strategy's accepted trade holds the same coin (either side);
the refused trade holds nothing. Trades are taken in entry order; on the same timestamp momentum goes first, then the
crowd, then RSI-2 (fixed before any result). A strategy never blocks itself: its own simulator already rebalances.

Sizes and statistics are those of portfolio_dollars_study.py ($500, fixed size, from 2022-01, 2024-> shown apart).

  RAQM_RESEARCH_CACHE=/opt/raqm-data/research python research/one_account_study.py
The open-interest files are on the server only: run it there.
"""
import os, pickle, sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import paper_baseline as pb
import core_improve_study as ci
import pump_momentum_study as pm
from portfolio_dollars_study import frame, stats, CACHE, BASE, START, CUT

ORDER = {"momentum": 0, "crowd": 1, "rsi2": 2}
PORTFOLIOS = {"momentum + crowd": {"momentum": 26, "crowd": 20}, "all three": {"momentum": 20, "crowd": 20, "rsi2": 15}}


def one_account(t):
    """t: every strategy's trades. Returns a bool Series: taken on one shared account."""
    t = t.assign(o=t.strategy.map(ORDER)).sort_values(["entry_ts", "o"])
    held, keep = {}, {}
    for r in t.itertuples():
        busy = [(st, b) for st, b in held.get(r.symbol, []) if b > r.entry_ts]
        held[r.symbol] = busy
        if any(st != r.strategy for st, _ in busy):
            keep[r.Index] = False; continue
        keep[r.Index] = True; busy.append((r.strategy, r.exit_ts))
    return pd.Series(keep).reindex(t.index).sort_index()


def main():
    data = pickle.loads((CACHE / "universe_daily.pkl").read_bytes())
    fund_raw = pickle.loads((CACHE / "universe_funding.pkl").read_bytes())
    fund = {s: fund_raw.get(s, {}) for s in data}
    btc = {100: ci.btc_above(data, 100), 200: ci.btc_above(data, 200)}
    crowd = pb.retail_fade(data, fund)
    if not crowd:
        sys.exit("no open-interest files here: run it on the server")
    T = {"momentum": frame(ci.run_momentum(data, fund, pm.rank_table(data, 60), btc, "2w", 0), "momentum"),
         "crowd": frame(crowd, "crowd"), "rsi2": frame(pb.rsi2_btc(data, fund), "rsi2")}
    end = min(t.exit_d.max() for t in T.values()).floor("D")
    days = pd.date_range(START, end, freq="D")

    print(f"$500, fixed size, {START.date()} -> {end.date()}")
    print("portfolio | account | trades | PnL $ | %/yr | %/yr 2024-> | maxDD $ | worst month $ | months up % | Sharpe <2024 | Sharpe 2024-> | max margin $")
    for name, sizes in PORTFOLIOS.items():
        t = pd.concat([T[k][T[k].exit_d <= end].assign(usd=lambda x, m=m: x.pnl * m / BASE, margin=m) for k, m in sizes.items()],
                      ignore_index=True)
        ok = one_account(t)
        for label, sub in (("separate", t), ("one account", t[ok])):
            s = stats(sub, days)
            print(f"{name} | {label} | {s['trades']} | {s['pnl_usd']} | {s['per_year_pct']} | {s['after_per_year_pct']} | {s['max_dd_usd']} | "
                  f"{s['worst_month_usd']} | {s['months_up_pct']} | {s['sharpe_before']} | {s['sharpe_after']} | {s['max_margin_usd']}")
        after = t.entry_d >= CUT
        for k in sizes:
            m = t.strategy == k; r = m & ~ok
            print(f"   {k}: refused {int(r.sum())} of {int(m.sum())} ({r.sum() / m.sum():.1%}), their PnL {t.usd[r].sum():+.0f}$ of "
                  f"{t.usd[m].sum():+.0f}$; after 2024 refused {int((r & after).sum())}, PnL {t.usd[r & after].sum():+.0f}$")


if __name__ == "__main__":
    main()
