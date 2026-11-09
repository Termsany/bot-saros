"""Each account's own activity (security plan item 10, owner 2026-11-08): every new sign-in session the API sees (when,
the device, the IP) and every sensitive change (real money, keys, admin actions), on a page the user reads
(/settings/activity). Someone using a stolen password or session shows up there, and an admin's new session is also
sent to the owner's Telegram.

Never raises into the request: a full disk or a locked file must not stop a sign-in or a change. Nothing secret is
stored: no token (only Supabase's session id, which opens nothing), no key; the details are the short ones the audit
log keeps. 180 days and 300 rows per account are kept.
"""
from __future__ import annotations
import json, os, re, sqlite3, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# next to the API's other records (/opt/raqm-api/app, kept by the updater's git reset: untracked, .gitignore)
DEFAULT_PATH = Path(os.getenv("RAQM_ACTIVITY_DB") or Path(__file__).resolve().parent.parent.parent / "account_activity.sqlite3")
KEEP_DAYS, KEEP_ROWS = 180, 300
_SEEN: dict = {}            # (uid, session id) -> time: one database write per session, not one per request
_SEEN_MAX = 5000


def _connect(path):
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p), timeout=3.0, isolation_level=None); con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS activity (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL,
        uid TEXT, email TEXT, kind TEXT NOT NULL, what TEXT NOT NULL, ip TEXT, device TEXT, session TEXT, details TEXT)""")
    con.execute("CREATE INDEX IF NOT EXISTS activity_uid ON activity(uid, id)")
    con.execute("CREATE INDEX IF NOT EXISTS activity_email ON activity(email, id)")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS activity_session ON activity(uid, session) WHERE kind = 'session'")
    return con


def device(ua: str | None) -> str:
    """A short name for a User-Agent ("Chrome · Windows"), never the whole string."""
    ua = ua or ""
    browser = next((name for pat, name in ((r"Edg/", "Edge"), (r"OPR/|Opera", "Opera"), (r"SamsungBrowser", "Samsung"),
                                           (r"Firefox/", "Firefox"), (r"Chrome/|CriOS/", "Chrome"), (r"Safari/", "Safari"),
                                           (r"curl/|python|httpx|Go-http", "برنامج")) if re.search(pat, ua)), "متصفح")
    system = next((name for pat, name in ((r"iPhone|iPad", "iPhone/iPad"), (r"Android", "Android"), (r"Windows", "Windows"),
                                          (r"Mac OS X|Macintosh", "Mac"), (r"Linux", "Linux")) if re.search(pat, ua)), "")
    return f"{browser} · {system}" if system else browser


def _prune(con, uid, email):
    cut = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).isoformat()
    con.execute("DELETE FROM activity WHERE at < ?", (cut,))
    for col, val in (("uid", uid), ("email", email)):
        if val:
            con.execute(f"DELETE FROM activity WHERE {col} = ? AND id NOT IN (SELECT id FROM activity WHERE {col} = ? "
                        f"ORDER BY id DESC LIMIT ?)", (val, val, KEEP_ROWS))


def record(kind: str, what: str, *, uid=None, email=None, ip=None, ua=None, session=None, details=None, path=None) -> bool:
    """One row; False (never an exception) when it couldn't be written."""
    try:
        con = _connect(path or DEFAULT_PATH)
        try:
            d = json.dumps(details, ensure_ascii=False, default=str, sort_keys=True)[:500] if details else None
            cur = con.execute("INSERT OR IGNORE INTO activity(at,uid,email,kind,what,ip,device,session,details) VALUES(?,?,?,?,?,?,?,?,?)",
                              (datetime.now(timezone.utc).isoformat(), uid, (email or "").lower() or None, kind, what,
                               (ip or "")[:64] or None, device(ua) if ua is not None else None, session, d))
            _prune(con, uid, (email or "").lower() or None)
            return cur.rowcount == 1
        finally:
            con.close()
    except Exception as e:
        print(f"account activity not recorded: {type(e).__name__}")
        return False


def session_seen(user: dict, session: str | None, ip=None, ua=None, path=None) -> bool:
    """True the first time a sign-in session is seen for this account (recorded once; later requests cost nothing)."""
    uid = user.get("id")
    if not uid or not session:
        return False
    key = (uid, session)
    if key in _SEEN:
        return False
    if len(_SEEN) > _SEEN_MAX:
        _SEEN.clear()
    _SEEN[key] = time.time()
    return record("session", "دخول جديد", uid=uid, email=user.get("email"), ip=ip, ua=ua, session=session, path=path)


def list_for(user: dict, limit: int = 100, path=None) -> list[dict]:
    """This account's rows, newest first: by its id, and the admin actions done under its email."""
    try:
        con = _connect(path or DEFAULT_PATH)
        try:
            rows = con.execute("SELECT at,kind,what,ip,device,details FROM activity WHERE uid = ? OR (uid IS NULL AND email = ?) "
                               "ORDER BY id DESC LIMIT ?", (user.get("id"), (user.get("email") or "").lower() or None,
                                                            max(1, min(int(limit), KEEP_ROWS)))).fetchall()
        finally:
            con.close()
    except Exception:
        return []
    out = []
    for r in rows:
        row = dict(r)
        try:
            row["details"] = json.loads(row["details"]) if row["details"] else None
        except ValueError:
            row["details"] = None
        out.append(row)
    return out
