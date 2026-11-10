"""
RSI-2 with the BTC filter: can it win more often without losing its edge? (owner, 2026-11-10: "can you develop the
strategies we have and reach a higher win rate", after asking about 80-90% strategies.)

The bot today (the paper candidate of §28, `raqm-rsi2-btc`): top 10 by volume, the coin's close above its 200-day
average, BTC's close above its 200-day average, RSI-2 below 5 -> buy the next open; out at the open after the first
close above the 5-day average, or after 10 days; the 40% guard stop.

Eleven variants, fixed before any result. One change at a time, then three combinations:

  A   today
  B1  RSI-2 below 3                     B2  RSI-2 below 2          (fewer, deeper dips)
  C1  out after the first up close (close above the previous close)
  C2  out after the first close above the entry price               (the classic win-rate raiser)
  C3  a +3% take-profit order, else today's exit
  D   two halves: half at the signal, the other half the next open if the first day closed below the entry
  E   no entry on a day BTC fell more than 5%
  F1  C1 + D          F2  B1 + C1          F3  C2 + D

The rule, fixed first: a candidate must win more often than A in BOTH periods (before 2024, and from 2024) AND have a
Sharpe not below A's in both, on at least 60 trades. A higher win rate alone is not a result: the table shows the
average win, the average loss and the worst trade next to it. Added after the first run, because an exit that holds
its losers can hide them: the same book marked at every daily close ("MTM"), which a candidate must also not lose on.

$20 margin x2 per trade, fees 0.04% a side, real per-coin funding (as core_improve_study.py; D's halves are $10 each).

  python -X utf8 research/rsi2_winrate_study.py
"""
import math, pickle, sys
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import core_improve_study as ci
import pump_momentum_study as pm
import traders_study as ts

AMOUNT, LEV, FEE, CUT, MIN_TRADES = ci.AMOUNT, ci.LEV, ci.FEE, ci.CUT, ci.MIN_TRADES
TOP, HOLD = 10, 10

VARIANTS = {
    "A  today": {},
    "B1 RSI-2 < 3": {"T": 3},
    "B2 RSI-2 < 2": {"T": 2},
    "C1 out on the first up close": {"exit": "upclose"},
    "C2 out on the first close above entry": {"exit": "profit"},
    "C3 +3% take-profit, else today's exit": {"tp": 0.03},
    "D  two halves (add if day 1 closes lower)": {"scale": True},
    "E  no entry when BTC fell > 5% that day": {"calm": 0.05},
    "F1 up close + two halves": {"exit": "upclose", "scale": True},
    "F2 RSI-2 < 3 + up close": {"T": 3, "exit": "upclose"},
    "F3 close above entry + two halves": {"exit": "profit", "scale": True},
}


NEIGHBORS = {          # --neighbors: after the run, the exit that passed (C2) at nearby settings — a check, not a pick
    "A  today": {},
    "C2 (10 days, top 10, BTC filter)": {"exit": "profit"},
    "C2 5 days": {"exit": "profit", "hold": 5}, "C2 15 days": {"exit": "profit", "hold": 15}, "C2 20 days": {"exit": "profit", "hold": 20},
    "A  top 20": {"top": 20}, "C2 top 20": {"exit": "profit", "top": 20},
    "A  no BTC filter": {"btc": False}, "C2 no BTC filter": {"exit": "profit", "btc": False},
    "A  RSI-2 < 10": {"T": 10}, "C2 RSI-2 < 10": {"exit": "profit", "T": 10},
}


def run(A, btc200, btc_ret, T=5, exit="sma5", tp=0.0, scale=False, calm=0.0, hold=HOLD, top=TOP, btc=True):
    out = []
    for s, a in A.items():
        o, h, l, c, f, tss = a["o"], a["h"], a["l"], a["c"], a["f"], a["ts"]; n = len(c)
        if n < 210: continue
        r2, m5, m200 = ts.rsi(c, 2), ts.sma(c, 5), ts.sma(c, 200)
        bt = np.array([btc200.get(int(t), False) for t in tss])
        br = np.array([btc_ret.get(int(t), 0.0) for t in tss])
        i = 200
        while i < n - 2:
            ok = a["rk"][i + 1] <= top and r2[i] < T and c[i] > m200[i] and (bt[i] or not btc) and (not calm or br[i] > -calm)
            if not ok: i += 1; continue
            k = i + 1; unit = AMOUNT * LEV * (0.5 if scale else 1.0)
            legs = [(k, o[k], unit / o[k])]                      # (bar, price, quantity)
            done = None
            for j in range(k, min(n, k + hold)):
                qty = sum(q for _, _, q in legs); avg = sum(p * q for _, p, q in legs) / qty
                stop = avg * (1 - 0.8 / LEV)
                if l[j] <= stop: done = (j, min(o[j], stop), "stop"); break
                if tp and h[j] >= avg * (1 + tp):               # a resting limit: a gap above it fills at the open
                    done = (j, max(o[j], avg * (1 + tp)), "target"); break
                sig = (c[j] > m5[j] if exit == "sma5" else c[j] > c[j - 1] if exit == "upclose" else c[j] > avg)
                if j + 1 < n and sig: done = (j + 1, o[j + 1], "signal"); break
                if scale and j == k and c[j] < legs[0][1] and j + 1 < n:
                    legs.append((j + 1, o[j + 1], unit / o[j + 1]))      # the second half, at the next open
            if done is None:
                j = min(n - 1, k + hold); done = (j, o[j], "time")
            j, x, why = done
            pnl = 0.0; marks = {}                                   # marks: day -> PnL of that day at its close (mark to market)
            def mark(m, v): marks[int(tss[min(m, n - 1)])] = marks.get(int(tss[min(m, n - 1)]), 0.0) + v
            for b, p, q in legs:
                if b > j: continue                                  # an add that never filled (the exit came first)
                pnl += (x - p) * q - (p + x) * q * FEE - sum(q * c[m] * f[m] for m in range(b, j))
                prev = p; mark(b, -p * q * FEE)
                for m in range(b, j):
                    mark(m, (c[m] - prev) * q - q * c[m] * f[m]); prev = c[m]
                mark(j, (x - prev) * q - x * q * FEE)
            out.append({"symbol": s, "side": "long", "entry": float(o[k]), "entry_ts": int(tss[k]), "exit_ts": int(tss[min(j, n - 1)]), "pnl": pnl, "reason": why,
                        "margin": sum(p * q for b, p, q in legs if b <= j) / LEV, "marks": marks, "days": j - k})
            i = j
    return out


def candidate(data, fund):
    """C2's trades from raw data: for research/lookahead_check.py."""
    b = data["BTCUSDT"]
    return run(ts.coin_arrays(data, fund, pm.rank_table(data, 60)), ci.btc_above(data, 200),
               dict(zip(b.ts.astype("int64"), b.close.pct_change().fillna(0.0))), exit="profit")


def stats(trades):
    t = pd.DataFrame(trades); t["d"] = pd.to_datetime(t.exit_ts, unit="ms").dt.floor("D")
    daily = t.groupby("d").pnl.sum(); daily = daily.reindex(pd.date_range("2019-09-01", daily.index.max()), fill_value=0)
    eq = daily.cumsum()
    sh = lambda x: round(float(x.mean() / x.std() * math.sqrt(365)), 2) if x.std() else 0.0
    win = lambda x: round(float((x.pnl > 0).mean() * 100), 1) if len(x) else None
    b, a = t[t.d < CUT], t[t.d >= CUT]; w, lo = t.pnl[t.pnl > 0], t.pnl[t.pnl <= 0]
    # the same book marked at every daily close: a rule that holds its losers shows them here, not only when they close
    m = pd.Series(dtype=float)
    for tr in trades:
        for k, v in tr["marks"].items(): m[k] = m.get(k, 0.0) + v
    m.index = pd.to_datetime(m.index, unit="ms").floor("D"); m = m.groupby(level=0).sum().reindex(daily.index, fill_value=0); meq = m.cumsum()
    assert abs(m.sum() - t.pnl.sum()) < 1e-6
    return {"trades": len(t), "win% <2024": win(b), "win% 2024→": win(a), "avg win $": round(float(w.mean()), 2),
            "avg loss $": round(float(lo.mean()), 2) if len(lo) else None, "worst $": round(float(t.pnl.min()), 2),
            "PF": round(float(w.sum() / -lo.sum()), 2) if len(lo) else None, "PnL $": round(float(t.pnl.sum())),
            "max DD $": round(float((eq.cummax() - eq).max())), "Sharpe <2024": sh(daily[daily.index < CUT]),
            "Sharpe 2024→": sh(daily[daily.index >= CUT]), "MTM DD $": round(float((meq.cummax() - meq).max())),
            "MTM Sh <2024": sh(m[m.index < CUT]), "MTM Sh 2024→": sh(m[m.index >= CUT]), "days held": round(float(t.days.mean()), 1),
            "timed out": int((t.reason == "time").sum()), "stops": int((t.reason == "stop").sum())}


def main():
    data = pickle.loads((ci.CACHE / "universe_daily.pkl").read_bytes())
    fund_raw = pickle.loads((ci.CACHE / "universe_funding.pkl").read_bytes())
    A = ts.coin_arrays(data, {s: fund_raw.get(s, {}) for s in data}, pm.rank_table(data, 60))
    btc200 = ci.btc_above(data, 200)
    b = data["BTCUSDT"]; btc_ret = dict(zip(b.ts.astype("int64"), b.close.pct_change().fillna(0.0)))
    # the first row must be §28's candidate, trade for trade
    ref = ci.run_rsi2(A, {200: btc200}, 5, "sma5", 1, TOP); mine = run(A, btc200, btc_ret)
    assert len(ref) == len(mine) and abs(sum(t["pnl"] for t in ref) - sum(t["pnl"] for t in mine)) < 1e-6, "baseline differs from §28"
    variants = NEIGHBORS if "--neighbors" in sys.argv else VARIANTS
    rows = {name: stats(run(A, btc200, btc_ret, **kw)) for name, kw in variants.items()}
    base = rows["A  today"]
    for name, r in rows.items():
        r["rule"] = "—" if r is base else "✓" if (r["trades"] >= MIN_TRADES and r["win% <2024"] > base["win% <2024"] and r["win% 2024→"] > base["win% 2024→"]
                                                 and r["Sharpe <2024"] >= base["Sharpe <2024"] and r["Sharpe 2024→"] >= base["Sharpe 2024→"]) else "✗"
        r["rule MTM"] = "—" if r is base else "✓" if (r["rule"] == "✓" and r["MTM Sh <2024"] >= base["MTM Sh <2024"] and r["MTM Sh 2024→"] >= base["MTM Sh 2024→"]) else "✗"
    pd.set_option("display.width", 260); pd.set_option("display.max_columns", 30)
    print(f"RSI-2 + BTC filter, top {TOP}, ${AMOUNT} x{LEV}; rule: win% above A in both periods and Sharpe not below A in both\n")
    print(pd.DataFrame(rows).T.to_string())
    if "--years" in sys.argv:
        yr = {}
        for name in ("A  today", "C2 out on the first close above entry", "F3 close above entry + two halves"):
            t = pd.DataFrame(run(A, btc200, btc_ret, **VARIANTS[name])); y = pd.to_datetime(t.exit_ts, unit="ms").dt.year
            yr[name] = t.groupby(y).pnl.agg(lambda x: f"{x.sum():+.0f} ({(x > 0).mean() * 100:.0f}% of {len(x)})")
        print("\nPnL $ by year (win % of trades)\n" + pd.DataFrame(yr).to_string())


if __name__ == "__main__":
    main()
