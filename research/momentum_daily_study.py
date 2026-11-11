"""
momentum_ls daily (the basket the real accounts run since 2026-11-11, --mom-daily): two improvements, owner's request
2026-11-11.

1. The short side. Over 2019 → 2026-10 the weekly bot's shorts made $33 of its $2,200, and they are what the squeezes
   hit (AGT +205% in a day on 2026-11-11). Variants: full shorts, half-size shorts, no shorts, shorts only while BTC
   closes under its 200-day average (a falling market).
2. A buffer before a coin leaves. Today a long leaves the moment it is no longer in the strongest 5; with buffer B it
   stays while it is in the strongest B (shorts the same at the weak end), and the basket is filled back to 5 from the
   top. Fewer exits and re-entries, fewer fees.

The simulator: every day, rank the top 50 by 30-day volume (60+ days of history) on their last 14 days' return at
that day's close; trade at the next open; a coin still wanted on the same side is held as it is; each leg $20 margin
x2 (shorts x their weight), stop 40% of the price checked on each day's high/low (a gap fills at the open), fees 0.04%
a side, the real daily funding where cached (missing = 0). A stopped coin may come back the next day if still picked.

Chosen on before 2024 only (Sharpe of daily PnL), judged on 2024 → 2026-10, which played no part in the choice.

  python -X utf8 research/momentum_daily_study.py
"""
import sys, pickle, math
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import short_study as ss
import pump_momentum_study as pm

AMOUNT, LEV, FEE, STOP, N = 20, 2, 0.0004, 0.40, 5
CUT = pd.Timestamp("2024-01-01")


def load():
    data = pickle.loads((ss.CACHE / "universe_daily.pkl").read_bytes())
    fund_raw = pickle.loads((ss.CACHE / "universe_funding.pkl").read_bytes())
    rk = pm.rank_table(data, 60)
    piv = lambda col: pd.DataFrame({s: df.set_index(pd.to_datetime(df.ts, unit="ms"))[col] for s, df in data.items()}).sort_index()
    O, H, L, C = piv("open"), piv("high"), piv("low"), piv("close")
    syms = list(C.columns)
    rk = rk.reindex(index=C.index, columns=syms)
    past = C / C.shift(14) - 1
    btc = C["BTCUSDT"]; bear = (btc < btc.rolling(200).mean()).reindex(C.index).fillna(False).values
    ts = np.array([int(d.timestamp() * 1000) for d in C.index], dtype=np.int64)   # ms, whatever unit the index holds
    F = np.zeros(C.shape)
    for j, s in enumerate(syms):
        f = fund_raw.get(s, {})
        if f: F[:, j] = [f.get(int(t), 0.0) for t in ts]
    # the day's ranking, shared by every variant: eligible coin indexes, weakest first
    R, Pv = rk.values, past.values
    ranked = []
    for i in range(len(C)):
        ok = np.where((R[i] <= 50) & ~np.isnan(Pv[i]))[0]
        ranked.append(ok[np.argsort(Pv[i, ok], kind="stable")] if len(ok) >= 20 else None)
    return dict(O=O.values, H=H.values, L=L.values, C=C.values, F=F, ts=ts, syms=syms, ranked=ranked, bear=bear, dates=C.index)


def simulate(M, buffer=5, shorts="full"):
    """trades [{entry_ts, exit_ts, side, pnl}] of the daily basket with this buffer and short mode."""
    O, H, L, C, F, ts, ranked, bear = M["O"], M["H"], M["L"], M["C"], M["F"], M["ts"], M["ranked"], M["bear"]
    w_short = {"full": 1.0, "half": 0.5, "none": 0.0, "bear": 1.0}[shorts]
    pos, trades, last_close = {}, [], {}          # pos: j -> dict(side, e, q, stop, k0, fu)

    def close(j, k, x):
        p = pos.pop(j); sg = 1 if p["side"] == "long" else -1
        if not np.isfinite(x): x = last_close.get(j, p["e"])          # a missing price: the last close
        trades.append({"entry_ts": int(ts[p["k0"]]), "exit_ts": int(ts[k]), "side": p["side"],
                       "pnl": sg * (x - p["e"]) * p["q"] - (p["e"] + x) * p["q"] * FEE + p["fu"]})

    for i in range(len(ts) - 1):
        k = i + 1
        order = ranked[i]
        if order is not None:
            short_on = shorts in ("full", "half") or (shorts == "bear" and bear[i])
            strong, weak = list(order[::-1]), list(order)
            want = {}
            for side, lst, on in (("long", strong, True), ("short", weak, short_on)):
                if not on: continue
                keep = [j for j in lst[:buffer] if j in pos and pos[j]["side"] == side]
                picks = keep + [j for j in lst if j not in keep and j not in want][:N - len(keep)]
                for j in picks[:N]: want[j] = side
            for j in [j for j in pos if want.get(j) != pos[j]["side"]]:
                x = O[k, j] if not np.isnan(O[k, j]) else last_close.get(j, pos[j]["e"])
                close(j, k, x)
            for j, side in want.items():
                if j in pos or np.isnan(O[k, j]): continue
                e = O[k, j]; w = 1.0 if side == "long" else w_short
                if w <= 0: continue
                sg = 1 if side == "long" else -1
                pos[j] = {"side": side, "e": e, "q": AMOUNT * LEV * w / e, "stop": e * (1 - sg * STOP), "k0": k, "fu": 0.0}
        for j in list(pos):
            p = pos[j]
            if np.isnan(H[k, j]):                                   # delisted / no bar: out at the last close
                close(j, k, last_close.get(j, p["e"])); continue
            if p["side"] == "long" and L[k, j] <= p["stop"]:
                close(j, k, min(O[k, j], p["stop"])); continue
            if p["side"] == "short" and H[k, j] >= p["stop"]:
                close(j, k, max(O[k, j], p["stop"])); continue
            if np.isnan(C[k, j]): continue
            sg = 1 if p["side"] == "long" else -1
            p["fu"] += -sg * p["q"] * C[k, j] * F[k, j]
            last_close[j] = C[k, j]
    k = len(ts) - 1
    for j in list(pos): close(j, k, last_close.get(j, pos[j]["e"]))
    return trades


def main():
    M = load()
    print("data until", M["dates"].max().date(), "| coins", len(M["syms"]))
    rows = []
    for buffer in (5, 7, 10, 15):
        for shorts in ("full", "half", "none", "bear"):
            tr = simulate(M, buffer, shorts)
            r = ss.summary(tr, f"buffer {buffer:>2} · shorts {shorts}")
            t = pd.DataFrame(tr)
            r["long"] = round(t[t.side == "long"].pnl.sum()); r["short"] = round(t[t.side == "short"].pnl.sum())
            rows.append(r)
    out = pd.DataFrame([{k: v for k, v in r.items() if k != "_daily"} for r in rows]).set_index("variant")
    pd.set_option("display.width", 300); pd.set_option("display.max_columns", 30)
    cols = ["trades", "win%", "pnl", "long", "short", "maxDD", "is_sharpe", "oos_sharpe", "oos_pnl", "2020", "2021", "2022", "2023", "2024", "2025", "2026"]
    print(out[[c for c in cols if c in out]].to_string())
    best = out.is_sharpe.idxmax()
    print(f"\nchosen on before 2024: {best} (Sharpe {out.loc[best, 'is_sharpe']} before, {out.loc[best, 'oos_sharpe']} after)")
    print("rank correlation of Sharpe, before vs after:", round(out.is_sharpe.rank().corr(out.oos_sharpe.rank()), 2))


if __name__ == "__main__":
    main()
