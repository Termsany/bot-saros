"""
momentum_ls: filter out the coins that went too far before they enter the basket (owner, 2026-11-09: "some coins have
risen so much that the bot goes long and they hit the stop, and the reverse for the shorts").

The bot today: every 7 days, among the top 50 by 30-day volume, long the 5 strongest and short the 5 weakest 2-week
returns, a week's hold, the 40% guard stop. Each filter below drops a candidate that looks overextended at the ranking
close (nothing after it is used) and takes the next one in the ranking instead, so the basket stays 5 + 5. All
variants were fixed before any result; the first is the rule the bot runs today and must match §28's baseline.

  cap        the 2-week return itself: no long above +X, no short below -Y (a pump or a crash already priced in)
  skip       the k most extreme of each side left out (ranks k+1..k+5)
  day        the last day's move: no long after a day up more than 15%, no short after a day down more than 15%
             (blow-off top / capitulation; the 1-day reversal effect)
  ma20       distance from the 20-day average: no long more than X above it, no short more than Y below it
  vol        no coin in the most volatile 20% of the pool (14-day daily volatility)
  ma50       trend agreement: long only above the 50-day average, short only below it

$20 margin x2 per trade, fees 0.04% a side, real per-coin funding (core_improve_study / pump_momentum_study
simulators). The in-sample pick is the best Sharpe before 2024 (at least 60 trades); after 2024 is the test.

  RAQM_RESEARCH_CACHE=/opt/raqm-data/research python research/momentum_filter_study.py
"""
import math, os, pickle, sys
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import pump_momentum_study as pm
from core_improve_study import summary, MIN_TRADES

CACHE = Path(os.getenv("RAQM_RESEARCH_CACHE") or Path(__file__).resolve().parent / ".cache")
N, TOP, POOL_MIN = 5, 50, 20

VARIANTS = {
    "today (no filter)": None,
    "cap long>+100% short<-50%": ("cap", 1.00, 0.50),
    "cap long>+200% short<-66%": ("cap", 2.00, 0.66),
    "skip 1 most extreme": ("skip", 1),
    "skip 2 most extreme": ("skip", 2),
    "day move >15%": ("day", 0.15),
    "ma20 long>+30% short<-25%": ("ma20", 0.30, 0.25),
    "ma20 long>+60% short<-40%": ("ma20", 0.60, 0.40),
    "vol top 20% out": ("vol", 0.80),
    "ma50 trend agreement": ("ma50",),
}


def frames(data):
    closes = pd.DataFrame({s: df.set_index(pd.to_datetime(df.ts, unit="ms")).close for s, df in data.items()})
    return {"close": closes, "score": closes / closes.shift(14) - 1, "day": closes.pct_change(),
            "ma20": closes / closes.rolling(20).mean() - 1, "ma50": closes / closes.rolling(50).mean() - 1,
            "vol": closes.pct_change().rolling(14).std()}


def allowed(f, rule, d, pool):
    """{symbol: (long ok, short ok)} for the pool at the ranking close d."""
    sc = f["score"].loc[d, pool]
    if rule is None or rule[0] == "skip":
        return {s: (True, True) for s in pool}
    kind = rule[0]
    if kind == "cap":
        return {s: (sc[s] <= rule[1], sc[s] >= -rule[2]) for s in pool}
    if kind == "day":
        x = f["day"].loc[d, pool]
        return {s: (not x[s] > rule[1], not x[s] < -rule[1]) for s in pool}
    if kind == "ma20":
        x = f["ma20"].loc[d, pool]
        return {s: (not x[s] > rule[1], not x[s] < -rule[2]) for s in pool}
    if kind == "vol":
        x = f["vol"].loc[d, pool]; cut = x.quantile(rule[1])
        return {s: (not x[s] > cut, not x[s] > cut) for s in pool}
    if kind == "ma50":
        x = f["ma50"].loc[d, pool]
        return {s: (x[s] > 0, x[s] < 0) for s in pool}
    raise ValueError(kind)


def basket(f, rule, d, pool):
    """[(symbol, side)]: 5 longs from the strongest down, 5 shorts from the weakest up, skipping what the rule drops."""
    p = f["score"].loc[d, pool].dropna().sort_values()
    if len(p) < POOL_MIN:
        return []
    ok = allowed(f, rule, d, list(p.index))
    skip = rule[1] if rule and rule[0] == "skip" else 0
    longs = [s for s in reversed(p.index) if ok[s][0]][skip:skip + N]
    shorts = [s for s in p.index if ok[s][1] and s not in longs][skip:skip + N]
    return [(s, "long") for s in longs] + [(s, "short") for s in shorts]


def run(data, fund, rk, f, rule):
    out = []
    for d in f["close"].index[7 * 2 + 30::7]:
        if d not in rk.index: continue
        r = rk.loc[d]; pool = [s for s in r[r <= TOP].index if s in f["score"].columns]
        for x, side in basket(f, rule, d, pool):
            t = pm.momentum_trade(data[x], fund[x], d, side)
            if t: out.append(dict(t, symbol=x))
    return out


def main():
    data = pickle.loads((CACHE / "universe_daily.pkl").read_bytes())
    fund_raw = pickle.loads((CACHE / "universe_funding.pkl").read_bytes())
    fund = {s: fund_raw.get(s, {}) for s in data}
    rk = pm.rank_table(data, 60); f = frames(data)

    rows = {}
    print("variant | trades | win% | win% 2024-> | stops% | stops% 2024-> | PF | PF 2024-> | PnL | maxDD | Sharpe<2024 | Sharpe 2024-> | PnL 2024-> | long PnL | short PnL")
    for name, rule in VARIANTS.items():
        tr = run(data, fund, rk, f, rule); s = summary(tr); rows[name] = s
        t = pd.DataFrame(tr); a = t[pd.to_datetime(t.exit_ts, unit="ms") >= pd.Timestamp("2024-01-01")]
        stops = round(float((t.reason == "stop").mean() * 100), 1); stops_a = round(float((a.reason == "stop").mean() * 100), 1)
        lp, sp = round(float(t[t.side == "long"].pnl.sum())), round(float(t[t.side == "short"].pnl.sum()))
        print(f"{name} | {s['trades']} | {s['win']} | {s['win_after']} | {stops} | {stops_a} | {s['pf']} | {s['pf_after']} | {s['pnl']} | "
              f"{s['max_dd']} | {s['is']} | {s['oos']} | {s['pnl_after']} | {lp} | {sp}")
    base = rows["today (no filter)"]
    ok = {k: r for k, r in rows.items() if r["trades"] >= MIN_TRADES}
    pick = max(ok, key=lambda k: ok[k]["is"])
    better = [k for k, r in ok.items() if k != "today (no filter)" and r["oos"] > base["oos"] and r["is"] > base["is"]]
    print(f"\nin-sample pick: {pick} — Sharpe after 2024 {ok[pick]['oos']} vs today {base['oos']}")
    print(f"better than today in BOTH periods: {better or 'none'}")


if __name__ == "__main__":
    main()
