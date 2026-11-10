"""What a real momentum_ls rebalance actually cost, from Binance's own records (development-plan 2.5, roadmap B3).

Read only: the account's fills and income history. Nothing is placed, changed or cancelled. It compares each cost
with what the backtest assumed (research/momentum_carry_study.py):
  - fees: the commission Binance charged, against 0.04 % of each fill's notional.
  - slippage, measured two ways:
      - against the 00:00 UTC daily close, the price the backtest trades at (it assumes no slippage);
      - against the open of the minute each fill happened in, which is the bot's own execution cost.
    A positive value is a cost: bought higher, or sold lower.
  - funding: what the account paid (-) or received (+) on the funding of the week the rebalance closed.

Run as raqmlive with the real key, the same way as rebalance_check.py:
  sudo -u raqmlive sh -c 'set -a; . /opt/raqm-live/.env.real; . /opt/raqm-live/.env.telegram; set +a; \
      cd /opt/raqm-live && venv/bin/python -E -s scripts/rebalance_costs.py [--day 2026-11-09] [--hours 6] [--telegram]'
The default --day is the bot's last rebalance (mom_last). --hours sets how long after 00:00 counts as the rebalance.
"""
import json, math, os, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(os.getenv("RAQM_LIVE_ROOT") or Path(__file__).resolve().parent.parent)   # override: a copy run from elsewhere
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "backend"))
STATE = ROOT / "state" / "live-momentum_ls.json"
FEE_ASSUMED = 0.0004       # per side, research/momentum_carry_study.py
DAY_MS, MIN_MS = 86_400_000, 60_000


def _f(v):
    try:
        v = float(v); return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def summarize(fills, funding, close_ref, minute_ref, fee_assumed=FEE_ASSUMED):
    """fills: [{symbol, side buy|sell, price, amount, fee_usdt, time}]; funding: [USDT, + received];
    close_ref: {symbol: price at 00:00}; minute_ref: {(symbol, minute ms): open}. Totals in USDT."""
    s = {"fills": len(fills), "coins": len({f["symbol"] for f in fills}), "notional": 0.0, "fees": 0.0,
         "slip_close": 0.0, "slip_close_notional": 0.0, "slip_exec": 0.0, "slip_exec_notional": 0.0,
         "funding": sum(funding), "missing_fee": 0, "per_coin": {}}
    for f in fills:
        n = f["price"] * f["amount"]; sign = 1 if f["side"] == "buy" else -1
        s["notional"] += n
        if f.get("fee_usdt") is None: s["missing_fee"] += 1
        else: s["fees"] += f["fee_usdt"]
        c = s["per_coin"].setdefault(f["symbol"], {"notional": 0.0, "slip_close": 0.0, "slip_exec": 0.0})
        c["notional"] += n
        ref = close_ref.get(f["symbol"])
        if ref:
            v = sign * (f["price"] - ref) * f["amount"]; s["slip_close"] += v; s["slip_close_notional"] += n; c["slip_close"] += v
        ref = minute_ref.get((f["symbol"], f["time"] // MIN_MS * MIN_MS))
        if ref:
            v = sign * (f["price"] - ref) * f["amount"]; s["slip_exec"] += v; s["slip_exec_notional"] += n; c["slip_exec"] += v
    s["fees_assumed"] = s["notional"] * fee_assumed
    s["total"] = s["fees"] + s["slip_close"] - s["funding"]
    return s


def report(s, day, hours):
    bps = lambda v, n: f"{v / n * 1e4:+.1f} bps" if n else "—"
    pct = lambda v, n: f"{v / n * 100:.3f}%" if n else "—"
    lines = [f"💸 تكاليف التبديل الحقيقي — {day:%Y-%m-%d} (أول {hours} ساعة بعد 00:00 UTC)"]
    if not s["fills"]:
        lines.append("ℹ️ مفيش صفقات اتنفذت في الوقت ده"); return "\n".join(lines)
    lines += [
        f"ℹ️ {s['fills']} تنفيذ على {s['coins']} عملة · حجم {s['notional']:.2f} USDT",
        f"ℹ️ الرسوم: {s['fees']:.4f} USDT ({pct(s['fees'], s['notional'])} من الحجم) · الباكتست فرض {s['fees_assumed']:.4f} (0.04%)"
        + (f" · {s['missing_fee']} تنفيذ من غير رسوم معروفة" if s["missing_fee"] else ""),
        f"ℹ️ الفرق عن سعر إقفال 00:00 (الباكتست فرضه صفر): {s['slip_close']:+.4f} USDT ({bps(s['slip_close'], s['slip_close_notional'])})",
        f"ℹ️ الفرق عن سعر الدقيقة اللي اتنفذ فيها (تكلفة التنفيذ نفسه): {s['slip_exec']:+.4f} USDT ({bps(s['slip_exec'], s['slip_exec_notional'])})",
        f"ℹ️ الـ funding للأسبوع اللي اتقفل: {s['funding']:+.4f} USDT ({'اتقبض' if s['funding'] >= 0 else 'اتدفع'})",
        f"ℹ️ التكلفة كلها (رسوم + فرق السعر − funding): {s['total']:+.4f} USDT",
    ]
    worst = sorted(s["per_coin"].items(), key=lambda kv: -kv[1]["slip_close"])[:3]
    if worst and worst[0][1]["slip_close"] > 0:
        lines.append("ℹ️ أكتر فرق سعر: " + " · ".join(f"{k.split('/')[0]} {v['slip_close']:+.4f}" for k, v in worst if v["slip_close"] > 0))
    return "\n".join(lines)


def _income(ex, kind, start, end):
    out, t = [], start
    while t < end:
        rows = ex.fapiPrivateGetIncome({"incomeType": kind, "startTime": t, "endTime": end, "limit": 1000}) or []
        out += rows
        if len(rows) < 1000: break
        t = int(rows[-1]["time"]) + 1
    return out


def collect(ex, day, hours):
    """(fills, funding, close_ref, minute_ref) from Binance for the rebalance on `day` (00:00 UTC)."""
    ex.load_markets()
    by_id = {m["id"]: s for s, m in ex.markets.items() if m.get("swap") and m.get("linear")}
    d0 = int(day.timestamp() * 1000); start, end = d0, d0 + hours * 3_600_000
    # which coins traded: the commission records name every one (one per fill), so no coin is missed
    syms = sorted({by_id[r["symbol"]] for r in _income(ex, "COMMISSION", start, end) if r.get("symbol") in by_id})
    fills = []
    for sym in syms:
        for t in ex.fetch_my_trades(sym, since=start, limit=1000):
            if not (start <= t["timestamp"] < end): continue
            fee = t.get("fee") or {}; cost = _f(fee.get("cost"))
            if cost is not None and (fee.get("currency") or "USDT") != "USDT":
                try: cost *= float(ex.fetch_ticker(f"{fee['currency']}/USDT:USDT")["last"])
                except Exception: cost = None
            fills.append({"symbol": sym, "side": t["side"], "price": float(t["price"]), "amount": float(t["amount"]),
                          "fee_usdt": cost, "time": int(t["timestamp"])})
    funding = [float(r["income"]) for r in _income(ex, "FUNDING_FEE", d0 - 7 * DAY_MS, d0)]
    close_ref, minute_ref = {}, {}
    for sym in syms:
        try:
            k = ex.fetch_ohlcv(sym, "1d", since=d0 - DAY_MS, limit=2)
            row = next((r for r in k if r[0] == d0 - DAY_MS), None)        # the candle that closed at 00:00
            if row: close_ref[sym] = float(row[4])
        except Exception: pass
        for m in sorted({f["time"] // MIN_MS * MIN_MS for f in fills if f["symbol"] == sym}):
            try:
                k = ex.fetch_ohlcv(sym, "1m", since=m, limit=1)
                if k and k[0][0] == m: minute_ref[(sym, m)] = float(k[0][1])
            except Exception: pass
    return fills, funding, close_ref, minute_ref


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    arg = lambda name, default=None: argv[argv.index(name) + 1] if name in argv else default
    hours = int(arg("--hours", "6"))
    if arg("--day"):
        day = datetime.fromisoformat(arg("--day")).replace(tzinfo=timezone.utc)
    else:
        last = json.loads(STATE.read_text(encoding="utf-8")).get("mom_last")
        if not last: sys.exit("no rebalance yet (mom_last empty): pass --day")
        day = datetime.fromisoformat(last)
    day = day.replace(hour=0, minute=0, second=0, microsecond=0)
    import bot
    assert bot.binance_env() == "live", f"BINANCE_ENV={bot.binance_env()}: this reads the real account"
    ex, err = bot.get_exchange(auth=True)
    if err: sys.exit(err)
    text = report(summarize(*collect(ex, day, hours)), day, hours)
    print(text)
    if "--telegram" in argv:
        sys.path.insert(0, str(ROOT / "scripts")); import watchdog
        for part in watchdog.chunks(text.split("\n")): watchdog.send(part)
    return 0


if __name__ == "__main__":
    sys.exit(main())
