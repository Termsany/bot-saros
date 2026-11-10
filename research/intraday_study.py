"""
5–15 minute strategies with real costs (owner, 2026-11-07: "isn't there a scientific bot that trades 5–15 minutes?").

Three families from the literature, every variant fixed before any result:
  A. 15m Bollinger reversal (short-term reversal; Lehmann 1990, Jegadeesh 1990; crypto: Wen et al. 2022) — a limit
     order at the signal close (maker fee, filled only if the next bar trades through it), out at the moving average
     or a time stop (taker).
  B. 15m channel breakout (intraday time-series momentum; Gao et al. 2018) — taker in, trailing ATR stop or a time cap.
  C. 5m shock reversal (liquidity-shock reversal; Nagel 2012) — a limit order after a k-sigma 5m move, out after H bars.

Universe: each day, the coins in the top 10 by 30-day USDT volume the day before (delisted included, as
research/hourly_study.py). Every trade $100 notional. Costs: taker 0.05% + 0.02% slippage a side, maker 0.02%.
Funding left out (holds of minutes to hours). The in-sample pick is the best Sharpe before 2024; it is judged after.

  RAQM_RESEARCH_CACHE=/opt/raqm-data/research python research/intraday_study.py     # needs research/m5_data.py
"""
import json, os, pickle, sys, time
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m5_data import ranks, CACHE

TAKER, MAKER = 0.0005 + 0.0002, 0.0002
NOTIONAL, CUT, TOP = 100.0, pd.Timestamp("2024-01-01"), 10
DAY = 86_400_000

A = [("A", L, k, H) for L in (20, 48) for k in (2.0, 2.5, 3.0) for H in (4, 16)]
B = [("B", N, k, cap) for N in (16, 96) for k in (2.0, 4.0) for cap in (1, 4)]          # cap in multiples of N bars
C = [("C", 288, k, H) for k in (4.0, 6.0) for H in (3, 12)]
VARIANTS = A + B + C


def name(v):
    f, a, b, c = v
    return {"A": f"A 15m reversal L{a} k{b} H{c}", "B": f"B 15m breakout N{a} ATRx{b} cap{c}N",
            "C": f"C 5m shock k{b} H{c}"}[f]


def to15(d):
    g = d.ts // 900_000
    o = d.groupby(g).agg(ts=("ts", "first"), open=("open", "first"), high=("high", "max"), low=("low", "min"),
                         close=("close", "last"), n=("ts", "size"))
    return o[o.n == 3].reset_index(drop=True)


def cols(df, *names):
    return tuple(df[x].to_numpy(np.float64) for x in names) + (df.ts.to_numpy(),)


def rolling_mean(x, n):
    c = np.cumsum(np.insert(x, 0, 0.0)); m = np.full(len(x), np.nan)
    m[n - 1:] = (c[n:] - c[:-n]) / n; return m


def rolling_std(x, n):
    m = rolling_mean(x, n); m2 = rolling_mean(x * x, n)
    return np.sqrt(np.maximum(m2 - m * m, 0))


def trade(sym, side, ets, xts, entry, exit_, fee_in, fee_out):
    gross = side * (exit_ / entry - 1)
    return (sym, ets, xts, side, gross, gross - fee_in - fee_out)


def run_A(sym, b, ok, L, k, H):
    o, h, l, c, ts = cols(b, "open", "high", "low", "close")
    sma, sd = rolling_mean(c, L), rolling_std(c, L)
    z = (c - sma) / np.where(sd > 0, sd, np.nan)
    sig = np.where(ok & (z <= -k), 1, np.where(ok & (z >= k), -1, 0))
    out, i, n = [], 0, len(c)
    cand = np.flatnonzero(sig[:-1])
    while True:
        j = np.searchsorted(cand, i)
        if j >= len(cand): break
        t = cand[j]; s = sig[t]; e = t + 1; lim = c[t]
        if not ((s == 1 and l[e] < lim) or (s == -1 and h[e] > lim)):
            i = t + 1; continue
        end = min(e + H - 1, n - 1)
        seg = c[e:end + 1] - sma[e:end + 1]
        hit = np.flatnonzero(seg >= 0 if s == 1 else seg <= 0)
        x = e + (hit[0] if len(hit) else end - e)
        out.append(trade(sym, s, ts[e], ts[x], lim, c[x], MAKER, TAKER)); i = x + 1
    return out


def run_B(sym, b, ok, N, k, cap):
    o, h, l, c, ts = cols(b, "open", "high", "low", "close")
    hi = pd.Series(h).rolling(N).max().shift(1).to_numpy(); lo = pd.Series(l).rolling(N).min().shift(1).to_numpy()
    pc = np.insert(c[:-1], 0, c[0]); tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    atr = pd.Series(tr).rolling(N).mean().to_numpy()
    sig = np.where(ok & (c > hi), 1, np.where(ok & (c < lo), -1, 0))
    out, i, n, hold = [], 0, len(c), cap * N
    cand = np.flatnonzero(sig[:-1])
    while True:
        j = np.searchsorted(cand, i)
        if j >= len(cand): break
        t = cand[j]; s = sig[t]; e = t + 1
        if not np.isfinite(atr[t]): i = t + 1; continue
        end = min(e + hold - 1, n - 1); dist = k * atr[t]
        if s == 1:
            best = np.maximum.accumulate(np.insert(h[e:end], 0, o[e]))          # high up to the previous bar
            stop = best - dist; hit = np.flatnonzero(l[e:end + 1] <= stop)
            px = (min(o[e + hit[0]], stop[hit[0]]) if len(hit) else c[end])
        else:
            best = np.minimum.accumulate(np.insert(l[e:end], 0, o[e]))
            stop = best + dist; hit = np.flatnonzero(h[e:end + 1] >= stop)
            px = (max(o[e + hit[0]], stop[hit[0]]) if len(hit) else c[end])
        x = e + hit[0] if len(hit) else end
        out.append(trade(sym, s, ts[e], ts[x], o[e], px, TAKER, TAKER)); i = x + 1
    return out


def run_C(sym, d, ok, W, k, H):
    h, l, c, ts = cols(d, "high", "low", "close")
    r = np.insert(c[1:] / c[:-1] - 1, 0, 0.0)
    sd = np.insert(rolling_std(r, W)[:-1], 0, np.nan)                      # the sigma before this bar
    sig = np.where(ok & (r <= -k * sd), 1, np.where(ok & (r >= k * sd), -1, 0))
    out, i, n = [], 0, len(c)
    cand = np.flatnonzero(sig[:-1])
    while True:
        j = np.searchsorted(cand, i)
        if j >= len(cand): break
        t = cand[j]; s = sig[t]; e = t + 1; lim = c[t]
        if not ((s == 1 and l[e] < lim) or (s == -1 and h[e] > lim)):
            i = t + 1; continue
        x = min(e + H - 1, n - 1)
        out.append(trade(sym, s, ts[e], ts[x], lim, c[x], MAKER, TAKER)); i = x + 1
    return out


def stats(t):
    if not len(t): return None
    t = t.assign(pnl=t.net * NOTIONAL, day=pd.to_datetime(t.xts, unit="ms").dt.floor("D"))
    def part(p):
        if not len(p): return {"trades": 0, "pnl": 0.0, "sharpe": 0.0}
        dd = p.groupby("day").pnl.sum()
        dd = dd.reindex(pd.date_range(dd.index.min(), dd.index.max()), fill_value=0)
        return {"trades": int(len(p)), "pnl": round(float(p.pnl.sum()), 1),
                "sharpe": round(float(dd.mean() / dd.std() * np.sqrt(365)) if dd.std() > 0 else 0.0, 2)}
    eq = t.sort_values("xts").pnl.cumsum()
    return {"trades": int(len(t)), "win": round(float((t.net > 0).mean() * 100), 1),
            "gross_bps": round(float(t.gross.mean() * 1e4), 2), "net_bps": round(float(t.net.mean() * 1e4), 2),
            "pnl": round(float(t.pnl.sum()), 1), "max_dd": round(float((eq.cummax() - eq).max()), 1),
            "before": part(t[t.day < CUT]), "after": part(t[t.day >= CUT])}


def main():
    t0 = time.time()
    daily = pickle.loads((CACHE / "universe_daily.pkl").read_bytes())
    member = (ranks(daily) <= TOP).shift(1, fill_value=False)                # yesterday's top 10
    days = pd.DatetimeIndex(member.index).as_unit("ms").asi8
    trades = {v: [] for v in VARIANTS}
    files = sorted((CACHE / "m5").glob("*.pkl"))
    for n, p in enumerate(files):
        sym = p.stem
        if sym not in member: continue
        d = pickle.loads(p.read_bytes()).reset_index(drop=True)
        mem = member[sym].to_numpy()
        def ok_of(ts):
            idx = np.searchsorted(days, (ts // DAY) * DAY)
            idx = np.clip(idx, 0, len(days) - 1)
            return mem[idx] & (days[idx] == (ts // DAY) * DAY)
        ok5 = ok_of(d.ts.to_numpy())
        if not ok5.any(): continue
        b = to15(d); ok15 = ok_of(b.ts.to_numpy())
        for v in VARIANTS:
            f = v[0]
            if f == "A": trades[v] += run_A(sym, b, ok15, *v[1:])
            elif f == "B": trades[v] += run_B(sym, b, ok15, *v[1:])
            else: trades[v] += run_C(sym, d, ok5, *v[1:])
        print(f"  {n + 1}/{len(files)} {sym} {time.time() - t0:.0f}s", flush=True)
    cols = ["sym", "ets", "xts", "side", "gross", "net"]
    res = {name(v): stats(pd.DataFrame(trades[v], columns=cols)) for v in VARIANTS}
    for fam in "ABC":
        print(f"\n{fam}: variant | trades | win% | gross bps | net bps | PnL | maxDD | Sharpe<2024 | Sharpe 2024-> | PnL 2024->")
        for k_, r in res.items():
            if not k_.startswith(fam) or not r: continue
            print(f"{k_} | {r['trades']} | {r['win']} | {r['gross_bps']} | {r['net_bps']} | {r['pnl']} | {r['max_dd']} | "
                  f"{r['before']['sharpe']} | {r['after']['sharpe']} | {r['after']['pnl']}")
    ok = {k_: r for k_, r in res.items() if r and r["before"]["trades"] >= 100}
    pick = max(ok, key=lambda k_: ok[k_]["before"]["sharpe"])
    pos = sum(1 for r in ok.values() if r["after"]["pnl"] > 0)
    print(f"\nin-sample pick: {pick} -> Sharpe after 2024 {ok[pick]['after']['sharpe']}, PnL {ok[pick]['after']['pnl']}")
    print(f"variants positive after 2024: {pos} / {len(ok)}")
    Path("intraday_results.json").write_text(json.dumps({"variants": res, "pick": pick}, indent=1))
    print(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
