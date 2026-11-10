"""
The three strategies together on one $500 account, in real dollars (owner, 2026-11-09: "do it and show me the
results"): momentum_ls (the real bot), against the crowd (X3 L3, §29) and RSI-2 with BTC above its 200-day average
(§28), alone and combined, so the choice is made on the yearly return, the worst drawdown and the worst month.

Each strategy's trades come from its own study's simulator ($20 margin x2, fees 0.04% a side, real funding, the 40%
guard) and are scaled to the dollars per trade of the portfolio. Fixed size (no compounding): the result is dollars
on the starting $500. Period: from 2022-01 (the open-interest files start 2021-12), after 2024 shown apart.

Portfolios (sizes fixed before any result):
  momentum alone             $26 a leg (the real bot today: 10 legs = $260 of margin)
  momentum + crowd           $26 + $20 (3 + 3 legs)
  momentum + RSI-2           $26 + $20
  all three                  $20 + $20 + $15

  RAQM_RESEARCH_CACHE=/opt/raqm-data/research python research/portfolio_dollars_study.py [out.json]
The open-interest files are on the server only: run it there.
"""
import json, math, os, pickle, sys
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import paper_baseline as pb
import core_improve_study as ci
import pump_momentum_study as pm

CACHE = Path(os.getenv("RAQM_RESEARCH_CACHE") or Path(__file__).resolve().parent / ".cache")
CAPITAL, BASE, START, CUT = 500.0, 20.0, pd.Timestamp("2022-01-01"), pd.Timestamp("2024-01-01")
PORTFOLIOS = {
    "momentum alone": {"momentum": 26},
    "momentum + crowd": {"momentum": 26, "crowd": 20},
    "momentum + RSI-2": {"momentum": 26, "rsi2": 20},
    "all three": {"momentum": 20, "crowd": 20, "rsi2": 15},
}


def frame(trades, name):
    t = pd.DataFrame(trades)
    t["entry_d"] = pd.to_datetime(t.entry_ts, unit="ms"); t["exit_d"] = pd.to_datetime(t.exit_ts, unit="ms")
    t["strategy"] = name
    return t[t.entry_d >= START].reset_index(drop=True)


def stats(t, days):
    daily = t.groupby(t.exit_d.dt.floor("D")).usd.sum().reindex(days, fill_value=0.0)
    eq = daily.cumsum(); dd = eq.cummax().clip(lower=0) - eq
    monthly = daily.resample("MS").sum(); yearly = daily.resample("YS").sum()
    years = len(days) / 365.25
    sh = lambda x: round(float(x.mean() / x.std() * math.sqrt(365)), 2) if x.std() else 0.0
    # the most margin open at once: every open leg's dollars on the days it is held
    ev = pd.concat([pd.Series(t.margin.values, t.entry_d.values), pd.Series(-t.margin.values, t.exit_d.values)]).sort_index()
    after = daily[daily.index >= CUT]
    return {
        "trades": int(len(t)), "win_pct": round(float((t.usd > 0).mean() * 100), 1),
        "pnl_usd": round(float(daily.sum())), "per_year_pct": round(float(daily.sum() / years / CAPITAL * 100), 1),
        "after_per_year_pct": round(float(after.sum() / (len(after) / 365.25) / CAPITAL * 100), 1),
        "max_dd_usd": round(float(dd.max())), "max_dd_pct": round(float(dd.max() / CAPITAL * 100), 1),
        "worst_month_usd": round(float(monthly.min())), "best_month_usd": round(float(monthly.max())),
        "months_up_pct": round(float((monthly > 0).mean() * 100)),
        "worst_trade_usd": round(float(t.usd.min()), 1),
        "sharpe": sh(daily), "sharpe_before": sh(daily[daily.index < CUT]), "sharpe_after": sh(after),
        "max_margin_usd": round(float(ev.groupby(level=0).sum().cumsum().max())),
        "years": {str(k.year): round(float(v)) for k, v in yearly.items()},
        "curve": [[d.strftime("%Y-%m-%d"), round(float(v), 1)] for d, v in eq.resample("W").last().items()],
    }


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
    for k in T:
        T[k] = T[k][T[k].exit_d <= end]

    daily = pd.DataFrame({k: (t.pnl * 1.0).groupby(t.exit_d.dt.floor("D")).sum().reindex(days, fill_value=0.0) for k, t in T.items()})
    corr = daily.resample("W").sum().corr().round(2)

    out = {"capital": CAPITAL, "start": str(START.date()), "end": str(end.date()), "portfolios": {}, "sizes": PORTFOLIOS,
           "correlation_weekly": corr.to_dict()}
    print(f"$500 account, fixed size, {START.date()} -> {end.date()}")
    print("portfolio | trades | win% | PnL $ | %/yr | %/yr 2024-> | maxDD $ | maxDD % | worst month $ | months up % | Sharpe <2024 | Sharpe 2024-> | max margin $ | years")
    for name, sizes in PORTFOLIOS.items():
        t = pd.concat([T[k].assign(usd=T[k].pnl * m / BASE, margin=m) for k, m in sizes.items()], ignore_index=True)
        s = stats(t, days); out["portfolios"][name] = s
        print(f"{name} | {s['trades']} | {s['win_pct']} | {s['pnl_usd']} | {s['per_year_pct']} | {s['after_per_year_pct']} | {s['max_dd_usd']} | "
              f"{s['max_dd_pct']} | {s['worst_month_usd']} | {s['months_up_pct']} | {s['sharpe_before']} | {s['sharpe_after']} | {s['max_margin_usd']} | {s['years']}")
    for k, m in (("crowd", 20), ("rsi2", 20)):
        s = stats(T[k].assign(usd=T[k].pnl * m / BASE, margin=m), days); out["portfolios"][f"{k} alone ($20)"] = s
        print(f"{k} alone ($20) | {s['trades']} | {s['win_pct']} | {s['pnl_usd']} | {s['per_year_pct']} | {s['after_per_year_pct']} | {s['max_dd_usd']} | "
              f"{s['max_dd_pct']} | {s['worst_month_usd']} | {s['months_up_pct']} | {s['sharpe_before']} | {s['sharpe_after']} | {s['max_margin_usd']} | {s['years']}")
    print("weekly correlation:\n", corr)
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
