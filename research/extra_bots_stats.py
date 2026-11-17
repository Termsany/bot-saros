"""
The rest of the paper bots on the site's backtest page (owner, 2026-11-17: "add all the bots to the backtest"), next
to the four of research/bots_stats.py. Same data and rules as the studies: every Binance USDT-M perpetual since 2019
(delisted included), coins chosen by volume at the time, fees 0.04%, real funding, $20 margin x2 per position (per
leg), x2 only. Each bot is simulated as its paper bot runs:

  momentum_daily      momentum_daily_study.py: the 14-day ranking every day, coins still in the basket kept
  momentum_daily_b7   ... a held coin stays while among the strongest/weakest 7 (§37)
  momentum_daily_vol  ... each new leg's margin scaled by its 60-day volatility (§39)
  rsi2_pullback       traders_study.py: top 10, close > 200-day average, RSI-2 < 5, out above the 5-day average / 10 days
  rsi2_btc            ... and BTC's close above its 200-day average (§28)
  vol_breakout        traders_study.py: top 10, open + 0.7 x yesterday's range, yesterday's close > 20-day average
  trend_breakout      top 100, close > 50 > 150 > 200-day averages, a close above the previous 20-day high -> next
                      open; out after a close below the 20-day average; stop 40%
  ratio_nobtc         ratio_exit_study.py: every pair of the weekly top 7 without BTC/ETH, the 50-day cross (§25)
  ratio_trail         ... out when the ratio falls 20% from its best since entry (§35)
  ratio_trail_btc     the top 7 with BTC/ETH, the same trail

Not here: retail_fade (its crowd data starts 2021-12 and lives on the server only) and the weekly Wednesday basket
(the page's Momentum L/S is the weekly basket).

Writes lib/extra-stats.json (the numbers the page lists) and data/extra-trades.json (every trade, served by
app/api/bot-trades). Never edit those by hand.

  python -X utf8 research/extra_bots_stats.py
"""
import sys, json, math, pickle
from datetime import datetime, timezone
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import short_study as ss
import pump_momentum_study as pm
import bots_stats as bs
import traders_study as ts
import momentum_daily_study as md
import momentum_volsize_study as mv
import ratio_netting_study as rn
import ratio_universe_study as ru
import ratio_exit_study as rx

ROOT = Path(__file__).resolve().parent.parent
AMOUNT, LEV, FEE = 20, 2, 0.0004
ORDER = ["momentum_daily", "momentum_daily_b7", "momentum_daily_vol", "rsi2_pullback", "rsi2_btc", "vol_breakout",
         "trend_breakout", "ratio_nobtc", "ratio_trail", "ratio_trail_btc"]


# ── momentum daily (keep), with a buffer or volatility sizing ──
def momentum_daily(M, buffer=5, vol=None):
    O, H, L, C, F, ts_, ranked, syms = M["O"], M["H"], M["L"], M["C"], M["F"], M["ts"], M["ranked"], M["syms"]
    v, ref = mv.vol_table(M, vol) if vol else (None, None)
    pos, trades, last_close = {}, [], {}

    def close(j, k, x, why):
        p = pos.pop(j); sg = 1 if p["side"] == "long" else -1
        if not np.isfinite(x): x = last_close.get(j, p["e"])
        trades.append({"symbol": syms[j], "entry_ts": int(ts_[p["k0"]]), "exit_ts": int(ts_[k]), "side": p["side"],
                       "entry": float(p["e"]), "exit": float(x), "qty": p["q"], "reason": why,
                       "pnl": sg * (x - p["e"]) * p["q"] - (p["e"] + x) * p["q"] * FEE + p["fu"]})

    for i in range(len(ts_) - 1):
        k = i + 1; order = ranked[i]
        if order is not None:
            strong, weak = list(order[::-1]), list(order)
            want = {}
            for side, lst in (("long", strong), ("short", weak)):
                keep = [j for j in lst[:buffer] if j in pos and pos[j]["side"] == side]
                picks = keep + [j for j in lst if j not in keep and j not in want][:md.N - len(keep)]
                for j in picks[:md.N]: want[j] = side
            for j in [j for j in pos if want.get(j) != pos[j]["side"]]:
                close(j, k, O[k, j] if not np.isnan(O[k, j]) else last_close.get(j, pos[j]["e"]), "day")
            for j, side in want.items():
                if j in pos or np.isnan(O[k, j]): continue
                w = 1.0
                if v is not None and np.isfinite(v[i, j]) and v[i, j] > 0 and np.isfinite(ref[i]):
                    w = float(np.clip(ref[i] / v[i, j], 0.25, 2.0))
                e = O[k, j]; sg = 1 if side == "long" else -1
                pos[j] = {"side": side, "e": e, "q": AMOUNT * w * LEV / e, "stop": e * (1 - sg * md.STOP), "k0": k, "fu": 0.0}
        for j in list(pos):
            p = pos[j]; sg = 1 if p["side"] == "long" else -1
            if np.isnan(H[k, j]): close(j, k, last_close.get(j, p["e"]), "delisted/end"); continue
            if sg > 0 and L[k, j] <= p["stop"]: close(j, k, min(O[k, j], p["stop"]), "stop"); continue
            if sg < 0 and H[k, j] >= p["stop"]: close(j, k, max(O[k, j], p["stop"]), "stop"); continue
            if np.isnan(C[k, j]): continue
            p["fu"] += -sg * p["q"] * C[k, j] * F[k, j]
            last_close[j] = C[k, j]
    k = len(ts_) - 1
    for j in list(pos): close(j, k, last_close.get(j, pos[j]["e"]), "delisted/end")
    return trades


# ── RSI-2 with the BTC filter (traders_study.rsi2_trades + BTC above its 200-day average at the signal close) ──
def rsi2_btc(A, btc200, top=10, T=5):
    out = []
    for s, a in A.items():
        o, l, c = a["o"], a["l"], a["c"]; n = len(c)
        if n < 210: continue
        r2, m5, m200 = ts.rsi(c, 2), ts.sma(c, 5), ts.sma(c, 200)
        i = 200
        while i < n - 2:
            ok = a["rk"][i + 1] <= top and r2[i] < T and c[i] > m200[i] and btc200.get(int(a["ts"][i]), False)
            if not ok: i += 1; continue
            k = i + 1; e = o[k]; stop = e * (1 - 0.8 / LEV); done = None
            for j in range(k, min(n, k + 10)):
                if l[j] <= stop: done = (j, min(o[j], stop), "stop"); break
                if j + 1 < n and c[j] > m5[j]: done = (j + 1, o[j + 1], "signal"); break
            if done is None:
                j = min(n - 1, k + 10); done = (j, o[j], "time")
            j, x, why = done
            out.append(ts.long_trade(a, k, e, j, x, why, s)); i = j
    return out


# ── trend-template breakout (bots/trend_breakout.py TB) ──
def trend_breakout(A, top=100, L=20, exit_ma=20, slip=0.0005):
    out = []
    for s, a in A.items():
        o, h, l, c = a["o"], a["h"], a["l"], a["c"]; n = len(c)
        if n < 210: continue
        m50, m150, m200, mx = ts.sma(c, 50), ts.sma(c, 150), ts.sma(c, 200), ts.sma(c, exit_ma)
        box_hi = pd.Series(h).rolling(L).max().shift(1).values
        i = 200
        while i < n - 2:
            if not (a["rk"][i + 1] <= top and c[i] > m50[i] > m150[i] > m200[i] and c[i] > box_hi[i]): i += 1; continue
            k = i + 1; e = o[k] * (1 + slip); stop = e * (1 - 0.8 / LEV); done = None
            for j in range(k, n):
                if l[j] <= stop: done = (j, min(o[j], stop), "stop"); break
                if j + 1 < n and c[j] < mx[j]: done = (j + 1, o[j + 1], f"below {exit_ma}d avg"); break
            if done is None: done = (n - 1, c[-1], "delisted/end")
            j, x, why = done
            out.append(ts.long_trade(a, k, e, j, x, why, s)); i = j
    return out


# ── ratio pairs, as the paper bots book them (ratio_exit_study.pair_trades), with dates and why each closed ──
def ratio_pairs(O, F, days, held, sig):
    k = AMOUNT / rn.AMOUNT                                   # the studies' $26 a leg -> $20
    open_, out = {}, []
    for i, d in enumerate(days[:-2]):
        h = held.get(d, {}); t0, t1 = days[i + 1], days[i + 2]
        ret = (O.loc[t1] / O.loc[t0] - 1).fillna(0.0); fnd = F.loc[t0]
        for p in sorted(set(open_) | set(h)):
            if p in open_ and (p not in h or h[p] != open_[p]["sg"]):
                t = open_.pop(p); s_now = sig.get(d, {}).get(p)
                why = "left the list" if s_now is None else "flip" if s_now != t["sg"] else "trail"
                out.append({"pair": f"{p[0]}/{p[1]}" if t["sg"] > 0 else f"{p[1]}/{p[0]}", "side": "pair", "entry_ts": t["t0"],
                            "exit_ts": int(t0.value // 10**6), "entry": 0.0, "exit": 0.0, "reason": why, "pnl": (t["pnl"] - 2 * rn.N * FEE) * k})
            if p in h:
                if p not in open_: open_[p] = {"sg": h[p], "pnl": -2 * rn.N * FEE, "t0": int(t0.value // 10**6)}
                t = open_[p]
                t["pnl"] += sum(u * rn.N * ret.get(c, 0.0) - u * rn.N * fnd.get(c, 0.0) for c, u in rn.legs(p, h[p]).items())
    last = int(days[-1].value // 10**6)
    for p, t in open_.items():
        out.append({"pair": f"{p[0]}/{p[1]}" if t["sg"] > 0 else f"{p[1]}/{p[0]}", "side": "pair", "entry_ts": t["t0"], "exit_ts": last,
                    "entry": 0.0, "exit": 0.0, "reason": "delisted/end", "pnl": (t["pnl"] - 2 * rn.N * FEE) * k})
    return out


def main():
    data = pickle.loads((ss.CACHE / "universe_daily.pkl").read_bytes())
    fund_raw = pickle.loads((ss.CACHE / "universe_funding.pkl").read_bytes())
    fund = {s: fund_raw.get(s, {}) for s in data}
    bots = {}
    M = md.load()
    bots["momentum_daily"] = momentum_daily(M)
    bots["momentum_daily_b7"] = momentum_daily(M, buffer=7)
    bots["momentum_daily_vol"] = momentum_daily(M, vol=60)
    A = ts.coin_arrays(data, fund, pm.rank_table(data, 60))
    b = data["BTCUSDT"]; mb = b.close.rolling(200).mean()
    btc200 = dict(zip(b.ts.astype("int64"), (b.close > mb) & mb.notna()))
    bots["rsi2_pullback"] = ts.rsi2_trades(A, 10, 5, True, "sma5")
    bots["rsi2_btc"] = rsi2_btc(A, btc200)
    bots["vol_breakout"] = ts.vb_trades(A, 10, 0.7, 20)
    bots["trend_breakout"] = trend_breakout(A)
    _, O, C, F, _ = rn.load()
    days = O.index[O.index >= rn.START]
    r30 = ru.vol_rank(data, 30, 120)
    for k, members, rule in (("ratio_nobtc", ru.members_top_excluding(r30, days, 7), {}),
                             ("ratio_trail", ru.members_top_excluding(r30, days, 7), {"trail": 0.20}),
                             ("ratio_trail_btc", ru.members_top(r30, days, 7), {"trail": 0.20})):
        sig = rn.signals(C, days, members)
        bots[k] = ratio_pairs(O, F, days, rx.held_pairs(C, days, sig, rule), sig)

    mn = bs.binance_min_notional()
    out, ends = {}, []
    for k in ORDER:
        tr = bots[k]
        d = ss.summary(tr, k)["_daily"]; ends.append(d.index.max())
        out[k] = bs.stats(tr, d)
        m, cap, mx = bs.min_capital(tr, out[k]["maxDD"], mn, 2 if k.startswith("ratio") else 1)
        out[k].update({"minMargin": m, "minCapital": cap, "maxOpen": mx,
                       "testedCapital": int(math.ceil((AMOUNT * mx + out[k]["maxDD"]) / 10) * 10)})
        v = out[k]
        print(f"  {k:<19} trades {v['trades']:>6} WR {v['winRate']:>5}% PF {v['pf']:>5} pnl {v['pnl']:>9} DD {v['maxDD']:>7} "
              f"sharpe {v['sharpeIn']}/{v['sharpeOut']}  open {mx:>3}  min ${cap}")
    meta = {"generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "to": str(max(ends).date()), "marginUsdt": AMOUNT,
            "leverage": LEV, "feePct": FEE, "outOfSampleFrom": "2024-01-01",
            "universe": "all Binance USDT-M perpetuals since 2019, delisted included", "symbolsTested": len(data)}
    (ROOT / "lib" / "extra-stats.json").write_bytes((json.dumps({"meta": meta, "bots": out}, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    sym = lambda t: (t.get("pair") or t.get("symbol") or "").replace("USDT", "")
    rows = {k: {str(LEV): [[int(t["entry_ts"]), int(t["exit_ts"]), sym(t), t["side"], round(float(t["entry"]), 8), round(float(t["exit"]), 8),
                            round(float(t["pnl"]), 4), t.get("reason", "")] for t in sorted(bots[k], key=lambda t: t["entry_ts"])]} for k in ORDER}
    p = ROOT / "data" / "extra-trades.json"
    p.write_bytes(json.dumps({"meta": {**meta, "fields": ["entry_ts", "exit_ts", "symbol", "side", "entry", "exit", "pnl", "reason"]},
                              "trades": rows}, separators=(",", ":")).encode("utf-8"))
    print(f"wrote lib/extra-stats.json and {p.relative_to(ROOT)} ({p.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
