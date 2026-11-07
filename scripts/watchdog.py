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
from backend.app import live_accounts

STRATEGIES = ("trend_daily", "vol_breakout", "rsi2_pullback", "trend_breakout", "listing_short", "momentum_ls", "ratio_trend")
LEDGERS = {"demo": Path("/opt/raqm-risk-demo"), "live": Path("/opt/raqm-risk")}
IPC = Path(os.getenv("RAQM_IPC_ROOT", "/opt/raqm-ipc"))
STATE = ROOT / "state" / "watchdog.json"
HEARTBEAT = IPC / "watchdog_heartbeat.json"   # read by the API's public /api/health/bots, for a check from outside the server
STALE_S = 300            # the bots write their status every minute
ENV_NAME = {"demo": "Demo", "live": "فلوس حقيقية"}
FOREIGN = "صفقات على المنصة البوت مفتحهاش"   # bot.py reconcile_live's entry block for a position it didn't open


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
    if block and FOREIGN in block and env == "live":
        # a position the bot didn't open on a real account (owner, 2026-11-07: a manual EVAA trade stopped every entry
        # for hours before the alert): at the first check, saying what it blocks and what to do
        coins = block.split(FOREIGN, 1)[1].strip(" :")
        out[f"foreign:{key}"] = (f"صفقة على حساب {who} البوت ما فتحهاش: {coins} — البوت وقف أي دخول جديد، والتبديل الجاي "
                                 f"هيقفل السلة القديمة ومش هيفتح الجديدة. اقفلها وامسح أي أمر مفتوح عليها (الحساب ده للبوت لوحده)", 1)
    elif block and "kill switch" not in block:        # the kill switch has its own alert, once per account
        out[f"block:{key}"] = (f"الدخول متوقف في {who}: {block}", 2)
    return st


def _read_status(path, limit=1 << 20):
    """A bot's status file, not followed through a symlink (the users' watchdog reads other accounts' folders), and
    opened non-blocking with a regular-file check: a FIFO in its place must not hang the watchdog."""
    import stat
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("not a regular file")
        return os.read(fd, limit).decode("utf-8")
    finally:
        os.close(fd)


def named_unit(name):
    """(enabled, active) of a unit by its full name (a copy account's raqm-live-<name>@<strategy>)."""
    run = lambda *a: subprocess.run(["systemctl", *a, name], capture_output=True, text=True).stdout.strip()
    return run("is-enabled") == "enabled", run("is-active") == "active"


def problems(now, unit=unit, ipc=IPC, ledgers=LEDGERS, failed=None, accounts=None, risk_root=live_accounts.RISK_ROOT,
             copies=None, copy_unit=named_unit):
    """Every problem seen now: {key: (text, checks in a row before alerting)}. A live strategy on its own Binance
    account (backend/app/live_accounts.py) has its own ledger, so its own kill switch and alert; so does a copy of a
    strategy on a copy account, watched through its own unit and status folder."""
    out = {}
    if accounts is None or copies is None:
        try:
            accounts = live_accounts.load() if accounts is None else accounts
            copies = live_accounts.load_copies() if copies is None else copies
        except live_accounts.RegistryError as e:
            out["accounts"] = (f"ملف الحسابات الحقيقية (accounts.json) مش سليم: {e}", 1)
            accounts, copies = accounts or {}, copies or {}
    for env in ("demo", "live"):
        watched = set()
        for s in STRATEGIES:
            enabled, active = unit(env, s)
            if not enabled: continue
            watched.add(live_accounts.account_of(s, accounts) if env == "live" else None)
            check_bot(out, now, f"{env}:{s}", f"{s} ({ENV_NAME[env]})", env, active, ipc / s / "live_status.json")
        if env == "live":
            for acct, ss in sorted(copies.items()):
                for s in ss:
                    enabled, active = copy_unit(live_accounts.copy_unit_name(acct, s))
                    if not enabled: continue
                    watched.add(acct)
                    check_bot(out, now, f"live:{acct}:{s}", f"{s} ({ENV_NAME['live']} · {acct})", "live", active,
                              live_accounts.copy_ipc(acct, s, ipc) / "live_status.json")
        for acct in sorted(watched, key=lambda a: a or ""):
            key = env if acct is None else f"{env}:{acct}"
            name = ENV_NAME[env] if acct is None else f"{ENV_NAME[env]} ({acct})"
            ledger = ledgers[env] if acct is None else live_accounts.paths(acct, risk_root=risk_root)["risk"]
            if acct is not None and not live_accounts.ledger_exists(ledger):    # not created here, as the watchdog
                out[f"ledger:{key}"] = (f"ملف المخاطر بتاع {name} لسه مش موجود ({ledger})", 2); continue
            try:
                ks = riskmgr.load_risk_state(ledger / "risk_state.json")["kill_switch"]
                if ks.get("tripped"):
                    out[f"kill:{key}"] = (f"قفل الطوارئ اشتغل على حساب {name} — مفيش دخول جديد لأي استراتيجية: {ks.get('reason')}", 1)
            except Exception as e:
                out[f"ledger:{key}"] = (f"ملف المخاطر بتاع {name} مش بيتقري: {e}", 2)
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


# The server itself (development-plan 2.4): what stops every bot at once without any bot being "down" first.
DOMAINS = ("api.da3m.io", "demo.da3m.io", "realbot.da3m.io")   # this server's sites (it also hosts others, not ours)
DISK_MIN_FREE = (0.10, 5 * 1024 ** 3)   # under 10 % or 5 GB free: SQLite ledgers and logs start failing to write
MEM_MIN_AVAILABLE = 0.10
CLOCK_MAX_OFFSET_MS = 1000              # Binance refuses requests outside recvWindow (5 s): alert well before
CERT_MIN_DAYS = 14                      # certbot renews at 30 days left: 14 means renewal has been failing


def _disk(path="/"):
    import shutil
    u = shutil.disk_usage(path); return u.free, u.total


def _mem():
    m = {l.split(":")[0]: int(l.split()[1]) * 1024 for l in Path("/proc/meminfo").read_text().splitlines() if l.split()[1:2]}
    return m["MemAvailable"], m["MemTotal"]


def _ntp_synced():
    r = subprocess.run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"], capture_output=True, text=True, timeout=10)
    if r.returncode: raise OSError(r.stderr.strip())        # can't tell: skipped, not alerted
    return r.stdout.strip() == "yes"


def _binance_offset_ms():
    """Local clock minus Binance's (ms), or None when Binance can't be reached (the bots report that themselves)."""
    import time
    try:
        t0 = time.time()
        with urllib.request.urlopen("https://fapi.binance.com/fapi/v1/time", timeout=5) as r:
            server = json.loads(r.read())["serverTime"]
        return (t0 + time.time()) / 2 * 1000 - server
    except Exception:
        return None


def _cert_days(host, now):
    """Days until the certificate `host` serves expires (a failed TLS check raises)."""
    import socket, ssl
    ctx = ssl.create_default_context()
    with socket.create_connection((host, 443), timeout=8) as s, ctx.wrap_socket(s, server_hostname=host) as t:
        end = datetime.fromtimestamp(ssl.cert_time_to_seconds(t.getpeercert()["notAfter"]), timezone.utc)
    return (end - now).total_seconds() / 86400


def _api_vault():
    """The API's word on users' Demo key vault ("ok" / "empty" / "unreadable"), or None when the API doesn't answer.
    Asked over localhost: the watchdog runs as raqmlive and must not read the API's key or vault itself."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:8100/api/health", timeout=5) as r:
            return json.loads(r.read()).get("vault")
    except Exception:
        return None


def server_problems(now, disk=_disk, mem=_mem, ntp=_ntp_synced, offset=_binance_offset_ms, cert=_cert_days, domains=DOMAINS,
                    vault=_api_vault):
    """{key: (text, checks in a row before alerting)} for the server. A check that can't run is skipped, not alerted
    (it would page every 5 minutes for a missing tool) — except a site that doesn't answer on HTTPS at all."""
    out = {}
    try:
        free, total = disk()
        if free < DISK_MIN_FREE[1] or free < DISK_MIN_FREE[0] * total:
            out["server:disk"] = (f"مساحة السيرفر قربت تخلص: فاضل {free / 1024 ** 3:.1f} GB من {total / 1024 ** 3:.0f} GB", 2)
    except Exception: pass
    try:
        avail, total = mem()
        if avail < MEM_MIN_AVAILABLE * total:
            out["server:mem"] = (f"ذاكرة السيرفر قربت تخلص: فاضل {avail / 1024 ** 2:.0f} MB من {total / 1024 ** 2:.0f} MB", 2)
    except Exception: pass
    try:
        if not ntp():
            out["server:ntp"] = ("ساعة السيرفر مش متزامنة (NTP) — Binance بيرفض الطلبات لو الساعة بعدت", 3)
    except Exception: pass
    off = offset()
    if off is not None and abs(off) > CLOCK_MAX_OFFSET_MS:
        out["server:clock"] = (f"ساعة السيرفر بعيدة عن Binance بـ {off / 1000:+.1f} ثانية", 2)
    if vault() == "unreadable":
        out["server:vault"] = ("مفاتيح Demo بتاعة اليوزرز مش بتتفك (VAULT_MASTER_KEY مش هو اللي اتشفرت بيه) — محدش يقدر يحفظ أو يشغّل مفتاح", 2)
    for host in domains:
        try:
            days = cert(host, now)
            if days < CERT_MIN_DAYS:
                out[f"cert:{host}"] = (f"شهادة HTTPS بتاعة {host} بتخلص بعد {max(days, 0):.0f} يوم — التجديد التلقائي مش شغال", 1)
        except Exception as e:
            out[f"site:{host}"] = (f"{host} مش بيرد على HTTPS: {type(e).__name__}", 3)
    return out


def checks(now, users=False):
    """problems() and the server's, or one problem saying the watchdog itself can't look: a crash here used to mean silence."""
    try:
        if users:
            return user_problems(now)
        out = problems(now)
        out.update(server_problems(now))
        return out
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
