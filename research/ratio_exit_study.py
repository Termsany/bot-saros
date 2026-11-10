"""
Ratio trend exits: does an earlier exit keep the profit a trend reversal gives back? (owner, 2026-11-10: "it closes at a
loss when the trend turns, after it was in profit").

Today a pair is held while its price ratio is above (long the first) or below (short) its 50-day mean, and closed only
when the ratio crosses back: the reversal must already be under way. Six exits, fixed before any result:

  A  today: the 50-day cross only
  B1 trail 10%: out when the ratio (in the trade's direction) closes 10% below its best close since entry
  B2 trail 20%: the same at 20%
  C  faster exit: in only while the 20-day mean agrees with the 50-day one; out when the 20-day one turns
  D  break-even lock: once the ratio is +15% in the trade's direction, out if it comes back to the entry
  E  time: out after 30 days

After B1, B2, D or E the pair stays flat until its 50-day sign changes (as a stopped coin in the netted bot); C re-enters
when both means agree again. Exits are decided on a daily close and traded at the next open, like the signal.

Two universes: the weekly 30-day top 7 by volume (the paper bot) and the same without BTC/ETH (the candidate, §25).
Two books from the same held pairs: PAIRS (what the paper bot runs, with per-trade stats) and NETTED + 40% stop per coin
(what the live bot would run, research §21/§25). $26 margin x2 per unit, fees 0.04% per side, real funding.

The rule, fixed before the run: an exit is a candidate only if NETTED's Sharpe before 2024 beats A on the no-BTC
universe AND its Sharpe after 2024 is not lower. Seven variants were tried (with A); 17 universes before them.

  python -X utf8 research/ratio_exit_study.py
"""
import sys, math, itertools
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ratio_netting_study as rn
import ratio_universe_study as ru

N, FEE, CUT, AMOUNT = rn.N, rn.FEE, rn.CUT, rn.AMOUNT
TURNED = 5.0          # a pair trade "was in profit" once its running PnL reached +$5 (about 5% of its $104 notional)

VARIANTS = {
    "A today (50-day cross)": {},
    "B1 trail 10%": {"trail": 0.10},
    "B2 trail 20%": {"trail": 0.20},
    "C exit on the 20-day mean": {"fast": 20},
    "D break-even after +15%": {"lock": 0.15},
    "E out after 30 days": {"days": 30},
}


def held_pairs(C, days, sig, rule):
    """{day: {pair: sign}} the strategy holds after `rule`'s exits, from the 50-day signals `sig`."""
    pairs = sorted({p for s in sig.values() for p in s})
    ratio = {p: C[p[0]] / C[p[1]] for p in pairs}
    fast = {p: np.sign(r - r.rolling(rule["fast"]).mean()) for p, r in ratio.items()} if "fast" in rule else {}
    st = {}                      # pair -> {"sg", "entry", "best", "age", "locked"} while held; {"blocked": sg} after an exit
    out = {}
    for d in days:
        want, now = sig.get(d, {}), {}
        for p in list(st):
            if p not in want: st.pop(p)                      # left the members or no valid signal: closed
        for p, s in want.items():
            r = ratio[p].get(d)
            if r is None or not np.isfinite(r): continue
            if "fast" in rule:
                f = fast[p].get(d)
                if f == s: now[p] = s
                continue
            cur = st.get(p)
            if cur and "blocked" in cur:
                if s == cur["blocked"]: continue             # flat until the 50-day sign changes
                cur = None
            if cur is None or cur["sg"] != s:                # new, or a flip: a new trade
                cur = st[p] = {"sg": s, "entry": r, "best": 1.0, "age": 0, "locked": False}
            else:
                cur["age"] += 1
                x = (r / cur["entry"]) ** s                  # the ratio in the trade's direction, 1 = entry
                cur["best"] = max(cur["best"], x)
                if x >= 1 + rule.get("lock", math.inf): cur["locked"] = True
                out_now = (("trail" in rule and x <= cur["best"] * (1 - rule["trail"]))
                           or (cur["locked"] and x <= 1.0)
                           or ("days" in rule and cur["age"] >= rule["days"]))
                if out_now:
                    st[p] = {"blocked": s}; continue
            now[p] = s
        out[d] = now
    return out


def pair_trades(O, F, days, held):
    """Each pair trade's final PnL and its best running PnL, as the paper bot books them (daily model, fees on both
    legs in and out, funding)."""
    open_, trades = {}, []
    for i, d in enumerate(days[:-2]):
        h = held.get(d, {}); t0, t1 = days[i + 1], days[i + 2]
        ret = (O.loc[t1] / O.loc[t0] - 1).fillna(0.0); fnd = F.loc[t0]
        for p in set(open_) | set(h):
            if p in open_ and (p not in h or h[p] != open_[p]["sg"]):
                t = open_.pop(p); trades.append((t["pnl"] - 2 * N * FEE, t["peak"]))
            if p in h:
                if p not in open_: open_[p] = {"sg": h[p], "pnl": -2 * N * FEE, "peak": -2 * N * FEE}
                t = open_[p]
                t["pnl"] += sum(u * N * ret.get(c, 0.0) - u * N * fnd.get(c, 0.0) for c, u in rn.legs(p, h[p]).items())
                t["peak"] = max(t["peak"], t["pnl"])
    return trades


def sharpe(x):
    return round(x.mean() / x.std() * math.sqrt(365), 2) if x.std() else 0.0


def book(df):
    d = df.pnl; eq = d.cumsum(); dd = float((eq.cummax() - eq).max())
    return {"pnl": round(d.sum()), "DD": round(dd), "Sh<24": sharpe(d[d.index < CUT]), "Sh24→": sharpe(d[d.index >= CUT]),
            "fees": round(df.fees.sum())}


def trade_stats(trades):
    t = pd.DataFrame(trades, columns=["pnl", "peak"])
    win = t.pnl > 0; was_up = t.peak >= TURNED
    return {"trades": len(t), "win%": round(win.mean() * 100),
            "PF": round(t.pnl[win].sum() / -t.pnl[~win].sum(), 2) if (~win).any() else None,
            "up→loss %": round((was_up & ~win).sum() / max(1, was_up.sum()) * 100),
            "gave back $": round(float((t.peak - t.pnl)[t.peak > 0].mean()), 1)}


NEIGHBORS = {          # --neighbors: after the run, the two that passed (B2, E) at nearby values — a check, not a pick
    "A today (50-day cross)": {},
    "trail 15%": {"trail": 0.15}, "trail 20% (B2)": {"trail": 0.20}, "trail 25%": {"trail": 0.25}, "trail 30%": {"trail": 0.30},
    "out after 20 days": {"days": 20}, "out after 30 days (E)": {"days": 30}, "out after 45 days": {"days": 45},
    "out after 60 days": {"days": 60},
}


def main():
    global VARIANTS
    if "--neighbors" in sys.argv: VARIANTS = NEIGHBORS
    data, O, C, F, _ = rn.load()
    H, L = (pd.DataFrame({s: df.set_index(pd.to_datetime(df.ts, unit="ms"))[k] for s, df in data.items()}).sort_index()
            for k in ("high", "low"))
    days = O.index[O.index >= rn.START]
    r30 = ru.vol_rank(data, 30, 120)
    universes = {"top 7 (paper bot)": ru.members_top(r30, days, 7),
                 "top 7, no BTC/ETH (candidate)": ru.members_top_excluding(r30, days, 7)}
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    print(f"ratio trend exits, ${AMOUNT} x{rn.LEV} per unit, {days[0].date()} → {days[-1].date()}; "
          f"'up→loss %' = of the pair trades that reached +${TURNED:g}, the share closed at a loss\n")
    for uname, members in universes.items():
        sig = rn.signals(C, days, members)
        rows = []
        for vname, rule in VARIANTS.items():
            held = held_pairs(C, days, sig, rule)
            pairs_df, _ = rn.simulate(O, F, days, held, "pairs")
            net_df, _ = rn.simulate_netted_stop(O, H, L, F, days, held)
            row = {"exit": vname, **trade_stats(pair_trades(O, F, days, held))}
            row.update({f"PAIRS {k}": v for k, v in book(pairs_df).items() if k != "fees"})
            row.update({f"NET {k}": v for k, v in book(net_df).items()})
            rows.append(row)
        print(f"── {uname}")
        print(pd.DataFrame(rows).set_index("exit").to_string(), "\n")


if __name__ == "__main__":
    main()
