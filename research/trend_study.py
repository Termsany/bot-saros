"""
Trend following on daily candles (time-series momentum) with and without volatility targeting.

  python research/trend_data.py     # once: Binance USDT-M daily candles + funding, 8 coins since 2019/2020
  python research/trend_study.py    # grid on the first 60% of each coin, report the last 40%

Literature: Moskowitz, Ooi & Pedersen (2012) "Time Series Momentum", JFE; Liu & Tsyvinski (2021)
"Risks and Returns of Cryptocurrency", RFS (momentum in crypto); Moreira & Muir (2017)
"Volatility-Managed Portfolios", JF (size by inverse recent volatility).

Rules (per coin, no look-ahead): the signal uses closes up to day t and sets the position held over day t+1.
- signal: sign of the return over the last L days; "ens" = average sign of L = 20, 60, 120 (-1..1)
- long-only (negative signal = flat) or long/short
- size: fixed $100 notional ($20 margin x5, like the bot), or volatility-targeted:
  $100 x min(1, target / 30-day realised volatility) — never bigger than the bot's size today
- the position is only resized when the target moves more than 25% (fewer fees)
- costs: 0.04% of every change in notional, and the real funding paid/received each day
"""
import os
import pickle, itertools
from pathlib import Path
import numpy as np, pandas as pd

CACHE = Path(os.getenv("RAQM_RESEARCH_CACHE") or Path(__file__).resolve().parent / ".cache")   # shared store: research/README.md
COINS = ["BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "LINK"]
NOTIONAL, FEE, BAND, SPLIT = 100.0, 0.0004, 0.25, 0.6
LOOKBACKS = [20, 60, 120, "ens"]
MODES = ["long", "longshort"]
TARGETS = [None, 0.4, 0.6, 0.8]          # None = fixed size; else annualised volatility target


def load(coin): return pickle.loads((CACHE / f"trend_{coin}.pkl").read_bytes())


def signal(close, L):
    if L == "ens":
        return sum(np.sign(close / close.shift(l) - 1) for l in (20, 60, 120)) / 3
    return np.sign(close / close.shift(L) - 1)


def run(df, L, mode, target):
    """Daily PnL in USDT (index = day the PnL is earned)."""
    c = df.close; ret = c.pct_change()
    s = signal(c, L)
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
    pnl = pos * ret.fillna(0) - pos * df.funding - turnover * FEE
    return pnl, pos


def metrics(pnl, pos):
    eq = pnl.cumsum(); dd = (eq.cummax() - eq).max()
    sd = pnl.std()
    return {"pnl": pnl.sum(), "sharpe": pnl.mean() / sd * np.sqrt(365) if sd else 0.0, "maxDD": dd,
            "exposure": pos.abs().mean() / NOTIONAL, "trades": int((np.sign(pos).diff().fillna(0) != 0).sum())}


def main():
    data = {c: load(c) for c in COINS}
    rows = []
    configs = list(itertools.product(LOOKBACKS, MODES, TARGETS)) + [("hold", "long", None), ("hold", "long", 0.6)]
    for L, mode, tgt in configs:
        for coin, df in data.items():
            if L == "hold":
                s = pd.Series(1.0, index=df.index)
                size = NOTIONAL if tgt is None else NOTIONAL * np.minimum(1.0, tgt / (df.close.pct_change().rolling(30).std() * np.sqrt(365)))
                held = (s * size).fillna(0.0)
                pos = held.shift(1).fillna(0.0)
                pnl = pos * df.close.pct_change().fillna(0) - pos * df.funding - held.diff().abs().fillna(held.iloc[0]) * FEE
            else:
                pnl, pos = run(df, L, mode, tgt)
            cut = int(len(df) * SPLIT)
            for part, sl in (("is", slice(0, cut)), ("oos", slice(cut, None))):
                m = metrics(pnl.iloc[sl], pos.iloc[sl])
                rows.append({"L": str(L), "mode": mode, "target": tgt or 0, "coin": coin, "part": part, **m})
    r = pd.DataFrame(rows)
    key = ["L", "mode", "target"]
    agg = r.groupby(key + ["part"]).agg(sharpe_med=("sharpe", "median"), pnl=("pnl", "sum"), maxDD_med=("maxDD", "median"),
                                        won=("pnl", lambda x: int((x > 0).sum())), exposure=("exposure", "mean"),
                                        trades=("trades", "sum")).unstack("part")
    agg.columns = [f"{a}_{b}" for a, b in agg.columns]
    agg = agg.sort_values("sharpe_med_is", ascending=False)
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 100)
    cols = ["sharpe_med_is", "pnl_is", "won_is", "sharpe_med_oos", "pnl_oos", "won_oos", "maxDD_med_oos", "exposure_oos", "trades_oos"]
    print(agg[cols].round(2).to_string())
    (CACHE / "trend_results.pkl").write_bytes(pickle.dumps(r))


if __name__ == "__main__":
    main()
