"""
The ratio trend three ways, on the same data and costs (docs/ratio-trend-live-plan.md §1):

  PAIRS     the tested strategy: every pair among the weekly top 7 by 30-day volume, long the stronger / short the
            weaker while their price ratio is above its 50-day mean (what the backtest and the paper bot run);
  NETTED    the same pairs summed into one position per coin (+6 … −6 units); fees only on the net change;
  LIVE NOW  what the live path can hold today: one position per coin, so only pairs whose coins are both free open,
            first come in sorted order, as bot.py run_once_ratio.

Daily model: a signal on day d's close trades at day d+1's open; each unit is AMOUNT margin × LEV notional, its value
reset to that each day (so PAIRS here differs a little from research/ratio_fairness.py, which keeps a pair's
quantity from entry). Fees 0.04% per side on every unit traded, real funding per unit. No 40% stop (the netted
basket has none decided yet; the paper/live stop fires rarely on a hedged pair).

  python -X utf8 research/ratio_netting_study.py
"""
import sys, pickle, itertools, math
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import short_study as ss
import pump_momentum_study as pm

CACHE = ss.CACHE
AMOUNT, LEV, FEE, CUT = 26, 2, 0.0004, pd.Timestamp("2024-01-01")   # $26 margin: the real account's size
TOP, SMA, START = 7, 50, pd.Timestamp("2020-01-01")
N = AMOUNT * LEV


def load():
    data = pickle.loads((CACHE / "universe_daily.pkl").read_bytes())
    fund_raw = pickle.loads((CACHE / "universe_funding.pkl").read_bytes())
    idx = lambda df: pd.to_datetime(df.ts, unit="ms")
    O = pd.DataFrame({s: df.set_index(idx(df)).open for s, df in data.items()}).sort_index()
    C = pd.DataFrame({s: df.set_index(idx(df)).close for s, df in data.items()}).sort_index()
    F = pd.DataFrame({s: pd.Series({pd.Timestamp(int(t), unit="ms"): v for t, v in fund_raw.get(s, {}).items()}, dtype=float)
                      for s in data}).reindex(O.index).fillna(0.0)
    rk = pm.rank_table(data, 120)
    return data, O, C, F, rk


def members_by_day(rk, days):
    weeks = rk.index[rk.index >= START][::7]
    m = {d: tuple(sorted(rk.loc[d][rk.loc[d] <= TOP].index)) for d in weeks}
    s = pd.Series(m).reindex(days, method="ffill")
    return s


def signals(C, days, members):
    """{day: {(a, b): ±1}} for the pairs among that day's members with a valid 50-day mean."""
    need = sorted({p for ms in members.dropna() for p in itertools.combinations(ms, 2)})
    sig = {}
    for a, b in need:
        r = C[a] / C[b]
        s = np.sign(r - r.rolling(SMA).mean())
        sig[(a, b)] = s.where(r.rolling(SMA).count() >= SMA)
    out = {}
    for d in days:
        ms = members.get(d)
        if not isinstance(ms, tuple): out[d] = {}; continue
        out[d] = {p: int(sig[p].get(d)) for p in itertools.combinations(ms, 2)
                  if p in sig and pd.notna(sig[p].get(d)) and sig[p].get(d) != 0}
    return out


def legs(pair, sg):
    a, b = pair
    return {a: sg, b: -sg}


def simulate(O, F, days, sig, mode):
    """Daily PnL for one of the three ways; also units held per day and pair-trade PnLs (PAIRS / LIVE NOW)."""
    held = {}                       # pair -> sign (the pairs the strategy holds on day d+1)
    prev_units = {}; prev_pair_units = {}
    rows = []; open_pair = {}; trades = []
    for i, d in enumerate(days[:-2]):
        want = sig.get(d, {})
        if mode == "live":
            # the live path: a held pair flips or closes; a new pair opens only when both coins are free
            new = {}
            for p, sg in held.items():
                if p in want: new[p] = want[p]
            busy = {c for p in new for c in p}
            for p in sorted(want):
                if p in new: continue
                if p[0] in busy or p[1] in busy: continue
                new[p] = want[p]; busy |= set(p)
            held = new
        else:
            held = dict(want)
        # pair-level units (for the pair fee and for pair trades)
        pair_units = {}
        for p, sg in held.items():
            for c, u in legs(p, sg).items(): pair_units[(p, c)] = u
        units = {}
        for (p, c), u in pair_units.items(): units[c] = units.get(c, 0) + u
        units = {c: u for c, u in units.items() if u}
        t0, t1 = days[i + 1], days[i + 2]
        ret = (O.loc[t1] / O.loc[t0] - 1).fillna(0.0)
        fnd = F.loc[t0]
        if mode == "netted":
            traded = sum(abs(units.get(c, 0) - prev_units.get(c, 0)) for c in set(units) | set(prev_units))
        else:
            traded = sum(abs(pair_units.get(k, 0) - prev_pair_units.get(k, 0)) for k in set(pair_units) | set(prev_pair_units))
        gross = sum(u * N * ret.get(c, 0.0) for c, u in units.items())
        funding = sum(u * N * fnd.get(c, 0.0) for c, u in units.items())
        fees = traded * N * FEE
        rows.append({"day": t0, "pnl": gross - funding - fees, "fees": fees, "funding": funding,
                     "gross_units": sum(abs(u) for u in units.values()), "pairs": len(held)})
        # pair trades: open on a new sign, booked on a flip or a close
        for p in set(open_pair) | set(held):
            pnl_today = sum(u * N * ret.get(c, 0.0) - u * N * fnd.get(c, 0.0) for c, u in legs(p, held[p]).items()) if p in held else 0.0
            if p in open_pair and (p not in held or held[p] != open_pair[p]["sg"]):
                trades.append(open_pair.pop(p)["pnl"] - 2 * N * FEE)        # the exit fee of both legs
            if p in held:
                if p not in open_pair: open_pair[p] = {"sg": held[p], "pnl": -2 * N * FEE}   # the entry fee
                open_pair[p]["pnl"] += pnl_today
        prev_units, prev_pair_units = units, pair_units
    return pd.DataFrame(rows).set_index("day"), trades


def simulate_netted_stop(O, H, L, F, days, sig, stop=0.40):
    """NETTED with each coin's own stop, as the live legs carry (40% from the price the coin's net position took its
    current size and side): hit → the coin is flat until the strategy's net units for it change."""
    tgt_prev = {}; held = {}; entry = {}; stopped = set(); rows = []
    for i, d in enumerate(days[:-2]):
        tgt = {}
        for p, sg in sig.get(d, {}).items():
            for c, u in legs(p, sg).items(): tgt[c] = tgt.get(c, 0) + u
        tgt = {c: u for c, u in tgt.items() if u}
        t0, t1 = days[i + 1], days[i + 2]
        traded = 0
        for c in set(tgt) | set(tgt_prev):
            if tgt.get(c, 0) != tgt_prev.get(c, 0):
                stopped.discard(c); entry[c] = O.at[t0, c]
        now = {c: u for c, u in tgt.items() if c not in stopped}
        traded += sum(abs(now.get(c, 0) - held.get(c, 0)) for c in set(now) | set(held))
        gross = funding = 0.0
        for c, u in now.items():
            o, e = O.at[t0, c], entry[c]
            lvl = e * (1 - stop) if u > 0 else e * (1 + stop)
            hit = (L.at[t0, c] <= lvl) if u > 0 else (H.at[t0, c] >= lvl)
            if hit:
                px = min(o, lvl) if u > 0 else max(o, lvl)        # a gap through the stop fills at the open
                gross += u * N * (px / o - 1); stopped.add(c); traded += abs(u)
            else:
                gross += u * N * (O.at[t1, c] / o - 1)
            funding += u * N * F.at[t0, c]
        held = {c: u for c, u in now.items() if c not in stopped}
        fees = traded * N * FEE
        rows.append({"day": t0, "pnl": gross - funding - fees, "fees": fees, "funding": funding,
                     "gross_units": sum(abs(u) for u in now.values()), "pairs": 0})
        tgt_prev = tgt
    return pd.DataFrame(rows).set_index("day"), []


def stats(df, trades, label):
    d = df.pnl; eq = d.cumsum(); dd = float((eq.cummax() - eq).max())
    sh = lambda x: round(x.mean() / x.std() * math.sqrt(365), 2) if x.std() else 0.0
    t = pd.Series(trades, dtype=float)
    pf = round(t[t > 0].sum() / -t[t < 0].sum(), 2) if len(t) and (t < 0).any() else None
    out = {"version": label, "pnl $": round(d.sum()), "worst DD $": round(dd), "worst DD margins": round(dd / AMOUNT, 1),
           "Sharpe <2024": sh(d[d.index < CUT]), "Sharpe 2024→": sh(d[d.index >= CUT]),
           "fees $": round(df.fees.sum()), "funding $": round(df.funding.sum()),
           "avg margin used $": round(df.gross_units.mean() * AMOUNT), "max margin used $": round(df.gross_units.max() * AMOUNT),
           "pair trades": len(t) if len(t) else "—", "win%": round((t > 0).mean() * 100) if len(t) else "—", "PF": pf if pf else "—"}
    for y, v in d.groupby(d.index.year).sum().items(): out[str(y)] = round(v)
    return out


def main():
    data, O, C, F, rk = load()
    days = O.index[O.index >= START]
    members = members_by_day(rk, days)
    sig = signals(C, days, members)
    rows = []; daily = {}
    for mode, label in (("pairs", "PAIRS (tested)"), ("netted", "NETTED (one position per coin)"), ("live", "LIVE NOW (coin-disjoint pairs)")):
        df, tr = simulate(O, F, days, sig, mode)
        rows.append(stats(df, tr, label)); daily[label] = df.pnl
    H, L = (pd.DataFrame({s: df.set_index(pd.to_datetime(df.ts, unit="ms"))[k] for s, df in data.items()}).sort_index() for k in ("high", "low"))
    df, _ = simulate_netted_stop(O, H, L, F, days, sig)
    label = "NETTED + 40% stop per coin"; rows.append(stats(df, [], label)); daily[label] = df.pnl
    out = pd.DataFrame(rows).set_index("version").T
    pd.set_option("display.width", 200)
    print(f"ratio trend, weekly top {TOP} by volume, ratio vs its {SMA}-day mean, ${AMOUNT} margin x{LEV} per unit, "
          f"{days[0].date()} → {days[-1].date()}\n")
    print(out.to_string())
    # the worst stretches, and the last 12 months
    for label, d in daily.items():
        eq = d.cumsum(); peak = eq.cummax(); trough = (peak - eq).idxmax(); top = eq.loc[:trough].idxmax()
        last = d[d.index >= d.index[-1] - pd.Timedelta(days=365)]
        m = d.resample("ME").sum()
        print(f"\n{label}: worst drawdown {top.date()} → {trough.date()}; last 12 months {round(last.sum())} $; "
              f"losing months {int((m < 0).sum())} of {len(m)}; worst month {round(m.min())} $ ({m.idxmin():%Y-%m})")


if __name__ == "__main__":
    main()
