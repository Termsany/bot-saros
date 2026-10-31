"""
momentum_ls exits (owner, 2026-10-31): would a take-profit, a trailing stop or a break-even stop keep more of the
big weekly winners than the current rule (weekly rebalance, 40% stop)? Same trades as the bot and the baseline
(pump_momentum_study.momentum_positions: top 50 by volume, 2-week return, 5 long + 5 short, every 7 days), every
Binance USDT-M perpetual since 2019 (delisted included), fees 0.04% and real funding, $20 margin x2.

Daily candles only, read conservatively: a day's trailing level comes from the extreme up to the day before, and
when a stop and a take-profit both fall inside one day the stop is taken. A live bot polling every minute would
trail tighter than this, for better and for worse.

Result (2026-10-31, 3,420 trades to 2026-10-30): no exit beats the current rule by a margin worth a change. Net in
trades' margins, all (since 2024): current +91 (+58); take-profits +65 / +67 / +87; trailing from day one +59 / +55 /
+79; trailing 25% armed after +25% +94 (+65), the best; break-even after +25% +90 (+62). The top 10% of trades make
3.9x the whole net profit, so any rule that closes early cuts exactly the trades that pay. Kept as is.

  python research/universe_data.py             # once: research/.cache/universe_daily.pkl
  python research/momentum_trailing_study.py    # downloads the missing funding windows first
"""
import sys, pickle
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pump_momentum_study as pm
import strategies_trend as st

CACHE, AMOUNT, LEV, FEE, DAY = pm.CACHE, pm.AMOUNT, pm.LEV, pm.FEE, pm.DAY
OOS = pd.Timestamp("2024-01-01")

# (label, take-profit, trail, trail armed after, break-even after) — price moves; x2 leverage doubles them on margin
VARIANTS = [
    ("الحالي: تبديل أسبوعي + وقف 40%", None, None, 0.0, None),
    ("هدف ربح +25% سعر (+50% مارجن)", 0.25, None, 0.0, None),
    ("هدف ربح +50% سعر (+100% مارجن)", 0.50, None, 0.0, None),
    ("هدف ربح +75% سعر (+150% مارجن)", 0.75, None, 0.0, None),
    ("وقف متحرك 15% من القمة", None, 0.15, 0.0, None),
    ("وقف متحرك 25% من القمة", None, 0.25, 0.0, None),
    ("وقف متحرك 35% من القمة", None, 0.35, 0.0, None),
    ("وقف متحرك 15% بعد +25% ربح", None, 0.15, 0.25, None),
    ("وقف متحرك 25% بعد +25% ربح", None, 0.25, 0.25, None),
    ("وقف على الدخول بعد +25% ربح", None, None, 0.0, 0.25),
]


def trade(df, fund, d, side, tp=None, trail=None, arm=0.0, be=None):
    """pump_momentum_study.momentum_trade with optional exits; with none of them it is the same trade."""
    idx = pd.to_datetime(df.ts, unit="ms"); k = idx.searchsorted(d) + 1
    if k >= len(df): return None
    o, h, l, c, ts = df.open.values, df.high.values, df.low.values, df.close.values, df.ts.values
    sg = 1 if side == "long" else -1
    e = o[k]; q = AMOUNT * LEV / e; stop = e * (1 - sg * st.STOP_SHARE / LEV); fu = 0.0
    best = e                                     # highest high (long) / lowest low (short) up to the day before
    target = e * (1 + sg * tp) if tp else None
    done = lambda j, x, why: dict(entry_ts=int(ts[k]), exit_ts=int(ts[j]), side=side, entry=e, exit=x, qty=q, reason=why,
                                  pnl=sg * (x - e) * q - (e * q + x * q) * FEE + fu)
    for j in range(k, min(len(df), k + 7)):
        gain = sg * (best - e) / e
        level, why = stop, "stop"
        if trail and gain >= arm:
            t = best * (1 - sg * trail)
            if sg * (t - level) > 0: level, why = t, "trail"
        if be is not None and gain >= be and sg * (e - level) > 0: level, why = e, "breakeven"
        if target is not None and sg * (o[j] - target) >= 0: return done(j, o[j], "tp")          # opened past the target
        if (sg == 1 and l[j] <= level) or (sg == -1 and h[j] >= level):
            return done(j, min(o[j], level) if sg == 1 else max(o[j], level), why)
        if target is not None and ((sg == 1 and h[j] >= target) or (sg == -1 and l[j] <= target)):
            return done(j, target, "tp")
        fu += -sg * q * c[j] * fund.get(int(ts[j]), 0.0)
        best = max(best, h[j]) if sg == 1 else min(best, l[j])
    j = k + 7
    x, t = (o[j], ts[j]) if j < len(df) else (c[-1], ts[-1])
    return dict(entry_ts=int(ts[k]), exit_ts=int(t), side=side, entry=e, exit=x, qty=q, reason="week",
                pnl=sg * (x - e) * q - (e * q + x * q) * FEE + fu)


def stats(trades):
    t = pd.DataFrame(trades); t["exit_d"] = pd.to_datetime(t.exit_ts, unit="ms")
    out = {}
    for name, part in (("all", t), ("oos", t[t.exit_d >= OOS])):
        r = part.pnl / AMOUNT * 100
        daily = part.groupby(part.exit_d.dt.floor("D")).pnl.sum().sort_index().cumsum()
        out[name] = {"n": len(part), "win": (r > 0).mean() * 100, "avg_win": r[r > 0].mean(), "avg_loss": r[r <= 0].mean(),
                     "pf": part.pnl[part.pnl > 0].sum() / -part.pnl[part.pnl <= 0].sum(),
                     "net": part.pnl.sum() / AMOUNT, "dd": (daily.cummax() - daily).max() / AMOUNT,
                     "top10": part.pnl.nlargest(max(1, len(part) // 10)).sum() / part.pnl.sum() * 100 if part.pnl.sum() > 0 else float("nan")}
    return out


def main():
    data = pickle.loads((CACHE / "universe_daily.pkl").read_bytes())
    fpath = CACHE / "universe_funding.pkl"
    fund_raw = pickle.loads(fpath.read_bytes()) if fpath.exists() else {}
    positions = pm.momentum_positions(data, pm.rank_table(data, 60), 2, True)
    windows = {}
    for s, d, _ in positions:
        t0 = int(d.value // 10**6); windows.setdefault(s, []).append((t0, t0 + 9 * DAY))
    pm.fetch_windows(windows, fund_raw)
    fund = {s: fund_raw.get(s, {}) for s in data}

    base = [x for s, d, side in positions if (x := pm.momentum_trade(data[s], fund[s], d, side))]
    rows = []
    for label, tp, trail, arm, be in VARIANTS:
        tr = [x for s, d, side in positions if (x := trade(data[s], fund[s], d, side, tp, trail, arm, be))]
        if (tp, trail, be) == (None, None, None):
            assert [round(x["pnl"], 9) for x in tr] == [round(x["pnl"], 9) for x in base], "current variant != the bot's backtest"
        rows.append((label, stats(tr)))

    print("| المخرج | صفقات | نسبة الكسب | متوسط الكسب | متوسط الخسارة | PF (من 2024) | صافي بالمارجن (من 2024) | أسوأ تراجع | أكبر 10% صفقات من الربح |")
    print("|---|---|---|---|---|---|---|---|---|")
    for label, r in rows:
        a, o = r["all"], r["oos"]
        print(f"| {label} | {a['n']} | {a['win']:.1f}% | +{a['avg_win']:.1f}% | {a['avg_loss']:.1f}% | {a['pf']:.2f} ({o['pf']:.2f}) "
              f"| {a['net']:+.0f} ({o['net']:+.0f}) | {a['dd']:.1f} | {a['top10']:.0f}% |")


if __name__ == "__main__":
    main()
