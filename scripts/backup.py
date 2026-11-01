"""Daily backup of the real-orders bots' records, off the server, on Telegram (owner, 2026-11-01).

The positions themselves are safe on Binance with their stops if the VPS disk is lost; their records are not: each
Demo / live bot's state and execution journal, the risk ledgers (Demo and live), the yes/no per strategy, the watchdog
state and the logs — the measurement history. One .tar.gz a day (about 1 MB), sent silently (no notification sound) to
the watchdog's chat. SQLite files are copied with SQLite's backup API, so a copy taken while a bot writes is consistent.
No keys: the key files live elsewhere and are not read. The paper bots (/opt/raqm-bot) are another OS user's and are
not included. Run daily by raqm-backup.timer as raqmlive; a failure says so in the chat.

  sudo -u raqmlive sh -c 'set -a; . /opt/raqm-live/.env.telegram; set +a; cd /opt/raqm-live && venv/bin/python -E -s scripts/backup.py'
"""
import io, json, os, sqlite3, sys, tarfile, tempfile, urllib.request, uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = {"state": ROOT / "state", "risk-demo": Path("/opt/raqm-risk-demo"), "risk-live": Path("/opt/raqm-risk")}
SKIP = (".tmp", "-journal", "-wal", "-shm")
LIMIT = 45 * 1024 * 1024     # Telegram takes files up to 50 MB from a bot


def build(now, sources=SOURCES, skip=SKIP):
    """(archive bytes, file count). Every regular file under each source, SQLite through its backup API."""
    buf, n = io.BytesIO(), 0
    with tarfile.open(fileobj=buf, mode="w:gz") as tar, tempfile.TemporaryDirectory() as td:
        for name, root in sources.items():
            if not root.is_dir():
                continue
            for f in sorted(p for p in root.rglob("*") if p.is_file() and not p.is_symlink() and not p.name.endswith(skip)):
                arc = f"raqm-backup-{now:%Y%m%d}/{name}/{f.relative_to(root).as_posix()}"
                if f.suffix in (".sqlite3", ".db"):
                    copy = Path(td) / uuid.uuid4().hex
                    src = sqlite3.connect(f"file:{f.as_posix()}?mode=ro", uri=True); dst = sqlite3.connect(copy)
                    try:
                        src.backup(dst)
                    finally:
                        dst.close(); src.close()
                    tar.add(copy, arcname=arc)
                else:
                    tar.add(f, arcname=arc)
                n += 1
    return buf.getvalue(), n


USERS_DATA = Path("/var/lib/raqm-users")     # Phase 2 (docs/phase2-design.md): one folder per user, theirs alone
USERS_CODE = Path("/opt/raqm-users/code")


def users_archive(now, data_root=USERS_DATA, dump=None):
    """(archive bytes, user count) of every user's ledger and bot state, for raqm-backup-users (root). Each user's own
    archive is built AS that user (runuser), so their SQLite ledger is copied by its owner with the backup API and root
    never opens anything inside their folders; root only bundles the bytes. Their key credentials are not included."""
    import re, subprocess
    # `env -i`: the user's process gets an empty environment — root's has the owner's Telegram token
    dump = dump or (lambda uid, d: subprocess.run(
        ["runuser", "-u", "ru" + uid.replace("-", "")[:20], "--", "/usr/bin/env", "-i", "PATH=/usr/bin:/bin",
         str(USERS_CODE / "venv/bin/python"), "-E", "-s", str(USERS_CODE / "scripts/backup.py"), "--dump", str(d)],
        capture_output=True, check=True, timeout=300).stdout)
    buf, n, failed = io.BytesIO(), 0, []
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for d in sorted(data_root.iterdir()) if data_root.is_dir() else []:
            if not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", d.name) or d.is_symlink():
                continue
            try:
                blob = dump(d.name, d)
            except Exception as e:                # one user's part failing doesn't lose everyone else's backup
                failed.append(f"{d.name[:8]}: {type(e).__name__}"); continue
            info = tarfile.TarInfo(f"raqm-users-backup-{now:%Y%m%d}/{d.name}.tar.gz"); info.size = len(blob)
            tar.addfile(info, io.BytesIO(blob)); n += 1
    if failed:
        raise PartialBackup(buf.getvalue(), n, failed)
    return buf.getvalue(), n


class PartialBackup(Exception):
    """Some users' parts failed: the rest is still sent, and the chat is told whose failed."""
    def __init__(self, data, n, failed):
        super().__init__(", ".join(failed)); self.data, self.n, self.failed = data, n, failed


def _post(method, fields, files=None):
    tok = os.getenv("TELEGRAM_BOT_TOKEN", "")
    boundary = uuid.uuid4().hex; body = io.BytesIO()
    for k, v in fields.items():
        body.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for k, (fname, data) in (files or {}).items():
        body.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{fname}"\r\n'
                   f'Content-Type: application/gzip\r\n\r\n'.encode()); body.write(data); body.write(b"\r\n")
    body.write(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/{method}", data=body.getvalue(),
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        if not json.loads(r.read()).get("ok"):
            raise RuntimeError(f"telegram {method} refused")


def main():
    argv = sys.argv[1:]
    now = datetime.now(timezone.utc)
    if argv[:1] == ["--dump"]:            # as one user, from users_archive(): their own folders, to stdout
        d = Path(argv[1])          # the logs stay out: never rotated, they would outgrow Telegram's limit
        sys.stdout.buffer.write(build(now, {"risk": d / "risk", "state": d / "state"}, skip=SKIP + (".log",))[0]); return
    users = argv[:1] == ["--users"]
    chat = os.getenv("TELEGRAM_CHAT_ID", "")
    if not (os.getenv("TELEGRAM_BOT_TOKEN") and chat):
        raise SystemExit("backup: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set")
    partial = None
    try:
        try:
            data, n = users_archive(now) if users else build(now)
        except PartialBackup as e:
            data, n, partial = e.data, e.n, e
        if users and not n:
            return                         # no user yet: nothing to send
        if len(data) > LIMIT:
            raise RuntimeError(f"archive {len(data) // 1048576} MB is over Telegram's limit")
        what = "بوتات المستخدمين" if users else "يومية"
        _post("sendDocument", {"chat_id": chat, "disable_notification": "true",
                               "caption": f"💾 نسخة احتياطية {what} — {n} {'مستخدم' if users else 'ملف'} · {len(data) / 1048576:.1f} MB"},
              {"document": (f"raqm-{'users-' if users else ''}backup-{now:%Y%m%d}.tar.gz", data)})
        if partial:
            _post("sendMessage", {"chat_id": chat, "text": f"🚨 نسخة بعض المستخدمين ما اتعملتش: {partial}"})
    except Exception as e:
        _post("sendMessage", {"chat_id": chat, "text": f"🚨 النسخة الاحتياطية اليومية ما اتعملتش: {type(e).__name__}: {e}"})
        raise


if __name__ == "__main__":
    main()
