"""
Three hourly ideas — Binance USDT-M hourly candles for every coin ever in the top 10 by volume (delisted included,
research/hourly_data.py), exact-time funding, fees 0.04% per side, $20 x2 per trade, chosen on Sharpe before 2024.
Daily membership = the top 10 by 30-day volume as of the previous day (no look-ahead).

1. Intraday time-series momentum — Gao, Han, Li & Zhou (2018) "Market Intraday Momentum" (JFE); Shen, Urquhart &
   Wang (2022) "Bitcoin Intraday Time Series Momentum" (Financial Review): the return over the first S hours of the
   UTC day sets the direction of a trade over the last T hours (closed before 00:00, so no funding).
2. Lead-lag: BTC leads the altcoins — after an hour where BTC moved more than X, trade the top-10 altcoins in the
   same direction for the next H hours (all of them, or only those that lagged: moved less than half as much).
3. Funding-time effect (perpetual futures; Ackerer, Hugonnier & Jermann 2023 on perpetual pricing): when the last
   settled funding rate is above thr, short the coin Hb hours before the next funding time and close just before it
   (no funding paid); long when it is below -thr.

  python research/hourly_data.py && python research/hourly_study.py
"""
import sys, pickle, itertools, math
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import short_study as ss
import pump_momentum_study as pm
import strategies_trend as st
from universe_study import ranks

CACHE = ss.CACHE
AMOUNT, LEV, FEE, CUT = ss.AMOUNT, ss.LEV, ss.FEE, ss.CUT
N = AMOUNT * LEV          # notional per trade
HR, DAY = 3_600_000, 86_400_000


def load():
    data = pickle.loads((CACHE / "universe_daily.pkl").read_bytes())
    rk = ranks(data)
    hourly = {p.stem: pickle.loads(p.read_bytes()) for p in (CACHE / "hourly").glob("*.pkl")}
    hourly = {s: df for s, df in hourly.items() if len(df) > 24 * 30}
    fund = {p.stem: pickle.loads(p.read_bytes()) for p in (CACHE / "funding8h").glob("*.pkl")}
    member = (rk.shift(1) <= 10)           # membership known at the start of each day
    return data, hourly, fund, member


def is_member(member, sym, day_ms):
    d = pd.Timestamp(day_ms, unit="ms").normalize()
    try: return bool(member.at[d, sym])
    except KeyError: return False


def trade(entry_ts, exit_ts, sg, e, x, fu=0.0, **kw):
    q = N / e
    return {"entry_ts": int(entry_ts), "exit_ts": int(exit_ts), "side": "long" if sg == 1 else "short", "entry": e, "exit": x,
            "qty": q, "pnl": sg * (x - e) * q - (e * q + x * q) * FEE - sg * fu * N, **kw}


# ── 1. intraday momentum ──
def intraday(hourly, member, uni, S, T, th):
    out = []
    syms = ["BTCUSDT"] if uni == "BTC" else list(hourly)
    for s in syms:
        df = hourly[s]
        day, hour = df.ts.values // DAY, (df.ts.values // HR) % 24
        full = pd.Series(hour).groupby(day).transform("size").values == 24
        d = df[full]
        if d.empty: continue
        days = d.ts.values.reshape(-1, 24) // DAY
        o, c = d.open.values.reshape(-1, 24), d.close.values.reshape(-1, 24)
        sig = c[:, S - 1] / o[:, 0] - 1
        for k in range(len(o)):
            if abs(sig[k]) <= th or np.isnan(sig[k]): continue
            if uni != "BTC" and not is_member(member, s, days[k, 0] * DAY): continue
            sg = 1 if sig[k] > 0 else -1
            out.append(trade(days[k, 0] * DAY + (24 - T) * HR, days[k, 0] * DAY + DAY - 1, sg, o[k, 24 - T], c[k, 23]))
    return out


# ── 2. lead-lag ──
def leadlag(hourly, member, X, mode, H, fund_at):
    btc = hourly["BTCUSDT"].set_index("ts"); bret = (btc.close / btc.open - 1)
    sig_ts = bret.index[(bret.abs() > X).values]
    out = []
    for s, df in hourly.items():
        if s == "BTCUSDT": continue
        a = df.set_index("ts"); aret = a.close / a.open - 1
        pos = {t: i for i, t in enumerate(a.index)}
        o, c = a.open.values, a.close.values
        for t in sig_ts:
            i = pos.get(t)
            if i is None or i + H >= len(a) or a.index[i + H] != t + H * HR: continue
            if not is_member(member, s, t): continue
            sg = 1 if bret[t] > 0 else -1
            if mode == "lagging" and sg * aret.iloc[i] >= 0.5 * abs(bret[t]): continue
            fu = fund_at(s, t + HR, t + (H + 1) * HR)             # funding settled while held (longs pay positive)
            out.append(trade(t + HR, t + (H + 1) * HR - 1, sg, o[i + 1], c[i + H], fu))
    return out


# ── 3. funding-time effect ──
def funding_time(hourly, fund, member, thr, Hb):
    out = []
    for s, f in fund.items():
        if s not in hourly or len(f) < 3: continue
        a = hourly[s].set_index("ts"); o = a.open
        times, rates = f.ts.values // HR * HR, f.rate.values
        for k in range(1, len(times)):
            T, prev = times[k], rates[k - 1]
            if abs(prev) <= thr: continue
            t0 = T - Hb * HR
            if t0 not in o.index or T not in o.index or not is_member(member, s, t0): continue
            sg = -1 if prev > 0 else 1
            out.append(trade(t0, T - 1, sg, o[t0], o[T]))         # closed just before settlement: no funding
    return out


def main():
    data, hourly, fund, member = load()
    print(f"{len(hourly)} coins with hourly candles, {len(fund)} with exact funding", flush=True)
    fidx = {s: (f.ts.values, f.rate.values) for s, f in fund.items()}
    def fund_at(s, t0, t1):
        if s not in fidx: return 0.0
        ts, r = fidx[s]; m = (ts >= t0) & (ts < t1); return float(r[m].sum())

    rows, best = [], {}
    def keep(tag, r):
        rows.append(r)
        if r.get("trades") and (tag not in best or r["is_sharpe"] > best[tag]["is_sharpe"]): best[tag] = r

    for uni, S, T, th in itertools.product(["BTC", "top10"], [1, 4, 12], [1, 2], [0.0, 0.01]):
        keep("1", ss.summary(intraday(hourly, member, uni, S, T, th), f"1 intraday momentum {uni}: first {S}h -> last {T}h{', move > 1%' if th else ''}"))
    print("idea 1 done", flush=True)
    for X, mode, H in itertools.product([0.01, 0.02], ["all", "lagging"], [1, 3]):
        keep("2", ss.summary(leadlag(hourly, member, X, mode, H, fund_at), f"2 lead-lag: BTC hour > {X:.0%}, {mode} alts, hold {H}h"))
    print("idea 2 done", flush=True)
    for thr, Hb in itertools.product([0.0003, 0.0005, 0.001], [1, 2, 4]):
        keep("3", ss.summary(funding_time(hourly, fund, member, thr, Hb), f"3 funding time: |last rate| > {thr * 100:.2f}%, enter {Hb}h before"))
    print("idea 3 done", flush=True)

    # the three core paper bots (daily), for the combinations
    fund_raw = pickle.loads((CACHE / "universe_funding.pkl").read_bytes()); fd = {s: fund_raw.get(s, {}) for s in data}
    rk10 = ranks(data); ever10 = [s for s in data if (rk10[s] <= 10).any()]; rk100 = pm.rank_table(data, 60)
    long_tr = []
    for s in ever10:
        df = data[s]; top10 = list((rk10[s].reindex(pd.to_datetime(df.ts, unit="ms")) <= 10).fillna(False))
        long_tr += st.run_trend_daily(list(df.open), list(df.high), list(df.low), list(df.close), list(df.ts),
                                      [fd[s].get(int(t), 0.0) for t in df.ts], AMOUNT, LEV, FEE, 0, top10)
    new = [s for s, df in data.items() if pd.to_datetime(df.ts.iloc[0], unit="ms") >= pd.Timestamp("2021-01-01")]
    lst = []
    for s in new: lst += ss.run_listing_short(data[s], [fd[s].get(int(t), 0.0) for t in data[s].ts], 30, 90, 0.4)
    three = [ss.summary(long_tr, "PAPER 1"), ss.summary(pm.cap(lst, 10), "PAPER 2"),
             ss.summary([t for s, d, side in pm.momentum_positions(data, rk100, 2, True) if (t := pm.momentum_trade(data[s], fd[s], d, side))], "PAPER 3")]

    def combo(name, parts):
        d = parts[0]["_daily"]
        for p in parts[1:]: d = d.add(p["_daily"], fill_value=0)
        eq = d.cumsum(); sh = lambda x: round(x.mean() / x.std() * math.sqrt(365), 2)
        return {"variant": name, "pnl": round(d.sum()), "maxDD": round(float((eq.cummax() - eq).max())),
                "is_sharpe": sh(d[d.index < CUT]), "oos_sharpe": sh(d[d.index >= CUT]), "oos_pnl": round(d[d.index >= CUT].sum()),
                **{str(y): int(v) for y, v in d.groupby(d.index.year).sum().round(0).items() if y >= 2020}}
    rows += [combo("THREE CORE BOTS (daily)", three)] + [combo(f"three bots + best idea {k}", three + [best[k]]) for k in ("1", "2", "3") if k in best]
    out = pd.DataFrame([{k: v for k, v in r.items() if k != "_daily"} for r in rows]).set_index("variant")
    pd.set_option("display.width", 290); pd.set_option("display.max_columns", 30); pd.set_option("display.max_rows", 90)
    cols = [c for c in ["trades", "win%", "pnl", "maxDD", "is_sharpe", "oos_sharpe", "oos_pnl", "2020", "2021", "2022", "2023", "2024", "2025", "2026"] if c in out]
    print(out[cols].to_string())
    for k in ("1", "2", "3"):
        if k in best: print(f"best idea {k} on in-sample Sharpe: {best[k]['variant']}")
    for tag, n in (("1 ", 24), ("2 ", 8), ("3 ", 9)):
        print(f"variants with positive total PnL ({tag.strip()}): {sum(1 for r in rows if str(r.get('variant', '')).startswith(tag) and r.get('pnl', 0) > 0)}/{n}")
    fees = {k: round(sum(1 for _ in range(best[k]['trades'])) * N * 2 * FEE) for k in best}
    print("fees paid by the best variant of each idea ($):", fees)


if __name__ == "__main__":
    main()
