"""The real momentum_ls basket against Binance, read only (roadmap A7, development-plan 2.1).

Checks what the owner would check by hand after a rebalance: the bot is live and writing, no recovery or review, the
basket is 5 long + 5 short, each leg's quantity and side are the exchange's and its stop is open on Binance, nothing on
the exchange the bot doesn't hold, and — on a rebalance day — the rebalance ran today, every leg it closed has an
exchange exit price and a net PnL, and no order is left on those coins. Places, changes or cancels nothing.

Run as raqmlive with the real key (the same file the bot reads):
  sudo -u raqmlive sh -c 'set -a; . /opt/raqm-live/.env.real; . /opt/raqm-live/.env.telegram; set +a; \
      cd /opt/raqm-live && venv/bin/python -E -s scripts/rebalance_check.py [--rebalance-day] [--telegram]'
raqm-rebalance-check.timer runs it with both flags on Mondays at 00:20 UTC.
"""
import json, math, os, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.getenv("RAQM_LIVE_ROOT") or Path(__file__).resolve().parent.parent)   # override: a copy run from elsewhere
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "backend"))
STATE = ROOT / "state" / "live-momentum_ls.json"
STATUS = Path(os.getenv("RAQM_IPC_ROOT", "/opt/raqm-ipc")) / "momentum_ls" / "live_status.json"
WATCHDOG = ROOT / "state" / "watchdog.json"
LEGS_PER_SIDE = 5
STALE_S = 300


def _f(v):
    try:
        v = float(v); return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def check(state, status, ex, now, rebalance_day=False, watchdog=None):
    """[(ok, line)] — ok None = information only."""
    from app import oco
    out = []
    add = lambda ok, text: out.append((ok, text))

    # the bot
    age = None
    try: age = (now - datetime.fromisoformat(status["updated"])).total_seconds()
    except Exception: pass
    add(status.get("env") == "live" and age is not None and 0 <= age < STALE_S,
        f"البوت الحقيقي بيكتب حالته ({int(age)} ثانية)" if age is not None else "البوت الحقيقي مش بيكتب حالته")
    add(not status.get("entry_block"), "الدخول مش متوقف" if not status.get("entry_block") else f"الدخول متوقف: {status['entry_block']}")
    add(not state.get("recovery_required") and not status.get("review"),
        "مفيش recovery ولا مراجعة" if not state.get("recovery_required") and not status.get("review")
        else f"محتاج مراجعة: {', '.join(list(state.get('recovery_required') or {}) + list(status.get('review') or {}))}")
    if watchdog is not None:
        sent = [v.get("text") for v in watchdog.values() if v.get("sent")]
        add(not sent, "المراقب مش شايف مشاكل" if not sent else f"المراقب شايف: {' · '.join(sent)}")

    # the basket against the exchange
    pos = state.get("positions") or {}
    longs = sum(1 for p in pos.values() if p.get("side") == "long"); shorts = len(pos) - longs
    add(longs == LEGS_PER_SIDE and shorts == LEGS_PER_SIDE, f"السلة: {longs} لونج + {shorts} شورت")
    try:
        on_ex = {p["symbol"]: p for p in ex.fetch_positions() if abs(_f(p.get("contracts")) or 0) > 0}
    except Exception as e:
        add(False, f"مقدرناش نقرا الصفقات من Binance: {type(e).__name__}: {e}"); return out
    for sym in sorted(pos):
        p, e = pos[sym], on_ex.get(sym)
        name = sym.split("/")[0]
        if not e:
            add(False, f"{name}: في البوت ومش على Binance"); continue
        qty, eq = _f(p.get("qty")), _f(e.get("contracts"))
        same = e.get("side") == p.get("side") and qty and eq and abs(qty - eq) <= 1e-9 * max(qty, eq) + 1e-12
        ids = p.get("oco_ids") or {}
        stop = bool(ids.get("sl")) and oco._leg_on_exchange(ex, sym, {"id": ids["sl"]}, oco._oco_id(ids.get("pos_id"), "sl"))
        add(bool(same and stop), f"{name} {p.get('side')}: الكمية {'=' if same else '≠'} Binance · الوقف {'على Binance' if stop else 'مش لاقيينه على Binance'}")
    extra = sorted(set(on_ex) - set(pos))
    add(not extra, "مفيش صفقات على Binance البوت مش ماسكها" if not extra else f"على Binance ومش في البوت: {', '.join(s.split('/')[0] for s in extra)}")

    # the rebalance itself
    if rebalance_day:
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        add(state.get("mom_last") == today.isoformat(), f"التبديل اتعمل النهارده (آخر تبديل {state.get('mom_last')})")
        closed = [h for h in state.get("history") or [] if (h.get("time") or "") >= today.isoformat()]
        good = [h for h in closed if _f(h.get("exit")) and _f(h.get("pnl")) is not None]
        add(bool(closed) and len(good) == len(closed), f"اتقفل {len(closed)} صفقة، {len(good)} منهم بسعر خروج وربح صافي")
        if closed:
            add(None, f"صافي الأسبوع اللي فات (بعد الرسوم والـ funding): {sum(_f(h['pnl']) or 0 for h in closed):+.2f} USDT")
        left = []
        for sym in sorted({h["symbol"] for h in closed} - set(pos)):
            for view, fetch in oco._order_views(ex, sym):
                try: opens = fetch()
                except Exception: continue
                left += [f"{sym.split('/')[0]} ({view})" for o in opens or [] if oco._may_be_live_protection(o)]
        add(not left, "مفيش أوامر فاضلة على العملات اللي اتقفلت" if not left else f"أوامر فاضلة: {', '.join(sorted(set(left)))}")
    return out


def report(results, rebalance_day):
    bad = sum(1 for ok, _ in results if ok is False)
    head = "🔄 تشييك التبديل الحقيقي" if rebalance_day else "🔎 تشييك السلة الحقيقية"
    lines = [head] + [f"{'ℹ️' if ok is None else '✅' if ok else '❌'} {t}" for ok, t in results]
    lines.append("كله سليم" if not bad else f"🚨 {bad} محتاج تشوفه")
    return "\n".join(lines), bad


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    rebalance_day = "--rebalance-day" in argv
    import bot
    assert bot.binance_env() == "live", f"BINANCE_ENV={bot.binance_env()}: this checks the real account"
    ex, err = bot.get_exchange(auth=True)
    if err: sys.exit(err)
    load = lambda p: json.loads(p.read_text(encoding="utf-8"))
    try: wd = load(WATCHDOG)
    except Exception: wd = None
    text, bad = report(check(load(STATE), load(STATUS), ex, datetime.now(timezone.utc), rebalance_day, wd), rebalance_day)
    print(text)
    if "--telegram" in argv:
        sys.path.insert(0, str(ROOT / "scripts")); import watchdog
        for part in watchdog.chunks(text.split("\n")): watchdog.send(part)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
