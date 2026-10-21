"""
Daily trend following (time-series momentum) with volatility-sized entries — research/README.md.
Must stay identical to lib/trend-daily.ts — research/trend_parity.ts compares them trade by trade.

At each daily close: "on" when the close is above the close 20, 60 and 120 days ago for at least 2 of the 3.
- flat + on      -> buy at the next open, notional = margin x leverage x min(1, 80% / 30-day volatility)
- long + not on  -> sell at the next open
- protective stop at entry x (1 - 0.8 / leverage): sells before the margin would be liquidated
Long only. Costs: fee on both sides, and the funding of every candle held (positive funding = longs pay).
"""
import math

LOOKBACKS = (20, 60, 120)
VOL_DAYS, VOL_TARGET, STOP_SHARE = 30, 0.8, 0.8


def trend_on(c, i):
    if i < max(LOOKBACKS): return False
    return sum(c[i] > c[i - L] for L in LOOKBACKS) >= 2


def volatility(c, i):
    """Annualised standard deviation (n-1) of the last VOL_DAYS daily returns ending at candle i."""
    r = [c[k] / c[k - 1] - 1 for k in range(i - VOL_DAYS + 1, i + 1)]
    m = sum(r) / len(r)
    return math.sqrt(sum((x - m) ** 2 for x in r) / (len(r) - 1)) * math.sqrt(365)


def size_factor(c, i):
    v = volatility(c, i)
    return min(1.0, VOL_TARGET / v) if v > 0 else 1.0


def run_trend_daily(o, h, l, c, ts, funding=None, amount=20, leverage=2, fee=0.0004, start_ts=0):
    """Backtest on daily candle arrays (oldest first); entries only on candles at or after start_ts.
    funding[i] = funding rate paid over candle i (sum of its payments), or None.
    Returns trades: {entry_ts, exit_ts, side, entry, exit, qty, pnl, reason, kind}."""
    n = len(c); trades = []; pos = None; pending = None
    for i in range(n):
        if pending == "buy":
            qty = amount * leverage * pend_size / o[i]
            pos = {"entry": o[i], "qty": qty, "ts": ts[i], "funding": 0.0, "stop": o[i] * (1 - STOP_SHARE / leverage)}
        elif pending == "sell" and pos:
            trades.append(_close(pos, o[i], ts[i], "signal off", fee)); pos = None
        pending = None
        if pos:
            if l[i] <= pos["stop"]:
                trades.append(_close(pos, min(o[i], pos["stop"]), ts[i], "stop", fee)); pos = None
            elif funding is not None:
                pos["funding"] += pos["qty"] * c[i] * funding[i]
        # decision at candle i's close
        if i + 1 < n and i >= VOL_DAYS:
            on = trend_on(c, i)
            if pos is None and on and ts[i] >= start_ts:
                pending, pend_size = "buy", size_factor(c, i)
            elif pos is not None and not on:
                pending = "sell"
    if pos: trades.append(_close(pos, c[-1], ts[-1], "close", fee))
    return trades


def _close(p, price, exit_ts, reason, fee):
    q = p["qty"]
    pnl = (price - p["entry"]) * q - (p["entry"] * q + price * q) * fee - p["funding"]
    return {"entry_ts": p["ts"], "exit_ts": exit_ts, "side": "long", "entry": p["entry"], "exit": price, "qty": q,
            "pnl": pnl, "reason": reason, "kind": "Trend"}


def signal_now(c):
    """Live bot: (on, size_factor) from closed daily closes (oldest first)."""
    i = len(c) - 1
    return trend_on(c, i), (size_factor(c, i) if i >= VOL_DAYS else 1.0)
