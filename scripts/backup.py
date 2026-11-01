"""Daily backup of the real-orders bots' records, off the server, on Telegram (owner, 2026-11-01).

The positions themselves are safe on Binance with their stops if the VPS disk is lost; their records are not: each
Demo / live bot's state and execution journal, the risk ledgers (Demo and live), the yes/no per strategy, the watchdog
state and the logs — the measurement history. One .tar.gz a day (about 1 MB), sent silently (no notification sound) to
the watchdog's chat. SQLite files are copied with SQLite's backup API, so a copy taken while a bot writes is consistent.
No keys: the key files live elsewhere and are not read. The paper bots (/opt/raqm-bot) are another OS user's and are
not included. Run daily by raqm-backup.timer as raqmlive; a failure says so in the chat.

  sudo -u raqmlive sh -c 'set -a; . /opt/raqm-live/.env.telegram; set +a; cd /opt/raqm-live && venv/bin/python -E -s scripts/backup.py'
"""
import io, json, os, sqlite3, tarfile, tempfile, urllib.request, uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = {"state": ROOT / "state", "risk-demo": Path("/opt/raqm-risk-demo"), "risk-live": Path("/opt/raqm-risk")}
SKIP = (".tmp", "-journal", "-wal", "-shm")
LIMIT = 45 * 1024 * 1024     # Telegram takes files up to 50 MB from a bot


def build(now, sources=SOURCES):
    """(archive bytes, file count). Every regular file under each source, SQLite through its backup API."""
    buf, n = io.BytesIO(), 0
    with tarfile.open(fileobj=buf, mode="w:gz") as tar, tempfile.TemporaryDirectory() as td:
        for name, root in sources.items():
            if not root.is_dir():
                continue
            for f in sorted(p for p in root.rglob("*") if p.is_file() and not p.name.endswith(SKIP)):
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
    now = datetime.now(timezone.utc); chat = os.getenv("TELEGRAM_CHAT_ID", "")
    if not (os.getenv("TELEGRAM_BOT_TOKEN") and chat):
        raise SystemExit("backup: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set")
    try:
        data, n = build(now)
        if len(data) > LIMIT:
            raise RuntimeError(f"archive {len(data) // 1048576} MB is over Telegram's limit")
        _post("sendDocument", {"chat_id": chat, "disable_notification": "true",
                               "caption": f"💾 نسخة احتياطية يومية — {n} ملف · {len(data) / 1048576:.1f} MB"},
              {"document": (f"raqm-backup-{now:%Y%m%d}.tar.gz", data)})
    except Exception as e:
        _post("sendMessage", {"chat_id": chat, "text": f"🚨 النسخة الاحتياطية اليومية ما اتعملتش: {type(e).__name__}: {e}"})
        raise


if __name__ == "__main__":
    main()
