"""The weekly Demo check against the backtest baseline, to Telegram (roadmap B5, development-plan 6.1).

The same measurement as the admin page (backend/app/demo_measure.py, rules agreed on 2026-11-01): each strategy's own
closed Demo trades since the start, against lib/demo-baseline.json, its sample and its status. Read only: the bots'
closed.json files and the baseline.

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
        text, far = report(demo_measure.measure(load_closed(), baseline, datetime.now(timezone.utc)), labels)
    print(text)
    if "--telegram" in argv:
        sys.path.insert(0, str(ROOT / "scripts")); import watchdog
        for part in watchdog.chunks(text.split("\n")): watchdog.send(part)
    return 1 if far else 0


if __name__ == "__main__":
    sys.exit(main())
