"""
Numbers the site shows for the four paper bots (lib/bot-stats.json) and every trade of their historical test
(public/bot-trades.json, used by the backtest page for the portfolio bots) — never edit those files by hand.
Same data and rules as the studies: every Binance USDT-M perpetual since 2019 (delisted included), coins chosen by
volume at the time, real funding, fees 0.04%, $20 margin x2 per position (per leg). "Out-of-sample" = from 2024.

  python research/bots_stats.py
"""
import sys, json, pickle, math
from datetime import datetime, timezone
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import short_study as ss
import pump_momentum_study as pm
import ratio_fairness as rf
import strategies_trend as st
from universe_study import ranks

ROOT = Path(__file__).resolve().parent.parent
CACHE = ss.CACHE
AMOUNT, LEV, FEE, CUT = ss.AMOUNT, ss.LEV, ss.FEE, ss.CUT


def stats(trades, daily):
    p = np.array([t["pnl"] for t in trades]); gw, gl = p[p > 0].sum(), -p[p <= 0].sum()
    eq = daily.cumsum(); sh = lambda x: round(float(x.mean() / x.std() * math.sqrt(365)), 2) if x.std() else 0.0
    monthly = eq.resample("MS").last().ffill()
    return {"trades": int(len(p)), "winRate": round(float((p > 0).mean() * 100), 1), "pf": round(float(gw / gl), 2) if gl else 99.0,
            "pnl": round(float(daily.sum()), 2), "maxDD": round(float((eq.cummax() - eq).max()), 2),
            "sharpeIn": sh(daily[daily.index < CUT]), "sharpeOut": sh(daily[daily.index >= CUT]),
            "pnlOut": round(float(daily[daily.index >= CUT].sum()), 2),
            "years": {str(y): round(float(v), 2) for y, v in daily.groupby(daily.index.year).sum().items() if y >= 2020},
            "equity": [[m.strftime("%Y-%m"), round(float(v), 2)] for m, v in monthly.items() if m.year >= 2020]}


LEVERAGES = (1, 2, 3, 5)


def binance_min_notional():
    """Smallest order value Binance USDT-M accepts per symbol (MIN_NOTIONAL: $5 for most, more for BTC/ETH)."""
    import urllib.request
    info = json.loads(urllib.request.urlopen("https://fapi.binance.com/fapi/v1/exchangeInfo", timeout=30).read())
    out = {}
    for x in info["symbols"]:
        f = {y["filterType"]: y for y in x["filters"]}
        if "MIN_NOTIONAL" in f: out[x["symbol"]] = float(f["MIN_NOTIONAL"]["notional"])
    return out


def min_capital(trades, max_dd, min_notional, legs_per_trade=1):
    """Smallest capital that runs the bot as tested (x2): margin per trade large enough for every trade of the last
    two years to meet the exchange minimum order, times the most positions open at once, plus the test's worst
    drawdown scaled to that margin. Returns (margin per trade, capital, most positions open)."""
    recent = [t for t in trades if pd.Timestamp(int(t["entry_ts"]), unit="ms") >= pd.Timestamp("2024-10-01")]
    need = 0.0
    for t in recent:
        syms = t["pair"].split("/") if t.get("pair") else [t["symbol"]]
        for sy in syms:
            notional = AMOUNT * LEV if t.get("pair") else float(t["qty"]) * float(t["entry"])   # at $20 margin
            if notional > 0: need = max(need, AMOUNT * min_notional.get(sy, 5.0) * 1.1 / notional)   # +10% for price moves / lot steps
    ev = sorted([(int(t["entry_ts"]), legs_per_trade) for t in trades] + [(int(t["exit_ts"]), -legs_per_trade) for t in trades])
    cur = mx = 0
    for _, d in ev: cur += d; mx = max(mx, cur)
    margin = max(need, 1.0)
    capital = margin * mx + max_dd * margin / AMOUNT
    return round(margin, 2), int(math.ceil(capital / 10) * 10), mx




def trades_at(lev, data, fund, rk10, ever10, rk100, new):
    """The trend, momentum and new-listing trades re-simulated at leverage `lev`: the protective stop moves to
    0.8 / leverage below (above) entry so it closes before the margin is liquidated (40% at x2, 16% at x5)."""
    ss.LEV = pm.LEV = lev                      # module constants the simulators read
    out = {"trend_daily": [], "listing_short": []}
    for s in ever10:
        df = data[s]; top10 = list((rk10[s].reindex(pd.to_datetime(df.ts, unit="ms")) <= 10).fillna(False))
        out["trend_daily"] += [dict(t, symbol=s) for t in st.run_trend_daily(list(df.open), list(df.high), list(df.low), list(df.close), list(df.ts),
                                                                             [fund[s].get(int(t), 0.0) for t in df.ts], AMOUNT, lev, FEE, 0, top10)]
    out["momentum_ls"] = [dict(t, symbol=s) for s, d, side in pm.momentum_positions(data, rk100, 2, True) if (t := pm.momentum_trade(data[s], fund[s], d, side))]
    lst = []
    for s in new: lst += [dict(t, symbol=s) for t in ss.run_listing_short(data[s], [fund[s].get(int(t), 0.0) for t in data[s].ts], 30, 90, min(0.4, 0.8 / lev))]
    out["listing_short"] = pm.cap(lst, 10)
    ss.LEV = pm.LEV = LEV
    return out


def main():
    data = pickle.loads((CACHE / "universe_daily.pkl").read_bytes())
    fund_raw = pickle.loads((CACHE / "universe_funding.pkl").read_bytes())
    fund = {s: fund_raw.get(s, {}) for s in data}
    rk10 = ranks(data); ever10 = [s for s in data if (rk10[s] <= 10).any()]; rk100 = pm.rank_table(data, 60)

    long_tr = []
    for s in ever10:
        df = data[s]; top10 = list((rk10[s].reindex(pd.to_datetime(df.ts, unit="ms")) <= 10).fillna(False))
        long_tr += [dict(t, symbol=s) for t in st.run_trend_daily(list(df.open), list(df.high), list(df.low), list(df.close), list(df.ts),
                                      [fund[s].get(int(t), 0.0) for t in df.ts], AMOUNT, LEV, FEE, 0, top10)]
    new = [s for s, df in data.items() if pd.to_datetime(df.ts.iloc[0], unit="ms") >= pd.Timestamp("2021-01-01")]
    lst = []
    for s in new: lst += [dict(t, symbol=s) for t in ss.run_listing_short(data[s], [fund[s].get(int(t), 0.0) for t in data[s].ts], 30, 90, 0.4)]
    bots = {
        "trend_daily": long_tr,
        "momentum_ls": [dict(t, symbol=s) for s, d, side in pm.momentum_positions(data, rk100, 2, True) if (t := pm.momentum_trade(data[s], fund[s], d, side))],
        "listing_short": pm.cap(lst, 10),
        "ratio_trend": rf.dynamic_trades(data, fund, pm.rank_table(data, 120), 7, 50)[0],
    }
    out, dailies = {}, {}
    mn = binance_min_notional()
    for k, tr in bots.items():
        d = ss.summary(tr, k)["_daily"]; dailies[k] = d; out[k] = stats(tr, d)
        m, cap, mx = min_capital(tr, out[k]["maxDD"], mn, 2 if k == "ratio_trend" else 1)
        tested = int(math.ceil((AMOUNT * mx + out[k]["maxDD"]) / 10) * 10)
        out[k].update({"minMargin": m, "minCapital": cap, "maxOpen": mx, "testedCapital": tested})
        print(f"  {k:<14} max open {mx:>3}  min margin/trade ${m:>6}  min capital ${cap:>6}  (as tested at $20: ${tested})")
    core = pd.DataFrame({k: dailies[k] for k in ("trend_daily", "momentum_ls", "listing_short")}).fillna(0).sum(axis=1)
    allf = pd.DataFrame(dailies).fillna(0).sum(axis=1)
    combo = {"core": stats([{"pnl": x} for x in core.values if x], core), "all": stats([{"pnl": x} for x in allf.values if x], allf)}
    for c in combo.values():
        for k in ("trades", "winRate", "pf"): c.pop(k)
    meta = {"generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "from": str(min(d.index.min() for d in dailies.values()).date()),
            "to": str(max(d.index.max() for d in dailies.values()).date()), "marginUsdt": AMOUNT, "leverage": LEV, "feePct": FEE,
            "outOfSampleFrom": str(CUT.date()), "universe": "all Binance USDT-M perpetuals since 2019, delisted included",
            "symbolsTested": len(data)}
    path = ROOT / "lib" / "bot-stats.json"
    path.write_text(json.dumps({"meta": meta, "bots": out, "combined": combo}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {path}")
    # every trade, compact, for the backtest page (pnl at $20 x2 — the page scales it with the margin)
    sym = lambda t: (t.get("pair") or t.get("symbol") or "").replace("USDT", "")
    trades = {k: [[int(t["entry_ts"]), int(t["exit_ts"]), sym(t), t["side"], round(float(t["entry"]), 8), round(float(t["exit"]), 8),
                   round(float(t["pnl"]), 4), t.get("reason", "")] for t in sorted(tr, key=lambda t: t["entry_ts"])] for k, tr in bots.items()}
    # per leverage (the page lets the user pick x1-x5); the ratio trend has no stop, so it is only simulated at x2
    rows = lambda tr: [[int(t["entry_ts"]), int(t["exit_ts"]), sym(t), t["side"], round(float(t["entry"]), 8), round(float(t["exit"]), 8),
                        round(float(t["pnl"]), 4), t.get("reason", "")] for t in sorted(tr, key=lambda t: t["entry_ts"])]
    by_lev = {k: {} for k in bots}
    for lev in LEVERAGES:
        at = trades_at(lev, data, fund, rk10, ever10, rk100, new) if lev != LEV else {k: bots[k] for k in ("trend_daily", "momentum_ls", "listing_short")}
        for k, tr in at.items(): by_lev[k][str(lev)] = rows(tr)
        print(f"  x{lev}: " + "  ".join(f"{k} {sum(t['pnl'] for t in tr):+.0f}" for k, tr in at.items()))
    by_lev["ratio_trend"][str(LEV)] = trades["ratio_trend"]
    assert by_lev["momentum_ls"][str(LEV)] == trades["momentum_ls"]          # the x2 set is the one the site's numbers use
    tpath = ROOT / "public" / "bot-trades.json"; tpath.parent.mkdir(exist_ok=True)
    tpath.write_text(json.dumps({"meta": {**meta, "fields": ["entry_ts", "exit_ts", "symbol", "side", "entry", "exit", "pnl", "reason"],
                                          "leverages": {k: sorted(map(int, v)) for k, v in by_lev.items()}},
                                 "trades": by_lev}, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {tpath} ({tpath.stat().st_size // 1024} KB)")
    for k, v in out.items(): print(f"  {k:<14} trades {v['trades']:>5} WR {v['winRate']:>5}% PF {v['pf']:>5} pnl {v['pnl']:>9} DD {v['maxDD']:>7} sharpe {v['sharpeIn']}/{v['sharpeOut']}")
    for k, v in combo.items(): print(f"  combined {k:<5} pnl {v['pnl']:>9} DD {v['maxDD']:>7} sharpe {v['sharpeIn']}/{v['sharpeOut']}")


if __name__ == "__main__":
    main()
