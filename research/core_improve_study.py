"""
Can the daily trend, momentum_ls and RSI-2 bots win more? (owner, 2026-11-07: "research and improve them so the
win rate is higher than now"). Ideas not tried in §8-10, §22-23 or the traders study, every variant fixed before
any result; the first variant of each bot is the rule the bot runs today (its baseline).

Daily trend (bot: on when the close is above the closes 20/60/120 days ago for 2 of 3; top 10 by volume):
  - entry rule: 2 of 3 (now) / 3 of 3 (fewer whipsaws — Moskowitz, Ooi & Pedersen 2012 use the full horizon)
  - market filter: none / BTC above its 100-day / 200-day average (crypto market factor, Liu & Tsyvinski 2021)
  - a 30% trailing stop from the best high, then wait for the trend to switch off and on again
momentum_ls (bot: every 7 days, top 50 by volume, long the 5 strongest / short the 5 weakest 2-week returns):
  - ranking: 2-week return (now) / skipping the last day (short-term reversal; Jegadeesh & Titman 1993) /
    a 1-2-4 week composite (Han, Kang & Ryu 2023) / 2-week return over its volatility (risk-adjusted momentum)
  - market filter: none / no shorts while BTC is above its 200-day average (momentum crashes; Daniel & Moskowitz 2016)
RSI-2 (bot: top 10, BTC-free, close above its 200-day average, RSI-2 below 5, out above the 5-day average):
  - threshold 5 (now) / 10; exit above the 5-day average (now) / at the first close above the previous high
  - BTC above its 200-day average or not; top 10 (now) / top 20

$20 margin x2 per trade, fees 0.04% a side, real per-coin funding, the 40% guard stop (as baseline_stats.py).
Each bot's in-sample pick is its best Sharpe before 2024 (at least 60 trades); after 2024 is the test.

  RAQM_RESEARCH_CACHE=/opt/raqm-data/research python research/core_improve_study.py
"""
import itertools, math, os, pickle, sys
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import strategies_trend as st
import pump_momentum_study as pm
import traders_study as ts
from universe_study import ranks

CACHE = Path(os.getenv("RAQM_RESEARCH_CACHE") or Path(__file__).resolve().parent / ".cache")
AMOUNT, LEV, FEE, CUT, MIN_TRADES = 20, 2, 0.0004, pd.Timestamp("2024-01-01"), 60


def btc_above(data, n):
    """day timestamp (ms) -> BTC close above its n-day average at that close."""
    b = data["BTCUSDT"]; m = b.close.rolling(n).mean()
    return dict(zip(b.ts.astype("int64"), (b.close > m) & m.notna()))


# ── daily trend ──
def trend_trades(o, h, l, c, ts_, fu, allowed, need, trail):
    n, out, pos, pending, wait_off = len(c), [], None, None, False
    for i in range(n):
        if pending == "buy":
            q = AMOUNT * LEV * size / o[i]
            pos = dict(entry=o[i], qty=q, ts=ts_[i], funding=0.0, stop=o[i] * (1 - st.STOP_SHARE / LEV), peak=o[i])
        elif pending == "sell" and pos:
            out.append(st._close(pos, o[i], ts_[i], "signal off", FEE)); pos = None
        pending = None
        if pos:
            stop = pos["stop"] if not trail else max(pos["stop"], pos["peak"] * (1 - trail))
            if l[i] <= stop:
                out.append(st._close(pos, min(o[i], stop), ts_[i], "stop", FEE)); pos = None; wait_off = bool(trail)
            else:
                pos["funding"] += pos["qty"] * c[i] * fu[i]; pos["peak"] = max(pos["peak"], h[i])
        if i + 1 < n and i >= max(st.LOOKBACKS):
            votes = sum(c[i] > c[i - L] for L in st.LOOKBACKS)
            on = votes >= need
            if not (votes >= 2): wait_off = False                   # the trend switched off: a new entry may come
            if pos is None and on and not wait_off and allowed[i]:
                pending, size = "buy", st.size_factor(c, i)
            elif pos is not None and votes < 2:                     # the exit stays the bot's: off below 2 of 3
                pending = "sell"
    if pos: out.append(st._close(pos, c[-1], ts_[-1], "close", FEE))
    return out


def run_trend(data, fund, rk10, ever10, btc, need, mkt, trail):
    out = []
    for s in ever10:
        df = data[s]; tsv = df.ts.astype("int64").to_numpy()
        top = (rk10[s].reindex(pd.to_datetime(df.ts, unit="ms")) <= 10).fillna(False).to_numpy()
        ok = top & np.array([btc[mkt].get(int(t), False) for t in tsv]) if mkt else top
        if not ok.any(): continue
        fu = [fund[s].get(int(t), 0.0) for t in tsv]
        out += [dict(t, symbol=s) for t in trend_trades(df.open.to_numpy(float), df.high.to_numpy(float), df.low.to_numpy(float),
                                                         df.close.to_numpy(float), tsv, fu, ok, need, trail)]
    return out


# ── momentum ──
def run_momentum(data, fund, rk, btc, how, regime):
    closes = pd.DataFrame({s: df.set_index(pd.to_datetime(df.ts, unit="ms")).close for s, df in data.items()})
    if how == "2w": score = closes / closes.shift(14) - 1
    elif how == "skip1": score = closes.shift(1) / closes.shift(15) - 1
    elif how == "composite":
        score = sum((closes / closes.shift(7 * w) - 1).rank(axis=1, pct=True) for w in (1, 2, 4)) / 3
    else:
        vol = closes.pct_change().rolling(14).std()
        score = (closes / closes.shift(14) - 1) / vol
    out = []
    for d in closes.index[7 * 2 + 30::7]:
        if d not in rk.index: continue
        r = rk.loc[d]; p = score.loc[d, r[r <= 50].index].dropna()
        if len(p) < 20: continue
        p = p.sort_values()
        sides = [(x, "long") for x in p.index[-5:]]
        bull = btc[200].get(int(d.value // 1_000_000), False)
        if not (regime and bull): sides += [(x, "short") for x in p.index[:5]]
        out += [dict(t, symbol=x) for x, side in sides if (t := pm.momentum_trade(data[x], fund[x], d, side))]
    return out


# ── RSI-2 ──
def run_rsi2(A, btc, T, exit_rule, mkt, top):
    out = []
    for s, a in A.items():
        o, h, l, c = a["o"], a["h"], a["l"], a["c"]; n = len(c)
        if n < 210: continue
        r2, m5, m200 = ts.rsi(c, 2), ts.sma(c, 5), ts.sma(c, 200)
        bt = np.array([btc[200].get(int(t), False) for t in a["ts"]]) if mkt else None
        i = 200
        while i < n - 2:
            ok = a["rk"][i + 1] <= top and r2[i] < T and c[i] > m200[i] and (bt is None or bt[i])
            if not ok: i += 1; continue
            k = i + 1; e = o[k]; stop = e * (1 - 0.8 / LEV); done = None
            for j in range(k, min(n, k + 10)):
                if l[j] <= stop: done = (j, min(o[j], stop), "stop"); break
                sig = c[j] > m5[j] if exit_rule == "sma5" else (j > 0 and c[j] > h[j - 1])
                if j + 1 < n and sig: done = (j + 1, o[j + 1], "signal"); break
            if done is None:
                j = min(n - 1, k + 10); done = (j, o[j], "time")
            j, x, why = done
            out.append(ts.long_trade(a, k, e, j, x, why, s)); i = j
    return out


def summary(trades):
    t = pd.DataFrame(trades)
    if not len(t): return None
    t["d"] = pd.to_datetime(t.exit_ts, unit="ms").dt.floor("D")
    daily = t.groupby("d").pnl.sum(); daily = daily.reindex(pd.date_range("2019-09-01", daily.index.max()), fill_value=0)
    eq = daily.cumsum()
    def sh(x): return round(float(x.mean() / x.std() * math.sqrt(365)), 2) if x.std() else 0.0
    def pf(p): return round(float(p[p > 0].sum() / -p[p <= 0].sum()), 2) if (p <= 0).any() else None
    a = t[t.d >= CUT]
    return {"trades": len(t), "win": round(float((t.pnl > 0).mean() * 100), 1), "win_after": round(float((a.pnl > 0).mean() * 100), 1) if len(a) else None,
            "pf": pf(t.pnl), "pf_after": pf(a.pnl), "pnl": round(float(t.pnl.sum())), "max_dd": round(float((eq.cummax() - eq).max())),
            "is": sh(daily[daily.index < CUT]), "oos": sh(daily[daily.index >= CUT]), "pnl_after": round(float(a.pnl.sum()))}


def report(bot, rows):
    print(f"\n=== {bot}: {len(rows)} variants (first = the bot today) ===")
    print("variant | trades | win% | win% 2024-> | PF | PF 2024-> | PnL | maxDD | Sharpe<2024 | Sharpe 2024-> | PnL 2024->")
    for k, r in rows.items():
        print(f"{k} | {r['trades']} | {r['win']} | {r['win_after']} | {r['pf']} | {r['pf_after']} | {r['pnl']} | {r['max_dd']} | {r['is']} | {r['oos']} | {r['pnl_after']}")
    base = next(iter(rows.values()))
    ok = {k: r for k, r in rows.items() if r["trades"] >= MIN_TRADES}
    pick = max(ok, key=lambda k: ok[k]["is"])
    better = [k for k, r in ok.items() if r["oos"] > base["oos"]]
    print(f"in-sample pick: {pick}  Sharpe after 2024 {ok[pick]['oos']} vs now {base['oos']}; win% after {ok[pick]['win_after']} vs {base['win_after']}")
    print(f"variants beating today's rule after 2024 (Sharpe): {len(better)} / {len(ok) - 1}")


def main():
    data = pickle.loads((CACHE / "universe_daily.pkl").read_bytes())
    fund_raw = pickle.loads((CACHE / "universe_funding.pkl").read_bytes())
    fund = {s: fund_raw.get(s, {}) for s in data}
    btc = {100: btc_above(data, 100), 200: btc_above(data, 200)}
    rk10 = ranks(data); ever10 = [s for s in data if (rk10[s] <= 10).any()]

    rows = {}
    for need, mkt, trail in itertools.product((2, 3), (0, 100, 200), (0, 0.30)):
        rows[f"trend {need}of3 btc{mkt or '-'} trail{int(trail * 100) or '-'}"] = summary(run_trend(data, fund, rk10, ever10, btc, need, mkt, trail))
    report("daily trend", rows)

    rk60 = pm.rank_table(data, 60)
    rows = {}
    for how, regime in itertools.product(("2w", "skip1", "composite", "voladj"), (0, 1)):
        rows[f"momentum {how} {'no-shorts-in-bull' if regime else 'both'}"] = summary(run_momentum(data, fund, rk60, btc, how, regime))
    report("momentum_ls", rows)

    A = ts.coin_arrays(data, fund, rk60)
    rows = {}
    for top, T, ex, mkt in itertools.product((10, 20), (5, 10), ("sma5", "prevhigh"), (0, 1)):
        rows[f"rsi2 top{top} <{T} {ex} btc{'200' if mkt else '-'}"] = summary(run_rsi2(A, btc, T, ex, mkt, top))
    report("RSI-2", rows)


if __name__ == "__main__":
    main()
