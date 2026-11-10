"""The weekly Demo check against the backtest baseline, to Telegram (roadmap B5, development-plan 6.1).

The same measurement as the admin page (backend/app/demo_measure.py, rules agreed on 2026-11-01): each strategy's own
closed Demo trades since the start, against lib/demo-baseline.json, its sample and its status; then the real
momentum account, and the paper candidates against lib/paper-baseline.json. Read only: the bots' closed.json files,
the paper bots' public JSON and the baselines.

  python scripts/demo_weekly.py [--telegram]      # from the API's folder, as raqmapi (raqm-demo-weekly.timer, Sundays)
"""
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.getenv("RAQM_APP_ROOT") or Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(ROOT / "backend"))
IPC = Path(os.getenv("RAQM_IPC_DIR", "/opt/raqm-ipc"))
BASELINE = ROOT / "lib" / "demo-baseline.json"
ICON = {"in_range": "✅", "collecting": "⏳", "attention": "⚠️", "far": "❌", "not_measured": "➖"}
WORD = {"in_range": "قريبة من الباكتست", "collecting": "لسه بتجمع", "attention": "محتاجة نظرة", "far": "بعيدة: تتقفل",
        "not_measured": "مش متقاسة"}


def load_closed(ipc=IPC, strategies=None):
    from app import demo_measure
    out = {}
    for s in strategies or demo_measure.SAMPLE:
        try:
            doc = json.loads((ipc / s / "closed.json").read_text(encoding="utf-8"))
            if doc.get("env") == "demo": out[s] = doc.get("closed") or []
        except (OSError, ValueError):
            pass
    return out


# The real account and the momentum day experiment (owner, 2026-11-06), in the same units (% of each trade's margin):
LIVE_START = datetime(2026, 11, 3, 15, 23, tzinfo=timezone.utc)   # momentum_ls real money (docs/live-small-size-plan.md)
LIVE_SAMPLE = 30                    # its first 3 real rebalances, 10 legs each, before any size change
EXPERIMENT = "momentum_wed"         # docs/momentum-wed-demo.md: Wednesday open, 6 days held, on Demo
EXPERIMENT_SAMPLE = 80              # 8 weeks of 10 legs before any conclusion

# The paper candidates against their own backtest (owner, 2026-11-08; lib/paper-baseline.json from
# research/paper_baseline.py), with demo_measure's rules. Samples fixed before any of their trades closed.
PUBLIC = Path(os.getenv("BOT_PUBLIC_DIR", "/var/www/bot.da3m.io"))   # the paper bots' public JSON
PAPER_BASELINE = ROOT / "lib" / "paper-baseline.json"
PAPER = {"rsi2_btc": ("RSI-2 + فلتر BTC (ورقي)", 15),          # as slow as RSI-2: 3 trades a month
         "retail_fade": ("ضد الجمهور، OI (ورقي)", 36)}          # 6 weekly baskets of 3 + 3


def paper_rows(doc):
    """A paper bot's public history as demo_measure rows: each trade's PnL in % of its margin."""
    try:
        margin = float(doc.get("margin") or 0)
    except (TypeError, ValueError):
        margin = 0.0
    if margin <= 0:
        return []
    out = []
    for h in doc.get("history") or []:
        try:
            out.append({**h, "pnl_pct": float(h["pnl"]) / margin * 100})
        except (KeyError, TypeError, ValueError):
            continue
    return out


def paper_lines(now, public=PUBLIC, baseline_path=PAPER_BASELINE):
    from app import demo_measure as dm
    lines = ["", "📄 البوتات الورقية الجديدة قصاد الباكتست بتاعها"]
    try:
        base = json.loads(baseline_path.read_text(encoding="utf-8")).get("strategies") or {}
    except (OSError, ValueError):
        return lines + ["   ملف الباكتست (lib/paper-baseline.json) مش موجود"]
    for name, (label, sample) in PAPER.items():
        try:
            doc = json.loads((public / f"{name}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            lines.append(f"• {label}: ملفه مش موجود"); continue
        start = dm._when(doc.get("started")) or now
        st = dm.stats(dm.counted(paper_rows(doc), start), now, start)
        status, reasons = dm.verdict(st, base.get(name), sample)
        b = (base.get(name) or {}).get("all") or {}
        lines.append(f"{ICON.get(status, '•')} {label}: {WORD.get(status, status)} — {st['trades']}/{sample} صفقة")
        if st["trades"]:
            lines.append(f"   {_line(st)}")
            lines.append(f"   الباكتست: PF {b.get('profit_factor')} · كسب {b.get('win_rate')}% · تراجع {b.get('max_dd_margins')} مارجن")
        lines += [f"   ↳ {why}" for why in reasons]
    return lines


# The three portfolios of research/README.md §31 on paper (owner, 2026-11-09: "three bots on paper, $100 x2 a coin").
# Each strategy is its own paper bot (one account each, §32), so a portfolio is the sum of its bots' closed trades,
# every trade scaled to $100 of margin (a bot that ran smaller earlier counts at the same weight), counting the trades
# opened from PORTFOLIO_START. A fixed date, not the bots' "started": that moves at every restart (the install of
# 2026-11-09 moved momentum's to 17:26) and would empty the portfolios each time. The page's section
# (deploy/vps/page/index.html, #pfSec) uses the same rule.
PORTFOLIO_MARGIN = 100.0
PORTFOLIO_START = datetime(2026, 11, 9, tzinfo=timezone.utc)
PORTFOLIO_BOTS = {"momentum": "مومنتم", "retail_fade": "ضد الجمهور", "rsi2_btc": "RSI-2 + BTC"}
PORTFOLIOS = {"مومنتم + ضد الجمهور": ("momentum", "retail_fade"),
              "مومنتم + RSI-2": ("momentum", "rsi2_btc"),
              "الثلاثة": ("momentum", "retail_fade", "rsi2_btc")}


def _when(x):
    try:
        t = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def portfolio_trades(doc, since=PORTFOLIO_START):
    """[(close time, PnL at $100 of margin)] of a paper bot's trades opened at or after `since` (its close time when
    the trade doesn't say when it opened)."""
    try:
        margin = float(doc.get("margin") or 0)
    except (TypeError, ValueError):
        margin = 0.0
    if margin <= 0:
        return []
    out = []
    for h in doc.get("history") or []:
        t = _when(h.get("time")); o = _when(h.get("opened")) or t
        try:
            pnl = float(h["pnl"]) * PORTFOLIO_MARGIN / margin
        except (KeyError, TypeError, ValueError):
            continue
        if t and o >= since:
            out.append((t, pnl))
    return out


def portfolio_lines(now, public=PUBLIC):
    lines = ["", f"🧺 المحافظ الثلاثة على الورق (كل عملة ${PORTFOLIO_MARGIN:.0f} × 2، كل استراتيجية حساب لوحدها)"]
    docs = {}
    for name in PORTFOLIO_BOTS:
        try:
            docs[name] = json.loads((public / f"{name}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    for label, bots in PORTFOLIOS.items():
        missing = [PORTFOLIO_BOTS[b] for b in bots if b not in docs]
        if missing:
            lines.append(f"• {label}: ملف {' و'.join(missing)} مش موجود"); continue
        trades = sorted(t for b in bots for t in portfolio_trades(docs[b]))
        eq = peak = dd = 0.0
        for _, pnl in trades:
            eq += pnl; peak = max(peak, eq); dd = max(dd, peak - eq)
        wins = sum(1 for _, p in trades if p > 0)
        open_ = sum(1 for b in bots for p in docs[b].get("positions") or [] if (_when(p.get("opened")) or now) >= PORTFOLIO_START)
        days = max(0, (now - PORTFOLIO_START).days)
        line = f"• {label}: من {PORTFOLIO_START.date()} ({days} يوم) — {len(trades)} صفقة"
        if trades:
            line += f"، كسب {wins / len(trades):.0%}، صافي ${eq:+,.0f}، أقصى تراجع ${dd:,.0f}"
        lines.append(line + f" · مفتوح دلوقتي {open_} (${open_ * PORTFOLIO_MARGIN:,.0f} مارجن)")
    lines.append("   الباكتست (§31): الثلاثة أنعم (Sharpe بعد 2024 1.60 وأخف أسوأ شهر)؛ مومنتم + ضد الجمهور أعلى ربح وأعلى تراجع")
    return lines


def _read(ipc, folder, env):
    try:
        doc = json.loads((ipc / folder / "closed.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return (doc.get("closed") or []) if doc.get("env") == env else None


def _line(st):
    f = lambda v, s="": "—" if v is None else f"{v}{s}"
    return (f"PF {f(st['profit_factor'])} · كسب {f(st['win_rate'], '%')} · متوسط الكسب {f(st['avg_win_pct'], '%')} / الخسارة "
            f"{f(st['avg_loss_pct'], '%')} · تراجع {st['max_dd_margins']} مارجن · صافي {st['net_margins']:+} مارجن")


def real_and_experiment(ipc, baseline, now):
    """The lines for the real momentum_ls and for the Wednesday experiment next to it over the same weeks."""
    from app import demo_measure as dm
    b = ((baseline or {}).get("strategies") or {}).get("momentum_ls") or {}
    lines = ["", "💰 الحساب الحقيقي — momentum (من 3 نوفمبر)"]
    live = _read(ipc, "momentum_ls", "live")
    live_counted = dm.counted(live, LIVE_START) if live is not None else []
    if live is None:
        lines.append("   ملف الصفقات المقفولة مش موجود")
    else:
        st = dm.stats(live_counted, now, LIVE_START)
        status, reasons = dm.verdict(st, b, LIVE_SAMPLE)
        lines.append(f"{ICON.get(status, '•')} {WORD.get(status, status)} — {st['trades']}/{LIVE_SAMPLE} رجل (أول 3 تبديلات)")
        if st["trades"]:
            lines.append(f"   {_line(st)}")
            dollars = sum(float(r.get("pnl") or 0) for r in live if (dm._when(r.get("time")) or LIVE_START) >= LIVE_START)
            base = b.get("all") or {}
            lines.append(f"   بالدولار: {dollars:+.2f}$ · الباكتست: PF {base.get('profit_factor')} · كسب {base.get('win_rate')}%")
        lines += [f"   ↳ {why}" for why in reasons]
    exp = _read(ipc, EXPERIMENT, "demo")
    lines += ["", "🧪 تجربة الأربع (Demo) قصاد الاتنين الحقيقي، نفس الأسابيع"]
    if not exp:
        lines.append("   لسه ما بدأتش (docs/momentum-wed-demo.md)")
        return lines
    opened = sorted(t for t in (dm._when(r.get("opened")) for r in exp) if t)
    start = opened[0] if opened else now
    e = dm.stats(dm.counted(exp, start), now, start)
    r = dm.stats([x for x in live_counted if x[0] >= start], now, start)
    lines.append(f"   الأربع: {e['trades']}/{EXPERIMENT_SAMPLE} رجل · {_line(e)}")
    lines.append(f"   الاتنين: {r['trades']} رجل · {_line(r)}")
    if e["trades"] >= EXPERIMENT_SAMPLE:
        lines.append("   ✅ الأربع مش أسوأ من الاتنين في نفس الأسابيع" if e["net_margins"] >= r["net_margins"]
                     else "   ❌ الأربع أسوأ من الاتنين في نفس الأسابيع: الحقيقي يفضل على الاتنين")
    else:
        lines.append(f"   ⏳ لسه بتجمع: القرار بعد {EXPERIMENT_SAMPLE} رجل (8 أسابيع)")
    return lines


def report(m, labels=None):
    """The Telegram text from demo_measure.measure(...)."""
    labels = labels or {}
    lines = [f"📊 قياس الـ Demo الأسبوعي (من {m['start'][:10]})"]
    fmt = lambda v, suffix="": "—" if v is None else f"{v}{suffix}"
    for s, r in m["strategies"].items():
        d, b = r["demo"], r["baseline"] or {}
        head = f"{ICON.get(r['status'], '•')} {labels.get(s, s)}: {WORD.get(r['status'], r['status'])}"
        if r["sample"] is None:
            lines.append(head); continue
        lines.append(f"{head} — {d['trades']}/{r['sample']} صفقة")
        if d["trades"]:
            lines.append(f"   PF {fmt(d['profit_factor'])} (الباكتست {fmt(b.get('profit_factor'))}) · كسب {fmt(d['win_rate'], '%')} "
                         f"({fmt(b.get('win_rate'), '%')}) · تراجع {d['max_dd_margins']} مارجن (الحد {round(m['dd_limit'] * (b.get('max_dd_margins') or 0), 1)}) "
                         f"· صافي {d['net_margins']:+} مارجن")
        for why in r["reasons"]:
            lines.append(f"   ↳ {why}")
    far = [s for s, r in m["strategies"].items() if r["status"] == "far"]
    lines.append("❌ " + "، ".join(labels.get(s, s) for s in far) + " عدّت العينة وبعيدة عن الباكتست: تتقفل، مش تتعدّل" if far
                 else "مفيش استراتيجية لازم تتقفل")
    return "\n".join(lines), len(far)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    from app import demo_measure
    try: baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    except (OSError, ValueError): baseline = None
    if baseline is None:
        text, far = "📊 قياس الـ Demo الأسبوعي: ملف الباكتست (lib/demo-baseline.json) مش موجود — مقدرناش نقارن", 0
    else:
        from app import strategy_catalog
        labels = strategy_catalog.NAME_AR                    # lib/strategies.json, the site's names
        now = datetime.now(timezone.utc)
        text, far = report(demo_measure.measure(load_closed(), baseline, now), labels)
        text += "\n" + "\n".join(real_and_experiment(IPC, baseline, now))
        text += "\n" + "\n".join(paper_lines(now))
        text += "\n" + "\n".join(portfolio_lines(now))
    print(text)
    if "--telegram" in argv:
        sys.path.insert(0, str(ROOT / "scripts")); import watchdog
        for part in watchdog.chunks(text.split("\n")): watchdog.send(part)
    return 1 if far else 0


if __name__ == "__main__":
    sys.exit(main())
