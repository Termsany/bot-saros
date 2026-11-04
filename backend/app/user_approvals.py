"""The owner's approval of a user for their own Demo bots (development-plan 4.1, phase2-design.md gate 4).

The owner approves from the site: accepting the owner's gift invitation approves that account, and the admin page can
approve or remove anyone. The list is a file in the API's request folder, /opt/raqm-users/desired/approved.list (one
user id a line, oldest first: the order decides who gets a place first). The root provisioner reads it next to its
own /etc/raqm-users/allow.list and still checks every other gate itself: consent, keys, Demo only, the cap.
"""
import os, tempfile
from pathlib import Path

from app import user_bots


def path():
    return user_bots.DESIRED / "approved.list"


def read():
    try:
        lines = path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for l in (x.strip() for x in lines):
        if user_bots.UID_RE.match(l) and l not in out:
            out.append(l)
    return out


def set_approved(uid, on):
    """Add (at the end) or remove a user; returns the new list. Written as a new file renamed over the old one."""
    if not user_bots.UID_RE.match(uid or ""):
        raise ValueError("bad user id")
    now = read()
    new = (now + [uid]) if on and uid not in now else [u for u in now if u != uid] if not on else now
    if new == now:
        return now
    p = path(); p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".approved-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("".join(u + "\n" for u in new)); fh.flush(); os.fsync(fh.fileno())
        os.chmod(tmp, 0o640)
        os.replace(tmp, p)
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise
    return new
