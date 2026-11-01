"""The Demo measurement against the backtest baseline (owner, 2026-11-01): for each strategy, its own closed trades
on Demo since the measurement started next to lib/demo-baseline.json, how much of its sample is done and a status.

Agreed before any result was seen (owner, 2026-11-01):
- sample: 30 trades; 15 for the slow ones (rsi2_pullback, listing_short); momentum_ls is not measured (its basket of 10
  doesn't fit its share of slots);
- after its sample a strategy is "far" — switched off, not re-tuned — when its profit factor is under 1 or its worst
  drawdown is over 1.5 × the baseline's.
Only the strategies' own exits count: trades closed by hand (the site, the admin, on Binance) and anything closed
before the start are left out. Every figure is in % of the trade's margin, the baseline's unit.
"""
from datetime import datetime, timezone

START = datetime(2026, 10, 31, tzinfo=timezone.utc)
SAMPLE = {"trend_daily": 30, "ratio_trend": 30, "vol_breakout": 30, "trend_breakout": 30,
          "rsi2_pullback": 15, "listing_short": 15, "momentum_ls": None}
DD_LIMIT = 1.5        # × the baseline's worst drawdown
WIN_GAP = 15.0        # points of win rate: past it, a look (not a verdict)
LOSS_LIMIT = 1.5      # × the baseline's average loss: past it, a look


def _when(s):
    try:
        t = datetime.fromisoformat(s)
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def counted(rows, start=START):
    """The strategy's own exits since the start, oldest first: no manual close, opened and closed after the start."""
    out = []
    for r in rows or []:
        t, o = _when(r.get("time")), _when(r.get("opened"))
        if t is None or t < start or (o is not None and o < start):
            continue
        if r.get("by") or "يدوي" in str(r.get("reason") or ""):
            continue
        try:
            pct = float(r["pnl_pct"])
        except (KeyError, TypeError, ValueError):
            continue
        out.append((t, pct))
    return sorted(out)


def stats(trades, now, start=START):
    """Figures in the baseline's units from [(exit time, % of margin)]."""
    pcts = [p for _, p in trades]
    wins, losses = [p for p in pcts if p > 0], [p for p in pcts if p <= 0]
    cum = peak = dd = 0.0
    for p in pcts:
        cum += p / 100.0; peak = max(peak, cum); dd = max(dd, peak - cum)
    days = max((now - start).total_seconds() / 86400, 0.0)
    return {"trades": len(pcts), "days": round(days, 1),
            "per_month": round(len(pcts) / days * 30.44, 1) if days >= 1 else None,
            "win_rate": round(len(wins) / len(pcts) * 100, 1) if pcts else None,
            "avg_win_pct": round(sum(wins) / len(wins), 1) if wins else None,
            "avg_loss_pct": round(sum(losses) / len(losses), 1) if losses else None,
            "profit_factor": round(sum(wins) / -sum(losses), 2) if losses and sum(losses) < 0 else None,
            "max_dd_margins": round(dd, 2), "net_margins": round(cum, 2)}


def verdict(st, base, sample):
    """(status, reasons). not_measured / collecting / attention / far / in_range."""
    if sample is None:
        return "not_measured", ["سلتها 10 صفقات مع بعض وأكبر من نصيبها من الأماكن"]
    b = (base or {}).get("all") or {}
    hard, soft = [], []
    if b.get("max_dd_margins") and st["max_dd_margins"] > DD_LIMIT * b["max_dd_margins"]:
        hard.append(f"التراجع {st['max_dd_margins']} مارجن — أكتر من {DD_LIMIT}× الجدول ({b['max_dd_margins']})")
    if st["trades"] < sample:
        return ("attention", hard) if hard else ("collecting", [])
    if st["profit_factor"] is not None and st["profit_factor"] < 1:
        hard.append(f"الـ profit factor {st['profit_factor']} — أقل من 1")
    if hard:
        return "far", hard
    if st["win_rate"] is not None and b.get("win_rate") is not None and abs(st["win_rate"] - b["win_rate"]) > WIN_GAP:
        soft.append(f"نسبة الكسب {st['win_rate']}% والجدول {b['win_rate']}%")
    if st["avg_loss_pct"] is not None and b.get("avg_loss_pct") and st["avg_loss_pct"] < LOSS_LIMIT * b["avg_loss_pct"]:
        soft.append(f"متوسط الخسارة {st['avg_loss_pct']}% والجدول {b['avg_loss_pct']}%")
    return ("attention", soft) if soft else ("in_range", [])


def measure(closed_by_strategy, baseline, now=None):
    """{strategy: rows} and the baseline JSON → the admin page's table."""
    now = now or datetime.now(timezone.utc)
    out = {}
    for s, sample in SAMPLE.items():
        st = stats(counted(closed_by_strategy.get(s)), now)
        base = ((baseline or {}).get("strategies") or {}).get(s)
        status, reasons = verdict(st, base, sample)
        out[s] = {"sample": sample, "demo": st, "baseline": (base or {}).get("all"), "status": status, "reasons": reasons}
    return {"start": START.isoformat(), "dd_limit": DD_LIMIT, "strategies": out}
