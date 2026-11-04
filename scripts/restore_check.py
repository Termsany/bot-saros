"""Check a daily backup (scripts/backup.py, raqm-backup-YYYYMMDD.tar.gz from Telegram) restores (development-plan 2.2).

Unpacks it into a NEW empty folder — never over the live files — refusing links, absolute paths and "..", then checks
every SQLite file (integrity_check), every JSON file (parses), that the real ledger and the real bot's state are in it,
and — with --compare — that each bot's open positions in the backup are the ones on disk now.

  restore_check.py ARCHIVE OUT_DIR [--compare /opt/raqm-live/state]

Putting a backup back for real is a deliberate step with the bots stopped; the layout is in docs/restore.md.
"""
import json, re, sqlite3, sys, tarfile
from pathlib import Path

REQUIRED = ("risk-live/risk_state.sqlite3", "state/live-momentum_ls.json")


def unpack(archive, out):
    """The archive's files under `out` (which must not exist yet); its top folder (raqm-backup-DATE) is returned."""
    out = Path(out)
    out.mkdir(parents=True)            # FileExistsError: never into an existing folder
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        for m in members:
            p = Path(m.name)
            if not (m.isfile() or m.isdir()) or p.is_absolute() or ".." in p.parts:
                raise ValueError(f"refusing {m.name!r}: not a plain file inside the archive")
        tar.extractall(out, members=members, filter="data")
    tops = [p for p in out.iterdir() if p.is_dir()]
    if len(tops) != 1:
        raise ValueError(f"expected one raqm-backup-* folder, found {[p.name for p in tops]}")
    return tops[0]


def verify(top, compare=None):
    """[(ok, line)]"""
    out = []
    files = sorted(p for p in top.rglob("*") if p.is_file())
    for rel in REQUIRED:
        out.append(((top / rel).is_file(), f"{rel} {'موجود' if (top / rel).is_file() else 'ناقص'}"))
    bad_db, bad_json = [], []
    for f in files:
        if f.suffix in (".sqlite3", ".db"):
            try:
                con = sqlite3.connect(f"file:{f.as_posix()}?mode=ro", uri=True)
                try: ok = con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                finally: con.close()
            except sqlite3.Error:
                ok = False
            if not ok: bad_db.append(f.relative_to(top).as_posix())
        elif f.suffix == ".json":
            try: json.loads(f.read_text(encoding="utf-8"))
            except (ValueError, UnicodeDecodeError): bad_json.append(f.relative_to(top).as_posix())
    n_db = sum(1 for f in files if f.suffix in (".sqlite3", ".db")); n_json = sum(1 for f in files if f.suffix == ".json")
    out.append((not bad_db, f"{n_db} ملف SQLite سليم" if not bad_db else f"SQLite بايظ: {', '.join(bad_db)}"))
    out.append((not bad_json, f"{n_json} ملف JSON سليم" if not bad_json else f"JSON بايظ: {', '.join(bad_json)}"))
    if compare:
        # each bot's own state (live-<strategy>.json / demo-<strategy>.json); the pair bot keeps its open legs in "pairs"
        held = lambda d: set(d.get("positions") or {}) | {f"pair:{k}" for k in (d.get("pairs") or {})}
        for f in sorted(p for p in (top / "state").glob("*.json") if re.fullmatch(r"(live|demo)-[a-z0-9_]+\.json", p.name)):
            now = Path(compare) / f.name
            if not now.is_file(): continue
            try:
                a = held(json.loads(f.read_text(encoding="utf-8")))
                b = held(json.loads(now.read_text(encoding="utf-8")))
            except (ValueError, AttributeError):
                out.append((False, f"{f.name}: مقدرناش نقارن")); continue
            out.append((a == b, f"{f.name}: {len(a)} صفقة في النسخة {'= اللي شغالة دلوقتي' if a == b else f'≠ اللي شغالة دلوقتي ({len(b)})'}"))
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2:
        sys.exit(__doc__)
    compare = argv[argv.index("--compare") + 1] if "--compare" in argv else None
    top = unpack(argv[0], argv[1])
    res = verify(top, compare)
    for ok, line in res: print(f"{'✅' if ok else '❌'} {line}")
    bad = sum(1 for ok, _ in res if not ok)
    print(f"اتفكت في {top}" + ("" if not bad else f" — 🚨 {bad} مشكلة"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
