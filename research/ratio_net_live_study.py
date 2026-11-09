"""
The netted ratio trend as the live bot will trade it (owner, 2026-11-09: "build netting", for real money without
BTC/ETH). research/ratio_netting_study.py's NETTED + 40% stop trades only the change in a coin's units; the bot's
first version closes a coin's whole position and reopens it at the new size whenever its units change (one exit and
one entry through the basket engine, a fresh 40% stop from the new entry). This prices that difference — fees on
|old| + |new| units instead of |new − old| — on the universe the owner wants (30-day top 7 without BTC/ETH, §25), and
on the one the Demo runs (with them).

  python -X utf8 research/ratio_net_live_study.py
"""
import sys, math
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ratio_netting_study as rn
import ratio_universe_study as ru

N, FEE, AMOUNT = rn.N, rn.FEE, rn.AMOUNT


def simulate(O, H, L, F, days, sig, stop=0.40, reopen=False):
    """rn.simulate_netted_stop, with reopen=True charging a change as a full close and a full reopen."""
    tgt_prev = {}; held = {}; entry = {}; stopped = set(); rows = []; changes = 0
    for i, d in enumerate(days[:-2]):
        tgt = {}
        for p, sg in sig.get(d, {}).items():
            for c, u in rn.legs(p, sg).items(): tgt[c] = tgt.get(c, 0) + u
        tgt = {c: u for c, u in tgt.items() if u}
        t0, t1 = days[i + 1], days[i + 2]
        traded = 0
        changed = {c for c in set(tgt) | set(tgt_prev) if tgt.get(c, 0) != tgt_prev.get(c, 0)}
        for c in changed:
            stopped.discard(c); entry[c] = O.at[t0, c]; changes += 1
        now = {c: u for c, u in tgt.items() if c not in stopped}
        if reopen:
            traded += sum(abs(held.get(c, 0)) + abs(now.get(c, 0)) for c in changed)
            traded += sum(abs(now.get(c, 0)) for c in set(now) - changed - set(held))   # a coin that couldn't open before
        else:
            traded += sum(abs(now.get(c, 0) - held.get(c, 0)) for c in set(now) | set(held))
        gross = funding = 0.0
        for c, u in now.items():
            o, e = O.at[t0, c], entry[c]
            lvl = e * (1 - stop) if u > 0 else e * (1 + stop)
            hit = (L.at[t0, c] <= lvl) if u > 0 else (H.at[t0, c] >= lvl)
            if hit:
                px = min(o, lvl) if u > 0 else max(o, lvl)
                gross += u * N * (px / o - 1); stopped.add(c); traded += abs(u)
            else:
                gross += u * N * (O.at[t1, c] / o - 1)
            funding += u * N * F.at[t0, c]
        held = {c: u for c, u in now.items() if c not in stopped}
        fees = traded * N * FEE
        rows.append({"day": t0, "pnl": gross - funding - fees, "fees": fees, "funding": funding,
                     "gross_units": sum(abs(u) for u in now.values()), "pairs": 0})
        tgt_prev = tgt
    return pd.DataFrame(rows).set_index("day"), changes


def main():
    data, O, C, F, _ = rn.load()
    H, L = (pd.DataFrame({s: df.set_index(pd.to_datetime(df.ts, unit="ms"))[k] for s, df in data.items()}).sort_index()
            for k in ("high", "low"))
    days = O.index[O.index >= rn.START]
    r30 = ru.vol_rank(data, 30, 120)
    rows = []
    for label, members in (("vol30 top 7, no BTC/ETH", ru.members_top_excluding(r30, days, 7)), ("vol30 top 7", ru.members_top(r30, days, 7))):
        sig = rn.signals(C, days, members)
        for how, reopen in (("trade the change (research)", False), ("close + reopen (the bot)", True)):
            df, ch = simulate(O, H, L, F, days, sig, reopen=reopen)
            s = ru.stats(df, f"{label} · {how}")
            s["fees $"] = round(df.fees.sum()); s["changes/yr"] = round(ch / (len(days) / 365))
            rows.append(s)
    out = pd.DataFrame(rows).set_index("universe")
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    print(f"netted ratio trend + 40% stop per coin, ${AMOUNT} x{rn.LEV} per unit, {days[0].date()} → {days[-1].date()}\n")
    print(out.to_string())


if __name__ == "__main__":
    main()
