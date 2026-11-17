"""
Ichimoku on daily candles, against the daily trend (trend_daily) in the same harness as research/trend_study.py.

  python research/ichimoku_study.py     # reads universe_daily.pkl + universe_funding.pkl (research/README.md)

Same rules as trend_study.py, so the numbers compare: the 8 coins, the signal from closes up to day t sets the
position held over day t+1, $100 notional, 0.04% of every change in notional, the real funding each day, a position
resized only on a >25% change, chosen on the first 60% of each coin and reported on the last 40%.

Ichimoku lines (Hosoda), periods (a, b, c) = (9, 26, 52) classic or (20, 60, 120) "crypto"; displacement = b:
  tenkan = mid of the last a highs/lows, kijun = mid of the last b, span A = (tenkan + kijun) / 2 and span B = mid of
  the last c, both drawn b days ahead — so the cloud at day t comes from data up to t - b (no look-ahead).
Signals (-1..1; long-only clips the negative side to flat):
  cloud   +1 close above both spans, -1 below both, 0 inside
  tk      +1 tenkan > kijun, else -1
  bot     (cloud + 0.5 x tk) / 2: the scoring of bot.py's ichimoku_signal
  strict  +1 above the cloud and tenkan > kijun and close > close b days ago (chikou), -1 the mirror, else 0
  ens+cloud  trend_daily's signal, kept only when the close is above the cloud (the cloud as a filter)
Baselines: ens (trend_study's average sign of the 20/60/120-day returns), 2of3 (the bot's rule: on when at least 2
of the 3 are up), buy-and-hold.
"""
import os
import pickle, itertools
from pathlib import Path
import numpy as np, pandas as pd

CACHE = Path(os.getenv("RAQM_RESEARCH_CACHE") or Path(__file__).resolve().parent / ".cache")   # shared store: research/README.md
COINS = ["BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "LINK"]
NOTIONAL, FEE, BAND, SPLIT = 100.0, 0.0004, 0.25, 0.6
PERIODS = {"9/26/52": (9, 26, 52), "20/60/120": (20, 60, 120)}
ICHI = ["cloud", "tk", "bot", "strict", "ens+cloud"]
MODES = ["long", "longshort"]
TARGETS = [None, 0.8]                    # None = fixed size; 0.8 = trend_daily's volatility target


def load():
    daily = pickle.loads((CACHE / "universe_daily.pkl").read_bytes())
    funding = pickle.loads((CACHE / "universe_funding.pkl").read_bytes())
    out = {}
    for coin in COINS:
        df = daily[f"{coin}USDT"].copy().sort_values("ts").drop_duplicates("ts").reset_index(drop=True)
        f = funding.get(f"{coin}USDT") or {}
        df["funding"] = df.ts.map(f).fillna(0.0)
        df["ts"] = pd.to_datetime(df.ts, unit="ms")
        out[coin] = df
    return out


def trend_signal(c, kind):
    ups = [np.sign(c / c.shift(l) - 1) for l in (20, 60, 120)]
    if kind == "ens": return sum(ups) / 3
    return (sum((u > 0).astype(float) for u in ups) >= 2).astype(float) - (sum((u < 0).astype(float) for u in ups) >= 2).astype(float)


def ichimoku(df, a, b, c):
    h, l, cl = df.high, df.low, df.close
    mid = lambda n: (h.rolling(n).max() + l.rolling(n).min()) / 2
    tenkan, kijun = mid(a), mid(b)
    span_a, span_b = ((tenkan + kijun) / 2).shift(b), mid(c).shift(b)
    top, bottom = np.maximum(span_a, span_b), np.minimum(span_a, span_b)
    cloud = pd.Series(np.where(cl > top, 1.0, np.where(cl < bottom, -1.0, 0.0)), index=df.index).where(span_b.notna())
    tk = pd.Series(np.where(tenkan > kijun, 1.0, -1.0), index=df.index).where(kijun.notna())
    chikou = np.sign(cl / cl.shift(b) - 1)
    return cloud, tk, chikou


def signal(df, kind, periods):
    c = df.close
    if kind in ("ens", "2of3"): return trend_signal(c, kind)
    cloud, tk, chikou = ichimoku(df, *periods)
    if kind == "cloud": return cloud
    if kind == "tk": return tk
    if kind == "bot": return (cloud + 0.5 * tk) / 2
    if kind == "strict":
        return ((cloud > 0) & (tk > 0) & (chikou > 0)).astype(float) - ((cloud < 0) & (tk < 0) & (chikou < 0)).astype(float)
    if kind == "ens+cloud":
        s = trend_signal(c, "ens")
        return s.where(((s > 0) & (cloud > 0)) | ((s < 0) & (cloud < 0)), 0.0).where(cloud.notna())
    raise ValueError(kind)


def run(df, s, mode, target):
    """Daily PnL in USDT (index = day the PnL is earned) — trend_study.run with the signal passed in."""
    ret = df.close.pct_change()
    if mode == "long": s = s.clip(lower=0)
    vol = ret.rolling(30).std() * np.sqrt(365)
    size = NOTIONAL if target is None else NOTIONAL * np.minimum(1.0, target / vol)
    want = (s * size).fillna(0.0).to_numpy()
    held = np.zeros(len(df)); cur = 0.0
    for t in range(len(df)):
        w = want[t]
        if np.sign(w) != np.sign(cur) or (cur != 0 and abs(w - cur) > BAND * abs(cur)): cur = w
        held[t] = cur                                   # decided at day t's close
    pos = pd.Series(held, index=df.index).shift(1).fillna(0.0)   # held over the next day
    turnover = pd.Series(held, index=df.index).diff().abs().fillna(abs(held[0]))
    fees = turnover * FEE
    pnl = pos * ret.fillna(0) - pos * df.funding - fees
    return pnl, pos, fees


def metrics(pnl, pos, fees):
    eq = pnl.cumsum(); dd = (eq.cummax() - eq).max(); sd = pnl.std()
    return {"pnl": pnl.sum(), "sharpe": pnl.mean() / sd * np.sqrt(365) if sd else 0.0, "maxDD": dd, "fees": fees.sum(),
            "exposure": pos.abs().mean() / NOTIONAL, "trades": int((np.sign(pos).diff().fillna(0) != 0).sum())}


def main():
    data = load()
    for coin, df in data.items():
        cut = int(len(df) * SPLIT)
        print(f"{coin}: {df.ts.iloc[0].date()} -> {df.ts.iloc[-1].date()}, out-of-sample from {df.ts.iloc[cut].date()}")
    configs = [(k, "-", m, t) for k in ("ens", "2of3") for m in MODES for t in TARGETS]
    configs += [(k, p, m, t) for k, p, m, t in itertools.product(ICHI, PERIODS, MODES, TARGETS)]
    configs += [("hold", "-", "long", None)]
    rows, daily = [], {}
    for kind, per, mode, tgt in configs:
        for coin, df in data.items():
            s = pd.Series(1.0, index=df.index) if kind == "hold" else signal(df, kind, PERIODS.get(per))
            pnl, pos, fees = run(df, s, mode, tgt)
            daily[(kind, per, mode, tgt or 0, coin)] = pd.Series(pnl.to_numpy(), index=df.ts)
            cut = int(len(df) * SPLIT)
            for part, sl in (("is", slice(0, cut)), ("oos", slice(cut, None))):
                rows.append({"signal": kind, "periods": per, "mode": mode, "target": tgt or 0, "coin": coin, "part": part,
                             **metrics(pnl.iloc[sl], pos.iloc[sl], fees.iloc[sl])})
    r = pd.DataFrame(rows)
    key = ["signal", "periods", "mode", "target"]
    agg = r.groupby(key + ["part"]).agg(sharpe_med=("sharpe", "median"), pnl=("pnl", "sum"), maxDD_med=("maxDD", "median"),
                                        won=("pnl", lambda x: int((x > 0).sum())), fees=("fees", "sum"),
                                        exposure=("exposure", "mean"), trades=("trades", "sum")).unstack("part")
    agg.columns = [f"{a}_{b}" for a, b in agg.columns]
    agg = agg.sort_values("sharpe_med_is", ascending=False)
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)
    cols = ["sharpe_med_is", "pnl_is", "won_is", "sharpe_med_oos", "pnl_oos", "won_oos", "maxDD_med_oos", "fees_oos",
            "exposure_oos", "trades_oos"]
    print(agg[cols].round(2).to_string())

    # the 8-coin portfolio by year: the bot's trend_daily rule against the best Ichimoku of the first 60%
    ichi = agg[agg.index.get_level_values("signal").isin(ICHI)]
    best = ichi.index[0]
    for name, k in (("trend_daily (2of3, long, vol 0.8)", ("2of3", "-", "long", 0.8)),
                    ("trend_daily as studied (ens, long, vol 0.8)", ("ens", "-", "long", 0.8)),
                    (f"best Ichimoku on the first 60%: {best}", best),
                    ("buy-and-hold", ("hold", "-", "long", 0))):
        port = pd.concat([daily[(*k, c)] for c in COINS], axis=1).fillna(0.0).sum(axis=1)
        eq = port.cumsum(); dd = (eq.cummax() - eq).max(); sh = port.mean() / port.std() * np.sqrt(365)
        years = port.groupby(port.index.year).sum().round(0).astype(int).to_dict()
        print(f"{name}: total {port.sum():+.0f}, max DD {dd:.0f}, Sharpe {sh:.2f}, by year {years}")
    (CACHE / "ichimoku_results.pkl").write_bytes(pickle.dumps(r))


if __name__ == "__main__":
    main()
