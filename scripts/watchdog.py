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
HEARTBEAT = IPC / "watchdog_heartbeat.json"   # read by the API's public /api/health/bots, for a check from outside the server
STALE_S = 300            # the bots write their status every minute
ENV_NAME = {"demo": "Demo", "live": "فلوس حقيقية"}


def unit(env, strategy):
    """(enabled, active) of raqm-<env>@<strategy>."""
    name = f"raqm-{env}@{strategy}"
    run = lambda *a: subprocess.run(["systemctl", *a, name], capture_output=True, text=True).stdout.strip()
    return run("is-enabled") == "enabled", run("is-active") == "active"


def check_bot(out, now, key, who, env, active, status_path):
    """One bot's problems into `out`; returns its status (None when it isn't running or writing one)."""
    if not active:
        out[f"down:{key}"] = (f"البوت {who} واقف", 2); return None
    try:
        st = json.loads(_read_status(status_path))
        age = (now - datetime.fromisoformat(st["updated"])).total_seconds()
    except Exception:
        out[f"stale:{key}"] = (f"البوت {who} مش بيكتب حالته", 2); return None
    if env and st.get("env") not in (None, env):   # Demo and real money share a strategy's folder: the other one's leftover
        out[f"stale:{key}"] = (f"البوت {who} لسه ما كتبش حالته (الملف من {st.get('env')})", 2); return None
    if age > STALE_S:
        out[f"stale:{key}"] = (f"البوت {who} ما حدّثش حالته من {int(age // 60)} دقيقة", 2); return None
    for p in st.get("positions") or []:
        if p.get("unprotected") or p.get("sl_unverified"):
            why = "من غير وقف خسارة على Binance" if p.get("unprotected") else "مش متأكدين إن وقف الخسارة على Binance"
            out[f"stop:{key}:{p.get('symbol')}"] = (f"{p.get('symbol')} في {who} {why}", 1)
    if st.get("review"):
        out[f"review:{key}"] = (f"{who} محتاج مراجعة: " + " · ".join(f"{k.split(':')[0]} ({(v or {}).get('reason')})" for k, v in st["review"].items()), 1)
    block = st.get("entry_block") or ""
    if block and "kill switch" not in block:          # the kill switch has its own alert, once per account
        out[f"block:{key}"] = (f"الدخول متوقف في {who}: {block}", 2)
    return st


def _read_status(path, limit=1 << 20):
    """A bot's status file, not followed through a symlink (the users' watchdog reads other accounts' folders)."""
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        return os.read(fd, limit).decode("utf-8")
    finally:
        os.close(fd)


def problems(now, unit=unit, ipc=IPC, ledgers=LEDGERS, failed=None):
    """Every problem seen now: {key: (text, checks in a row before alerting)}."""
    out = {}
    for env in ("demo", "live"):
        watched = False
        for s in STRATEGIES:
            enabled, active = unit(env, s)
            if not enabled: continue
            watched = True
            check_bot(out, now, f"{env}:{s}", f"{s} ({ENV_NAME[env]})", env, active, ipc / s / "live_status.json")
        if watched:
            try:
                ks = riskmgr.load_risk_state(ledgers[env] / "risk_state.json")["kill_switch"]
                if ks.get("tripped"):
                    out[f"kill:{env}"] = (f"قفل الطوارئ اشتغل على حساب {ENV_NAME[env]} — مفيش دخول جديد لأي استراتيجية: {ks.get('reason')}", 1)
            except Exception as e:
                out[f"ledger:{env}"] = (f"ملف المخاطر بتاع {ENV_NAME[env]} مش بيتقري: {e}", 2)
    if (failed or _unit_failed)("raqm-watchdog-users.service"):      # the users' watchdog can't report its own crash
        out["watchdog-users"] = ("مراقب بوتات المستخدمين نفسه واقع (raqm-watchdog-users)", 2)
    return out


def _unit_failed(name):
    try:
        return subprocess.run(["systemctl", "is-failed", "--quiet", name], capture_output=True).returncode == 0
    except Exception:
        return False


# ── users' bots (Phase 2, docs/phase2-design.md): run as root with only CAP_DAC_READ_SEARCH (raqm-watchdog-users), so
# it can read every user's status and write nothing of theirs. Their kill switch shows in their status (entry_block).
USER_UNITS = Path("/etc/systemd/system")
USER_IPC = Path("/opt/raqm-users/ipc")
USER_STATE = Path("/var/lib/raqm-watchdog-users/state.json")


def user_bots(unit_dir=USER_UNITS):
    """[(uid, strategy)] of the users' bots the provisioner set up (one drop-in each)."""
    out = []
    for f in sorted(unit_dir.glob("raqm-user@*--*.service.d/user.conf")):
        uid, _, s = f.parent.name[len("raqm-user@"):-len(".service.d")].partition("--")
        if len(uid) == 36 and s in STRATEGIES:
            out.append((uid, s))
    return out


def _user_active(uid, s):
    r = subprocess.run(["systemctl", "is-active", f"raqm-user@{uid}--{s}.service"], capture_output=True, text=True)
    return r.stdout.strip() == "active"


def user_problems(now, bots=None, active=_user_active, ipc=USER_IPC):
    out = {}
    for uid, s in (user_bots() if bots is None else bots):
        who = f"{s} (مستخدم {uid[:8]})"
        st = check_bot(out, now, f"user:{uid}:{s}", who, None, active(uid, s), ipc / uid / s / "live_status.json")
        if st and "kill switch" in (st.get("entry_block") or ""):
            out[f"kill:user:{uid}"] = (f"قفل الطوارئ اشتغل على حساب المستخدم {uid[:8]}: {st['entry_block']}", 1)
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


LIMIT = 3900                 # Telegram refuses a message over 4096 characters — with every position unprotected at once


def chunks(lines, limit=LIMIT):
    """The alert lines in messages Telegram accepts; a single line longer than the limit is cut."""
    out, cur = [], ""
    for line in lines:
        line = line[:limit]
        if cur and len(cur) + 1 + len(line) > limit:
            out.append(cur); cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    return out + ([cur] if cur else [])


def send(text):
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
    if not (tok and chat):
        print(text); return
    body = json.dumps({"chat_id": chat, "text": text, "disable_web_page_preview": True}).encode()
    urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=body,
                           headers={"Content-Type": "application/json"}), timeout=15)


def checks(now, users=False):
    """problems(), or one problem saying the watchdog itself can't look: a crash here used to mean silence."""
    try:
        return user_problems(now) if users else problems(now)
    except Exception as e:
        return {"watchdog": (f"المراقب نفسه مش قادر يفحص البوتات: {type(e).__name__}: {e}", 2)}


def heartbeat(now, state, path=HEARTBEAT):
    """When this run finished and how many problems are alerted, no details: the API serves it to an uptime check
    outside the server, which alerts when it goes stale (the VPS down, the timer stopped) — the case this watchdog,
    running on the same server, can't report. Best effort: a failure here must not stop the alerts."""
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"at": now.isoformat(), "problems": sum(1 for v in state.values() if v.get("sent"))}), encoding="utf-8")
        os.chmod(tmp, 0o640); tmp.replace(path)
    except Exception as e:
        print(f"heartbeat: {e}")


def main(argv=None):
    users = "--users" in (sys.argv[1:] if argv is None else argv)   # the users' bots, from raqm-watchdog-users
    path = USER_STATE if users else STATE
    try: prev = json.loads(path.read_text(encoding="utf-8"))
    except Exception: prev = {}
    state, msgs = step(prev, checks(datetime.now(timezone.utc), users))
    if msgs:
        try:
            for part in chunks(["🐶 مراقب رقم" + (" — بوتات المستخدمين" if users else "")] + msgs): send(part)
        except Exception as e:                                # not marked sent: tried again next run
            print(f"telegram: {e}"); state = {k: {**v, "sent": prev.get(k, {}).get("sent", False)} for k, v in state.items()}
            state.update({k: v for k, v in prev.items() if k not in state and v.get("sent")})
    tmp = path.with_suffix(".tmp"); tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8"); tmp.replace(path)
    if not users:                 # the owner's watchdog watches the users' one (problems: watchdog-users)
        heartbeat(datetime.now(timezone.utc), state)


if __name__ == "__main__":
    main()
