"""
momentum_ls daily (keep), owner's idea 2026-11-16: once a leg is up X% (long or short), move its stop to the entry
price, so a winner that turns cannot become a loss. X is measured on the margin as the page shows it (2x leverage:
40% on the margin = a 20% price move); several levels are tried so one lucky number is not picked.

Daily bars hide the order of the day's high and low, so the day the trigger is reached is done two ways:
- "next":  the stop moves to the entry from the next day (the day's own return to the entry is not seen);
- "same":  pessimistic: if the trigger and the entry are both inside the day's range, the leg is out at the entry.
The truth is between the two. Everything else is momentum_daily_study.py (§37): top 50 by volume, 14-day return,
5 + 5 legs, $20 x2, stop 40%, fees 0.04%, real funding, chosen before 2024 and judged on 2024 →.

  python -X utf8 research/momentum_breakeven_study.py
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import short_study as ss
import momentum_daily_study as md


HOURS = ss.CACHE / "be_hours.pkl"          # {(symbol, day_ms): [(high, low), ...] hourly}, fetched on demand
_hours = None


def hours(sym, day_ms):
    """the day's 24 hourly (high, low) from Binance, cached; None when Binance has none (delisted, no data)."""
    global _hours
    import pickle, json, time, urllib.request
    if _hours is None: _hours = pickle.loads(HOURS.read_bytes()) if HOURS.exists() else {}
    key = (sym, int(day_ms))
    if key not in _hours:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=1h&startTime={int(day_ms)}&limit=24"
        rows = None
        for a in range(4):
            try:
                with urllib.request.urlopen(url, timeout=20) as r: rows = json.loads(r.read()); break
            except Exception: time.sleep(1 + a)
        _hours[key] = [(float(x[2]), float(x[3])) for x in rows if int(x[0]) < day_ms + 86_400_000] if rows else None
        if len(_hours) % 200 == 0: HOURS.write_bytes(pickle.dumps(_hours))
    return _hours[key]


def save_hours():
    import pickle
    if _hours is not None: HOURS.write_bytes(pickle.dumps(_hours))


def first_hit(sym, day_ms, sg, trig_px, entry):
    """on a day whose range holds both the trigger and the entry: 'trigger' when the trigger comes first and the price
    is back at the entry later that day, 'clear' when the trigger comes first and the entry is not revisited after,
    'entry' when the entry comes first (then the trigger: the stop moves, the leg stays). Ties in an hour: pessimistic."""
    hs = hours(sym, day_ms)
    if not hs: return "trigger"
    for i, (h, l) in enumerate(hs):
        up = h >= trig_px if sg > 0 else l <= trig_px
        if not up: continue
        rest = hs[i + 1:]
        back_same = (l <= entry if sg > 0 else h >= entry)          # inside the trigger hour: unknown order -> pessimistic
        back_later = any((lo <= entry if sg > 0 else hi >= entry) for hi, lo in rest)
        return "trigger" if back_same or back_later else "clear"
    return "clear"


def simulate_be(M, buffer=5, trig=None, mode="next"):
    """md.simulate (full shorts) plus a breakeven stop once the leg is up `trig` on the margin (None = off)."""
    O, H, L, C, F, ts, ranked = M["O"], M["H"], M["L"], M["C"], M["F"], M["ts"], M["ranked"]
    N, AMOUNT, LEV, FEE, STOP = md.N, md.AMOUNT, md.LEV, md.FEE, md.STOP
    move = None if trig is None else trig / LEV                 # price move that makes `trig` on the margin
    pos, trades, last_close = {}, [], {}

    def close(j, k, x, why):
        p = pos.pop(j); sg = 1 if p["side"] == "long" else -1
        if not np.isfinite(x): x = last_close.get(j, p["e"])
        trades.append({"entry_ts": int(ts[p["k0"]]), "exit_ts": int(ts[k]), "side": p["side"], "why": why, "be": p["be"],
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
                x = O[k, j] if not np.isnan(O[k, j]) else last_close.get(j, pos[j]["e"])
                close(j, k, x, "rebal")
            for j, side in want.items():
                if j in pos or np.isnan(O[k, j]): continue
                e = O[k, j]; sg = 1 if side == "long" else -1
                pos[j] = {"side": side, "e": e, "q": AMOUNT * LEV / e, "stop": e * (1 - sg * STOP), "k0": k, "fu": 0.0, "be": False}
        for j in list(pos):
            p = pos[j]; sg = 1 if p["side"] == "long" else -1
            if np.isnan(H[k, j]):
                close(j, k, last_close.get(j, p["e"]), "gone"); continue
            if sg > 0 and L[k, j] <= p["stop"]:
                close(j, k, min(O[k, j], p["stop"]), "be" if p["be"] else "stop"); continue
            if sg < 0 and H[k, j] >= p["stop"]:
                close(j, k, max(O[k, j], p["stop"]), "be" if p["be"] else "stop"); continue
            if move is not None and not p["be"]:
                hit = H[k, j] >= p["e"] * (1 + move) if sg > 0 else L[k, j] <= p["e"] * (1 - move)
                if hit:
                    p["be"] = True; p["stop"] = p["e"]
                    back = L[k, j] <= p["e"] if sg > 0 else H[k, j] >= p["e"]
                    if mode == "same" and back:
                        close(j, k, p["e"], "be"); continue
                    if mode == "exact" and back:
                        tp = p["e"] * (1 + sg * move)
                        if first_hit(M["syms"][j], ts[k], sg, tp, p["e"]) == "trigger":
                            close(j, k, p["e"], "be"); continue
            if np.isnan(C[k, j]): continue
            p["fu"] += -sg * p["q"] * C[k, j] * F[k, j]
            last_close[j] = C[k, j]
    k = len(ts) - 1
    for j in list(pos): close(j, k, last_close.get(j, pos[j]["e"]), "end")
    return trades


def main():
    M = md.load()
    print("data until", M["dates"].max().date(), "| coins", len(M["syms"]))
    rows = []
    for buffer in (5, 7):
        for trig, mode in [(None, "-")] + [(t, m) for t in (0.2, 0.4, 0.6, 0.8, 1.2) for m in ("next", "exact", "same")]:
            tr = simulate_be(M, buffer, trig, mode)
            lab = f"buffer {buffer} · " + ("no breakeven (runs)" if trig is None else f"BE at +{int(trig * 100)}% margin · {mode}")
            r = ss.summary(tr, lab); t = pd.DataFrame(tr)
            r["stops"] = int((t.why == "stop").sum()); r["be_exits"] = int((t.why == "be").sum())
            r["2026"] = r.get("2026", 0)
            rows.append(r); save_hours()
            print(f"  done: {lab}", flush=True)
    out = pd.DataFrame([{k: v for k, v in r.items() if k != "_daily"} for r in rows]).set_index("variant")
    pd.set_option("display.width", 320); pd.set_option("display.max_columns", 30)
    cols = ["trades", "win%", "pnl", "maxDD", "is_sharpe", "oos_sharpe", "oos_pnl", "stops", "be_exits", "2021", "2022", "2023", "2024", "2025", "2026"]
    print(out[[c for c in cols if c in out]].to_string())


if __name__ == "__main__":
    main()
