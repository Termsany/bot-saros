"""momentum_ls at the costs the real account pays (development-plan 2.5, 2026-11-04).

The baseline (research/baseline_stats.py) charges 0.04 % a side and no slippage. The first real rebalance paid 0.05 %
(Binance's taker fee). This re-runs the same weekly basket — every Binance USDT-M perpetual since 2019, delisted
included, real per-coin funding — at higher costs a side. Slippage is a cost on each fill's notional just like the fee,
so 0.06-0.10 % stand for the fee plus 1-5 bps of slippage.

  python research/momentum_fee_sensitivity.py     # needs research/.cache/universe_*.pkl (research/README.md)
"""
import sys, pickle
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pump_momentum_study as pm
from baseline_stats import CACHE

COSTS = (0.0004, 0.0005, 0.0006, 0.0008, 0.0010)
CUT = pd.Timestamp("2024-01-01")


def summary(trades):
    pnl = np.array([t["pnl"] for t in trades]); margin = pm.AMOUNT
    wins, losses = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    weeks = pd.Series(pnl, index=pd.to_datetime([t["entry_ts"] for t in trades], unit="ms")).resample("W").sum()
    eq = weeks.cumsum(); dd = (eq.cummax() - eq).max()
    return {"trades": len(pnl), "pnl_margins": pnl.sum() / margin, "pf": wins / losses if losses else float("inf"),
            "per_trade_pct": pnl.mean() / margin * 100, "sharpe": weeks.mean() / weeks.std() * np.sqrt(52) if weeks.std() else 0,
            "max_dd_margins": dd / margin}


def main():
    data = pickle.loads((CACHE / "universe_daily.pkl").read_bytes())
    fund_raw = pickle.loads((CACHE / "universe_funding.pkl").read_bytes())
    fund = {s: fund_raw.get(s, {}) for s in data}
    plan = pm.momentum_positions(data, pm.rank_table(data, 60), 2, True)
    rows = []
    for cost in COSTS:
        pm.FEE = cost
        tr = [t for s, d, side in plan if (t := pm.momentum_trade(data[s], fund[s], d, side))]
        late = [t for t in tr if pd.Timestamp(t["entry_ts"], unit="ms") >= CUT]
        rows.append((cost, summary(tr), summary(late)))
    print("| cost a side | trades | PF (from 2024) | PnL, margins (from 2024) | per trade % margin (from 2024) | Sharpe weekly (from 2024) | worst drawdown, margins |")
    print("|---|---|---|---|---|---|---|")
    for cost, a, b in rows:
        print(f"| {cost * 100:.2f}% | {a['trades']} | {a['pf']:.2f} ({b['pf']:.2f}) | {a['pnl_margins']:+.1f} ({b['pnl_margins']:+.1f}) | "
              f"{a['per_trade_pct']:+.2f} ({b['per_trade_pct']:+.2f}) | {a['sharpe']:.2f} ({b['sharpe']:.2f}) | {a['max_dd_margins']:.1f} |")
    # where the edge is gone: the cost a side at which the whole run's PnL reaches zero
    a0, a1 = rows[0][1], rows[1][1]
    per_bp = (a0["pnl_margins"] - a1["pnl_margins"]) / 1.0           # margins lost per extra 0.01 % a side
    if per_bp > 0:
        print(f"\nbreak-even cost a side (whole run, linear): {COSTS[0] * 100 + a0['pnl_margins'] / per_bp * 0.01:.2f}%")
    b0, b1 = rows[0][2], rows[1][2]
    per_bp = (b0["pnl_margins"] - b1["pnl_margins"]) / 1.0
    if per_bp > 0:
        print(f"break-even cost a side (from 2024, linear): {COSTS[0] * 100 + b0['pnl_margins'] / per_bp * 0.01:.2f}%")


if __name__ == "__main__":
    main()
