"""
Look-ahead check for the research simulators (owner, 2026-11-09: "add it"; the idea of freqtrade's lookahead-analysis,
written here from scratch).

A backtest that reads tomorrow's data shows an edge that can't exist live. The test: cut every coin's history at a date
T the way a live bot sees it at T's open — T's own bar has only its open (high = low = close = open, no volume, no
funding yet) — and run the simulator again. Every trade it entered up to and including T must come out the same —
same coin, side, entry time and entry price — because nothing after T's open can have decided it. A trade that
disappears, appears or changes price when the future is removed was decided with the future.

After T each listed coin gets PAD_DAYS flat, empty bars, so a simulator that needs a few bars after an entry (a next
open to fill at, a holding period) still takes the entries before T; whatever it does on those bars is after T and
isn't compared. Only entries are compared: exits of trades still open at T are cut short by design.

A strategy that rests a stop order at the open and fills when the day trades through it (vol_breakout: open + k x
yesterday's range) needs T's high and low to fill on T: for those (INTRABAR) T's bar keeps its high and low, and only
its close and volume are hidden. A leak through T's close is still caught there; one through T's high or low isn't.

  python research/lookahead_check.py                 # every live / paper strategy, 8 cut dates
  python research/lookahead_check.py --cuts 2022-06-01,2024-03-01 --only momentum_ls

retail_fade needs the open-interest files, which are on the server only: run it there with RAQM_RESEARCH_CACHE set.
Exit code 1 when any strategy fails.
"""
import argparse, os, pickle, sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent)); sys.path.insert(0, str(Path(__file__).resolve().parent))

CACHE = Path(os.getenv("RAQM_RESEARCH_CACHE") or Path(__file__).resolve().parent / ".cache")
DAY_MS = 86_400_000
PAD_DAYS = 15
CUTS = ["2021-03-01", "2021-11-15", "2022-06-01", "2023-01-15", "2023-09-01", "2024-03-01", "2024-11-15", "2025-07-01"]


def cut(data, fund, t_ms, pad=PAD_DAYS, intrabar=False):
    """What a live bot knows at t_ms's open: every coin's daily rows before t_ms, t_ms's bar as its open only, then
    `pad` flat empty bars; funding before t_ms. Coins not listed yet are left out; a coin whose history ended before
    t_ms (delisted) keeps that history as it is."""
    d = {}
    for s, df in data.items():
        x = df[df.ts <= t_ms].reset_index(drop=True)
        if not len(x):
            continue
        if int(x.ts.iloc[-1]) == t_ms:
            x = x.copy(); o = x.open.iloc[-1]; last = len(x) - 1
            for col in (("close",) if intrabar else ("high", "low", "close")):
                x.loc[last, col] = o
            x.loc[last, "qvol"] = 0.0
            x = pd.concat([x, pd.DataFrame({"ts": t_ms + DAY_MS * pd.RangeIndex(1, pad + 1), "open": o, "high": o, "low": o,
                                            "close": o, "qvol": 0.0})], ignore_index=True)
        d[s] = x
    return d, {s: {k: v for k, v in (fund.get(s) or {}).items() if k < t_ms} for s in d}


def entries(trades, until_ms):
    """{(coin, side, entry_ts): entry price} of the trades entered at or before until_ms."""
    out = {}
    for t in trades or []:
        if t["entry_ts"] <= until_ms:
            out[(t.get("symbol") or t.get("pair"), t.get("side"), int(t["entry_ts"]))] = float(t.get("entry", 0.0))
    return out


def compare(full, part, until_ms, rel=1e-9):
    """(missing, extra, repriced): entries the full run made that the cut run didn't, the reverse, and the same entry
    at another price."""
    a, b = entries(full, until_ms), entries(part, until_ms)
    missing = sorted(set(a) - set(b)); extra = sorted(set(b) - set(a))
    repriced = sorted(k for k in set(a) & set(b) if abs(a[k] - b[k]) > rel * max(1.0, abs(a[k])))
    return missing, extra, repriced


def check(sim, data, fund, cuts, intrabar=False):
    """[(cut date, compared, missing, extra, repriced)] for sim(data, fund) -> trades."""
    full = sim(data, fund)
    out = []
    for c in cuts:
        t = int(pd.Timestamp(c).value // 1_000_000)
        d, f = cut(data, fund, t, intrabar=intrabar)
        m, e, r = compare(full, sim(d, f), t)
        out.append((c, len(entries(full, t)), m, e, r))
    return out


# ── the strategies, as research/baseline_stats.py and research/paper_baseline.py simulate them ──
def _ctx(data, fund):
    import baseline_stats as b
    rk10 = b.ranks(data); ever10 = [s for s in data if (rk10[s] <= 10).any()]
    new = [s for s, df in data.items() if pd.to_datetime(df.ts.iloc[0], unit="ms") >= pd.Timestamp("2021-01-01")]
    return b, rk10, ever10, new


def _core(name):
    def sim(data, fund):
        b, rk10, ever10, new = _ctx(data, fund)
        return b.bs.trades_at(b.ts.LEV, data, fund, rk10, ever10, b.pm.rank_table(data, 60), new)[name]
    return sim


def _ratio(data, fund):
    import ratio_fairness as rf, pump_momentum_study as pm
    return rf.dynamic_trades(data, fund, pm.rank_table(data, 120), 7, 50)[0]


def _arrays(name):
    def sim(data, fund):
        import traders_study as ts, pump_momentum_study as pm, bot
        A = ts.coin_arrays(data, fund, pm.rank_table(data, 60))
        try:
            if name == "vol_breakout":
                ts.SLIP = bot.VB["slip"]; return ts.vb_trades(A, bot.VB["top"], bot.VB["k"], bot.VB["ma"])
            if name == "rsi2_pullback":
                ts.SLIP = 0.0; return ts.rsi2_trades(A, bot.RSI2["top"], bot.RSI2["below"], True, "sma5")
            ts.SLIP = bot.TB["slip"]; return ts.vcp_trades(A, bot.TB["top"], bot.TB["L"], float("inf"), "40pct", bot.TB["exit_ma"])
        finally:
            ts.SLIP = 0.0
    return sim


def _paper(name):
    def sim(data, fund):
        import paper_baseline as pb
        return getattr(pb, name)(data, fund)
    return sim


SIMS = {"trend_daily": _core("trend_daily"), "momentum_ls": _core("momentum_ls"), "listing_short": _core("listing_short"),
        "ratio_trend": _ratio, "vol_breakout": _arrays("vol_breakout"), "rsi2_pullback": _arrays("rsi2_pullback"),
        "trend_breakout": _arrays("trend_breakout"), "rsi2_btc": _paper("rsi2_btc"), "retail_fade": _paper("retail_fade")}
INTRABAR = {"vol_breakout"}          # a stop order resting from the open, filled when the day trades through it


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--cuts", default=",".join(CUTS))
    p.add_argument("--only", default="")
    a = p.parse_args(argv)
    data = pickle.loads((CACHE / "universe_daily.pkl").read_bytes())
    fund_raw = pickle.loads((CACHE / "universe_funding.pkl").read_bytes())
    fund = {s: fund_raw.get(s, {}) for s in data}
    names = [n.strip() for n in a.only.split(",") if n.strip()] or list(SIMS)
    cuts = [c.strip() for c in a.cuts.split(",") if c.strip()]
    bad = 0
    print("strategy | cut | entries compared | missing | extra | other price")
    for n in names:
        if SIMS[n](data, fund) is None:
            print(f"{n} | - | no data here (open-interest files: run it on the server)"); continue
        for c, k, m, e, r in check(SIMS[n], data, fund, cuts, intrabar=n in INTRABAR):
            print(f"{n} | {c} | {k} | {len(m)} | {len(e)} | {len(r)}")
            for what, xs in (("missing", m), ("extra", e), ("other price", r)):
                for x in xs[:3]:
                    print(f"    {what}: {x[0]} {x[1]} {pd.to_datetime(x[2], unit='ms').date()}")
            bad += bool(m or e or r)
    print("LOOK-AHEAD FOUND" if bad else "no look-ahead found")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
