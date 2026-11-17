"""
momentum_ls daily (keep), roadmap 2.3, 2026-11-17: size each leg by its volatility instead of the same $20 for all.
Moskowitz, Ooi & Pedersen (2012) scale every asset to the same volatility; Kim, Tse & Wald (2016) find most of
time-series momentum's risk-adjusted gain comes from that scaling. Here: a wild coin (ARIA, AGT, AKE in the paper
run) gets a smaller leg, a calm one a larger leg, so one 40% stop no longer costs the same as on a calm coin.

A leg's margin = $20 x clip(ref / vol, lo, hi):
- vol = the coin's standard deviation of daily returns over L days, at the ranking close;
- ref = the median vol of that day's ranked top-50 coins, so a typical coin keeps $20.
The basket, the ranking, the stop (40% of the price), fees, funding: momentum_daily_study.py, unchanged. A leg keeps
its size while held (the bot sets it at entry).

Fixed before any result:
- L in {20, 60} days x clip in {[0.25, 2] (shrink and grow), [0.25, 1] (shrink only)}, buffer 5 and 7.
- Smaller legs use less capital, so PnL is also shown "per $ of average margin" (scaled to the baseline's average),
  and the pick is by Sharpe, which the scale doesn't change.
- The pick: the best Sharpe before 2024 among the 4 sized variants at buffer 5. It is adopted only if it beats the
  baseline's Sharpe after 2024 as well, and its neighbours (L 30/45, hi 1.5) agree.

  python -X utf8 research/momentum_volsize_study.py
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import short_study as ss
import momentum_daily_study as md


def vol_table(M, L):
    C = M["C"]
    r = np.full(C.shape, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        r[1:] = C[1:] / C[:-1] - 1
    v = pd.DataFrame(r).rolling(L, min_periods=L).std().values
    ref = np.array([np.nanmedian(v[i, o]) if o is not None and np.isfinite(v[i, o]).any() else np.nan
                    for i, o in enumerate(M["ranked"])])
    return v, ref


def simulate_vol(M, buffer=5, L=None, lo=0.25, hi=2.0, V=None):
    """md.simulate (full shorts) with each new leg's margin scaled by ref / vol at the ranking close (L None = off).
    Returns (trades, average margin in use per day)."""
    O, H, L_, C, F, ts, ranked = M["O"], M["H"], M["L"], M["C"], M["F"], M["ts"], M["ranked"]
    N, AMOUNT, LEV, FEE, STOP = md.N, md.AMOUNT, md.LEV, md.FEE, md.STOP
    v, ref = V if V is not None else (vol_table(M, L) if L else (None, None))
    pos, trades, last_close, used = {}, [], {}, []

    def close(j, k, x):
        p = pos.pop(j); sg = 1 if p["side"] == "long" else -1
        if not np.isfinite(x): x = last_close.get(j, p["e"])
        trades.append({"entry_ts": int(ts[p["k0"]]), "exit_ts": int(ts[k]), "side": p["side"], "w": p["w"],
                       "pnl": sg * (x - p["e"]) * p["q"] - (p["e"] + x) * p["q"] * FEE + p["fu"]})

    for i in range(len(ts) - 1):
        k = i + 1
        order = ranked[i]
        if order is not None:
            strong, weak = list(order[::-1]), list(order)
            want = {}
            for side, lst in (("long", strong), ("short", weak)):
                keep = [j for j in lst[:buffer] if j in pos and pos[j]["side"] == side]
                picks = keep + [j for j in lst if j not in keep and j not in want][:N - len(keep)]
                for j in picks[:N]: want[j] = side
            for j in [j for j in pos if want.get(j) != pos[j]["side"]]:
                close(j, k, O[k, j] if not np.isnan(O[k, j]) else last_close.get(j, pos[j]["e"]))
            for j, side in want.items():
                if j in pos or np.isnan(O[k, j]): continue
                w = 1.0
                if v is not None:
                    w = float(np.clip(ref[i] / v[i, j], lo, hi)) if np.isfinite(v[i, j]) and v[i, j] > 0 and np.isfinite(ref[i]) else 1.0
                e = O[k, j]; sg = 1 if side == "long" else -1
                pos[j] = {"side": side, "e": e, "q": AMOUNT * w * LEV / e, "stop": e * (1 - sg * STOP), "k0": k, "fu": 0.0, "w": w}
        used.append(sum(AMOUNT * p["w"] for p in pos.values()))
        for j in list(pos):
            p = pos[j]; sg = 1 if p["side"] == "long" else -1
            if np.isnan(H[k, j]): close(j, k, last_close.get(j, p["e"])); continue
            if sg > 0 and L_[k, j] <= p["stop"]: close(j, k, min(O[k, j], p["stop"])); continue
            if sg < 0 and H[k, j] >= p["stop"]: close(j, k, max(O[k, j], p["stop"])); continue
            if np.isnan(C[k, j]): continue
            p["fu"] += -sg * p["q"] * C[k, j] * F[k, j]
            last_close[j] = C[k, j]
    k = len(ts) - 1
    for j in list(pos): close(j, k, last_close.get(j, pos[j]["e"]))
    u = np.array(used); return trades, float(u[u > 0].mean())


def row(M, label, buffer, L, lo, hi, base_used, vols):
    tr, used = simulate_vol(M, buffer, L, lo, hi, vols.get(L))
    r = ss.summary(tr, label); t = pd.DataFrame(tr)
    k = base_used / used if base_used else 1.0
    stops = t[t.pnl <= -0.3 * md.AMOUNT * md.LEV * t.w]                     # a 40% stop costs ~0.4 x notional
    r.update({"avg_margin": round(used), "pnl_same_$": round(r["pnl"] * k), "dd_same_$": round(r["maxDD"] * k),
              "worst_leg": round(t.pnl.min(), 1), "stop_cost": round(-stops.pnl.sum()), "avg_w": round(t.w.mean(), 2)})
    return r, used


def main():
    M = md.load()
    print("data until", M["dates"].max().date(), "| coins", len(M["syms"]))
    vols = {L: vol_table(M, L) for L in (20, 30, 45, 60)}
    rows = []
    for buffer in (5, 7):
        base, bu = row(M, f"buffer {buffer} · same $20 (runs)", buffer, None, 0, 0, None, vols); rows.append(base)
        for L in (20, 60):
            for lo, hi in ((0.25, 2.0), (0.25, 1.0)):
                rows.append(row(M, f"buffer {buffer} · vol {L}d · clip {lo}-{hi}", buffer, L, lo, hi, bu, vols)[0])
    pd.set_option("display.width", 340); pd.set_option("display.max_columns", 40)
    cols = ["trades", "avg_w", "avg_margin", "pnl", "pnl_same_$", "maxDD", "dd_same_$", "is_sharpe", "oos_sharpe",
            "worst_leg", "stop_cost", "2021", "2022", "2023", "2024", "2025", "2026"]
    out = pd.DataFrame([{k: v for k, v in r.items() if k != "_daily"} for r in rows]).set_index("variant")
    print(out[[c for c in cols if c in out]].to_string())
    b5 = out[out.index.str.startswith("buffer 5 · vol")]
    pick = b5.is_sharpe.idxmax(); base = out.loc["buffer 5 · same $20 (runs)"]
    print(f"\npick (best Sharpe before 2024, buffer 5): {pick}: {out.loc[pick, 'is_sharpe']} / {out.loc[pick, 'oos_sharpe']} "
          f"against {base.is_sharpe} / {base.oos_sharpe}")
    # neighbours of the pick, after the pick
    L0 = int(pick.split("vol ")[1].split("d")[0]); hi0 = float(pick.split("-")[-1])
    nb = []
    for L in sorted({20, 30, 45, 60} - {L0}):
        nb.append(row(M, f"neighbour · vol {L}d · clip 0.25-{hi0}", 5, L, 0.25, hi0, None, vols)[0])
    for hi in (1.5,) if hi0 != 1.5 else (2.0,):
        nb.append(row(M, f"neighbour · vol {L0}d · clip 0.25-{hi}", 5, L0, 0.25, hi, None, vols)[0])
    nbo = pd.DataFrame([{k: v for k, v in r.items() if k != "_daily"} for r in nb]).set_index("variant")
    print(nbo[["pnl", "maxDD", "is_sharpe", "oos_sharpe", "2025", "2026"]].to_string())


if __name__ == "__main__":
    main()
