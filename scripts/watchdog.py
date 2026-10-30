"""Problem alerts for the real-orders bots (Demo and live), on Telegram — problems only, no daily report.

Run every 5 minutes (raqm-watchdog.timer) as raqmlive. For every enabled raqm-demo@/raqm-live@ unit: the service is
running and writing its status, no position without a stop on the exchange, nothing waiting for a review, entries not
blocked for long (an unknown position on the account, equity unavailable...); for each account: the kill switch. One
message when a problem starts (after two checks in a row for the ones a restart or a one-off network error explains),
one when it clears. One process for every bot, so a problem shared by all seven sends one message, not seven.
Read only: it never sends an order and never changes a setting.

  sudo -u raqmlive sh -c 'set -a; . /opt/raqm-live/.env.telegram; set +a; cd /opt/raqm-live && venv/bin/python -E -s scripts/watchdog.py'
"""
import json, os, subprocess, sys, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend.app import risk_manager as riskmgr

STRATEGIES = ("trend_daily", "vol_breakout", "rsi2_pullback", "trend_breakout", "listing_short", "momentum_ls", "ratio_trend")
LEDGERS = {"demo": Path("/opt/raqm-risk-demo"), "live": Path("/opt/raqm-risk")}
IPC = Path(os.getenv("RAQM_IPC_ROOT", "/opt/raqm-ipc"))
STATE = ROOT / "state" / "watchdog.json"
STALE_S = 300            # the bots write their status every minute
ENV_NAME = {"demo": "Demo", "live": "فلوس حقيقية"}


def unit(env, strategy):
    """(enabled, active) of raqm-<env>@<strategy>."""
    name = f"raqm-{env}@{strategy}"
    run = lambda *a: subprocess.run(["systemctl", *a, name], capture_output=True, text=True).stdout.strip()
    return run("is-enabled") == "enabled", run("is-active") == "active"


def problems(now, unit=unit, ipc=IPC, ledgers=LEDGERS):
    """Every problem seen now: {key: (text, checks in a row before alerting)}."""
    out = {}
    for env in ("demo", "live"):
        watched = False
        for s in STRATEGIES:
            enabled, active = unit(env, s)
            if not enabled: continue
            watched = True; who = f"{s} ({ENV_NAME[env]})"
            if not active:
                out[f"down:{env}:{s}"] = (f"البوت {who} واقف", 2); continue
            try:
                st = json.loads((ipc / s / "live_status.json").read_text(encoding="utf-8"))
                age = (now - datetime.fromisoformat(st["updated"])).total_seconds()
            except Exception:
                out[f"stale:{env}:{s}"] = (f"البوت {who} مش بيكتب حالته", 2); continue
            if st.get("env") not in (None, env): continue
            if age > STALE_S:
                out[f"stale:{env}:{s}"] = (f"البوت {who} ما حدّثش حالته من {int(age // 60)} دقيقة", 2); continue
            for p in st.get("positions") or []:
                if p.get("unprotected") or p.get("sl_unverified"):
                    why = "من غير وقف خسارة على Binance" if p.get("unprotected") else "مش متأكدين إن وقف الخسارة على Binance"
                    out[f"stop:{env}:{s}:{p.get('symbol')}"] = (f"{p.get('symbol')} في {who} {why}", 1)
            if st.get("review"):
                out[f"review:{env}:{s}"] = (f"{who} محتاج مراجعة: " + " · ".join(f"{k.split(':')[0]} ({(v or {}).get('reason')})" for k, v in st["review"].items()), 1)
            block = st.get("entry_block") or ""
            if block and "kill switch" not in block:          # the kill switch has its own alert, once per account
                out[f"block:{env}:{s}"] = (f"الدخول متوقف في {who}: {block}", 2)
        if watched:
            try:
                ks = riskmgr.load_risk_state(ledgers[env] / "risk_state.json")["kill_switch"]
                if ks.get("tripped"):
                    out[f"kill:{env}"] = (f"قفل الطوارئ اشتغل على حساب {ENV_NAME[env]} — مفيش دخول جديد لأي استراتيجية: {ks.get('reason')}", 1)
            except Exception as e:
                out[f"ledger:{env}"] = (f"ملف المخاطر بتاع {ENV_NAME[env]} مش بيتقري: {e}", 2)
    return out


def step(prev, seen):
    """(new state, messages): alert once a problem was seen its number of checks in a row; say when it clears."""
    state, msgs = {}, []
    for key, (text, need) in seen.items():
        p = dict(prev.get(key) or {}); p["count"] = p.get("count", 0) + 1; p["text"] = text
        if p["count"] >= need and not p.get("sent"):
            msgs.append(f"🚨 {text}"); p["sent"] = True
        state[key] = p
    for key, p in prev.items():
        if key not in seen and p.get("sent"):
            msgs.append(f"✅ اتحلت: {p.get('text')}")
    return state, msgs


def send(text):
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
    if not (tok and chat):
        print(text); return
    body = json.dumps({"chat_id": chat, "text": text, "disable_web_page_preview": True}).encode()
    urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=body,
                           headers={"Content-Type": "application/json"}), timeout=15)


def main():
    try: prev = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception: prev = {}
    state, msgs = step(prev, problems(datetime.now(timezone.utc)))
    if msgs:
        try: send("🐶 مراقب رقم\n" + "\n".join(msgs))
        except Exception as e:                                # not marked sent: tried again next run
            print(f"telegram: {e}"); state = {k: {**v, "sent": prev.get(k, {}).get("sent", False)} for k, v in state.items()}
            state.update({k: v for k, v in prev.items() if k not in state and v.get("sent")})
    tmp = STATE.with_suffix(".tmp"); tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8"); tmp.replace(STATE)


if __name__ == "__main__":
    main()
