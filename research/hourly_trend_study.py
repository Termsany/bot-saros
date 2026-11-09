"""
Hourly strategies that hold for hours to days, so a trade's move is much bigger than its costs (owner, 2026-11-07:
"design a strategy on the hourly frame, profitable, and flexible from $200 to $10,000").

The 5-15 minute study (§26) and the first hourly study (§16-18) lost because their moves were a few basis points.
These three hold longer and trade with the daily trend, every variant fixed before any result:
  P. Trend pullback — the coin is above (below) its D-day average: buy (sell) when hourly RSI(14) falls below r
     (rises above 100-r); out when RSI crosses 50, at a 4 x ATR(24h) stop, or after T hours.
  Q. Hourly channel breakout — close above (below) the last N hours' high (low), optionally only with the daily
     trend; a trailing k x ATR stop, at most 30 days.
  R. Volatility squeeze breakout — Bollinger(20) width in its lowest 10% of the last 30 days, then a close outside
     the band; a trailing k x ATR stop, at most 30 days; optionally only with the daily trend.

Universe: each day the previous day's top 10 by 30-day USDT volume (delisted included). Costs: taker 0.05% +
0.02% slippage a side, and each coin's real daily funding for the time held. Account: at most 5 positions, each
40% of equity as notional (2x on a fifth of the account), compounding. In-sample pick: best Sharpe before 2024.

  RAQM_RESEARCH_CACHE=/opt/raqm-data/research python research/hourly_trend_study.py   # needs research/m5_data.py
"""
import json, os, pickle, sys, time
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m5_data import ranks, CACHE

COST, TOP, K, LEV, MAX_HOLD = 0.0005 + 0.0002, 10, 5, 2.0, 720
CUT, HOUR, DAY = pd.Timestamp("2024-01-01"), 3_600_000, 86_400_000
H1 = CACHE / "h1"

P = [("P", D, r, T) for D in (50, 100) for r in (25, 30) for T in (24, 72)]
Q = [("Q", N, k, f) for N in (72, 168) for k in (4.0, 8.0) for f in (0, 1)]
R = [("R", 20, k, f) for k in (3.0, 6.0) for f in (0, 1)]
VARIANTS = P + Q + R


def name(v):
    f, a, b, c = v
    return {"P": f"P pullback SMA{a}d RSI<{b:g} T{c}h", "Q": f"Q breakout {a}h trail{b:g}ATR {'trend' if c else 'any'}",
            "R": f"R squeeze trail{b:g}ATR {'trend' if c else 'any'}"}[f]


def hourly(sym):
    """1h candles from the saved 5m ones (full hours only), cached in <cache>/h1."""
    H1.mkdir(exist_ok=True)
    p, src = H1 / f"{sym}.pkl", CACHE / "m5" / f"{sym}.pkl"
    if p.exists() and p.stat().st_mtime >= src.stat().st_mtime:
        return pickle.loads(p.read_bytes())
    d = pickle.loads(src.read_bytes())
    g = d.ts // HOUR
    h = d.groupby(g).agg(ts=("ts", "first"), open=("open", "first"), high=("high", "max"), low=("low", "min"),
                         close=("close", "last"), qvol=("qvol", "sum"), n=("ts", "size"))
    h = h[h.n == 12].drop(columns="n").reset_index(drop=True)
    p.write_bytes(pickle.dumps(h)); return h


def rsi(c, n=14):
    d = np.diff(c, prepend=c[0]); up, dn = np.maximum(d, 0), np.maximum(-d, 0)
    au = pd.Series(up).ewm(alpha=1 / n, adjust=False).mean().to_numpy()
    ad = pd.Series(dn).ewm(alpha=1 / n, adjust=False).mean().to_numpy()
    return 100 - 100 / (1 + au / np.where(ad > 0, ad, 1e-12))


def atr(h, l, c, n=24):
    pc = np.insert(c[:-1], 0, c[0])
    return pd.Series(np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))).rolling(n).mean().to_numpy()


def trail_exit(s, e, o, h, l, c, dist, end):
    """Trailing stop dist from the best price since entry (as of the previous bar); exit at the stop or a gap open."""
    if s == 1:
        best = np.maximum.accumulate(np.insert(h[e:end], 0, o[e])); stop = best - dist
        hit = np.flatnonzero(l[e:end + 1] <= stop)
        return (e + hit[0], min(o[e + hit[0]], stop[hit[0]])) if len(hit) else (end, c[end])
    best = np.minimum.accumulate(np.insert(l[e:end], 0, o[e])); stop = best + dist
    hit = np.flatnonzero(h[e:end + 1] >= stop)
    return (e + hit[0], max(o[e + hit[0]], stop[hit[0]])) if len(hit) else (end, c[end])


def run(v, sym, b, ok, reg, ind):
    f = v[0]
    o, h, l, c, ts = ind["o"], ind["h"], ind["l"], ind["c"], ind["ts"]
    n, a = len(c), ind["atr"]
    up, dn = reg[v[1]] if f == "P" else reg[50]
    if f == "P":
        r_ = ind["rsi"]; lim = v[2]
        sig = np.where(ok & up & (r_ < lim), 1, np.where(ok & dn & (r_ > 100 - lim), -1, 0))
    elif f == "Q":
        N = v[1]; hi, lo = ind[f"hi{N}"], ind[f"lo{N}"]
        L = (c > hi) & ((up) if v[3] else True); S = (c < lo) & ((dn) if v[3] else True)
        sig = np.where(ok & L, 1, np.where(ok & S, -1, 0))
    else:
        sq = ind["squeeze"]
        L = sq & (c > ind["bbu"]) & ((up) if v[3] else True); S = sq & (c < ind["bbl"]) & ((dn) if v[3] else True)
        sig = np.where(ok & L, 1, np.where(ok & S, -1, 0))
    sig[~np.isfinite(a)] = 0
    out, i = [], 0
    cand = np.flatnonzero(sig[:-1])
    while True:
        j = np.searchsorted(cand, i)
        if j >= len(cand): break
        t = cand[j]; s = int(sig[t]); e = t + 1
        if f == "P":
            end = min(e + v[3] - 1, n - 1); stop = o[e] - s * 4 * a[t]
            seg = slice(e, end + 1)
            hs = np.flatnonzero(l[seg] <= stop) if s == 1 else np.flatnonzero(h[seg] >= stop)
            xr = np.flatnonzero(ind["rsi"][seg] > 50) if s == 1 else np.flatnonzero(ind["rsi"][seg] < 50)
            first_s = hs[0] if len(hs) else 10**9; first_r = xr[0] if len(xr) else 10**9
            if first_s <= first_r and len(hs):
                x = e + first_s; px = min(o[x], stop) if s == 1 else max(o[x], stop)
            elif len(xr):
                x = e + first_r; px = c[x]
            else:
                x = end; px = c[end]
        else:
            end = min(e + MAX_HOLD - 1, n - 1)
            x, px = trail_exit(s, e, o, h, l, c, v[2] * a[t], end)
        out.append((sym, s, int(ts[e]), int(ts[x]), float(o[e]), float(px), float(ind["qvol"][t])))
        i = x + 1
    return out


def funding_cost(fund, sym, side, ets, xts):
    f = fund.get(sym) or {}
    d0, d1 = (ets // DAY) * DAY, (xts // DAY) * DAY
    days = range(d0, d1 + DAY, DAY)
    tot = sum(f.get(d, 0.0) for d in days)
    frac = max(xts - ets, HOUR) / max((d1 - d0 + DAY), DAY)          # the share of those days actually held
    return side * tot * frac


def portfolio(trades, start=1.0):
    """At most K positions, each LEV/K of equity as notional, equity realized on exits (compounding)."""
    t = trades.sort_values("ets").reset_index(drop=True)
    eq, open_, rows = start, [], []
    for r in t.itertuples():
        for p in [p for p in open_ if p[0] <= r.ets]:
            eq += p[1]; rows.append((p[0], eq)); open_.remove(p)
        if len(open_) >= K: continue
        notional = eq * LEV / K
        open_.append((r.xts, notional * r.net, r.Index))
        open_.sort()
    for p in open_: eq += p[1]; rows.append((p[0], eq))
    taken = len(rows)
    s = pd.Series([e for _, e in rows], index=pd.to_datetime([x for x, _ in rows], unit="ms"))
    return s, taken


def evaluate(trades):
    if len(trades) < 30: return None
    curve, taken = portfolio(trades)
    d = curve.resample("D").last().ffill()
    d = pd.concat([pd.Series([1.0], index=[d.index[0] - pd.Timedelta(days=1)]), d])
    ret = d.pct_change().dropna()
    def part(m):
        r = ret[m]
        if len(r) < 30: return {"sharpe": 0.0, "ret_pct": 0.0}
        return {"sharpe": round(float(r.mean() / r.std() * np.sqrt(365)) if r.std() > 0 else 0.0, 2),
                "ret_pct": round(float(((1 + r).prod() - 1) * 100), 1)}
    years = (d.index[-1] - d.index[0]).days / 365.25
    wins, losses = trades.net[trades.net > 0], trades.net[trades.net <= 0]
    return {"trades": int(len(trades)), "taken": taken, "win": round(float(len(wins) / len(trades) * 100), 1),
            "profit_factor": round(float(wins.sum() / -losses.sum()), 2) if losses.sum() < 0 else None,
            "avg_win_pct": round(float(wins.mean() * 100), 2), "avg_loss_pct": round(float(losses.mean() * 100), 2),
            "gross_bps": round(float(trades.gross.mean() * 1e4), 1), "funding_bps": round(float(trades.funding.mean() * 1e4), 1),
            "net_bps": round(float(trades.net.mean() * 1e4), 1), "hours": round(float((trades.xts - trades.ets).mean() / HOUR), 1), "cagr_pct": round(float((d.iloc[-1] ** (1 / years) - 1) * 100), 1),
            "max_dd_pct": round(float(((d.cummax() - d) / d.cummax()).max() * 100), 1),
            "before": part(ret.index < CUT), "after": part(ret.index >= CUT)}


def main():
    t0 = time.time()
    daily = pickle.loads((CACHE / "universe_daily.pkl").read_bytes())
    fund = pickle.loads((CACHE / "universe_funding.pkl").read_bytes())
    member = (ranks(daily) <= TOP).shift(1, fill_value=False)
    days = pd.DatetimeIndex(member.index).as_unit("ms").asi8
    trades = {v: [] for v in VARIANTS}
    files = sorted((CACHE / "m5").glob("*.pkl"))
    for n_, p in enumerate(files):
        sym = p.stem
        if sym not in member or sym not in daily: continue
        b = hourly(sym)
        ts = b.ts.to_numpy(); dk = (ts // DAY) * DAY
        idx = np.clip(np.searchsorted(days, dk), 0, len(days) - 1)
        ok = member[sym].to_numpy()[idx] & (days[idx] == dk)
        if not ok.any(): continue
        dd = daily[sym]; dc = dd.close.to_numpy(np.float64); dts = dd.ts.to_numpy()
        reg = {}
        for D in (50, 100):
            sma = pd.Series(dc).rolling(D).mean().to_numpy()
            j = np.searchsorted(dts, dk) - 1                                 # the last completed day before this hour
            valid = j >= 0; jj = np.clip(j, 0, len(dc) - 1)
            above = valid & np.isfinite(sma[jj]) & (dc[jj] > sma[jj]); below = valid & np.isfinite(sma[jj]) & (dc[jj] < sma[jj])
            reg[D] = (above, below)
        o, h, l, c = (b[x].to_numpy(np.float64) for x in ("open", "high", "low", "close"))
        ind = {"o": o, "h": h, "l": l, "c": c, "ts": ts, "qvol": b.qvol.to_numpy(np.float64), "rsi": rsi(c), "atr": atr(h, l, c)}
        for N in (72, 168):
            ind[f"hi{N}"] = pd.Series(h).rolling(N).max().shift(1).to_numpy()
            ind[f"lo{N}"] = pd.Series(l).rolling(N).min().shift(1).to_numpy()
        sma20 = pd.Series(c).rolling(20).mean(); sd20 = pd.Series(c).rolling(20).std(ddof=0)
        width = (4 * sd20 / sma20)
        q10 = width.rolling(720, min_periods=240).quantile(0.10).shift(1)
        ind["squeeze"] = (width.shift(1) <= q10).to_numpy()
        ind["bbu"], ind["bbl"] = (sma20 + 2 * sd20).to_numpy(), (sma20 - 2 * sd20).to_numpy()
        for v in VARIANTS:
            trades[v] += run(v, sym, b, ok, reg, ind)
        if n_ % 10 == 0: print(f"  {n_ + 1}/{len(files)} {sym} {time.time() - t0:.0f}s", flush=True)
    res, frames = {}, {}
    for v in VARIANTS:
        t = pd.DataFrame(trades[v], columns=["sym", "side", "ets", "xts", "entry", "exit", "qvol"])
        if not len(t): continue
        t["gross"] = t.side * (t.exit / t.entry - 1)
        t["funding"] = [funding_cost(fund, s, sd, a, x) for s, sd, a, x in zip(t.sym, t.side, t.ets, t.xts)]
        t["net"] = t.gross - 2 * COST - t.funding
        res[name(v)] = evaluate(t); frames[name(v)] = t
    print("\nvariant | trades | win% | PF | avg win% | avg loss% | net bps | CAGR% | maxDD% | Sharpe<2024 | Sharpe 2024-> | ret% 2024->")
    for k_, r in res.items():
        if r: print(f"{k_} | {r['trades']} | {r['win']} | {r['profit_factor']} | {r['avg_win_pct']} | {r['avg_loss_pct']} | {r['gross_bps']} | {r['funding_bps']} | {r['net_bps']} | {r['hours']} | "
                    f"{r['cagr_pct']} | {r['max_dd_pct']} | {r['before']['sharpe']} | {r['after']['sharpe']} | {r['after']['ret_pct']}")
    ok_ = {k_: r for k_, r in res.items() if r and r["trades"] >= 100}
    pick = max(ok_, key=lambda k_: ok_[k_]["before"]["sharpe"])
    pos = sum(1 for r in ok_.values() if r["after"]["ret_pct"] > 0)
    print(f"\nin-sample pick: {pick} -> Sharpe after 2024 {ok_[pick]['after']['sharpe']}, return {ok_[pick]['after']['ret_pct']}%")
    print(f"variants positive after 2024: {pos} / {len(ok_)}")
    # capital check for the pick: $200 (Binance's $5 minimum) and $10,000 (share of the hour's volume)
    t = frames[pick]
    for cap in (200, 10_000):
        notional = cap * LEV / K
        print(f"  ${cap:,}: {notional:,.0f} notional a position; above $5 minimum: {notional >= 5}; "
              f"median share of the signal hour's volume {np.median(notional / t.qvol.clip(lower=1)) * 100:.4f}%, "
              f"99th pct {np.percentile(notional / t.qvol.clip(lower=1), 99) * 100:.4f}%")
    Path("hourly_trend_results.json").write_text(json.dumps({"variants": res, "pick": pick}, indent=1))
    frames[pick].to_csv("hourly_trend_pick_trades.csv", index=False)
    print(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
