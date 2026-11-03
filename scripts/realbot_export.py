"""The public page of the real-money bots, realbot.da3m.io (owner's choice, 2026-11-03: public like bot.da3m.io).

Every 20 seconds (raqm-realbot-export.timer) it reads each strategy's live_status.json from /opt/raqm-ipc and writes
one filtered live.json into the page's folder. Only the bots running on real money (env "live"; the same folder holds
the Demo bot's status) and only what the page shows: positions (symbol, side, entry, price, quantity, stop, PnL) and
closed trades — never who closed one, the review notes, the block reasons or anything else the dashboard has.

nginx never reads /opt/raqm-ipc: that folder also takes the close requests. This runs as raqmlive (who writes those
statuses) in a sandbox that can write the page's folder only; a status file is read only as a regular file, not
through a link, at most 1 MB.

  sudo -u raqmlive /opt/raqm-live/venv/bin/python -E -s /opt/raqm-live/scripts/realbot_export.py
"""
import json, os, stat, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path

IPC = Path(os.getenv("RAQM_IPC_ROOT", "/opt/raqm-ipc"))
OUT = Path(os.getenv("REALBOT_OUT", "/var/www/realbot.da3m.io/live.json"))
STRATEGIES = ("trend_daily", "vol_breakout", "rsi2_pullback", "trend_breakout", "listing_short", "momentum_ls", "ratio_trend")
MAX_BYTES = 1_000_000
STALE_S = 300            # the bots write their status every cycle (1–2 minutes)
POSITION_FIELDS = ("symbol", "side", "entry", "price", "qty", "contract_size", "sl", "pnl", "pnl_estimated", "loss_at_sl", "opened")
TRADE_FIELDS = ("symbol", "side", "entry", "exit", "qty", "pnl", "pnl_pct", "reason", "time", "opened")
HISTORY = 100


def read_status(path):
    """The JSON of a regular file at `path`, not through a link; None when missing, a link, too big or not JSON."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_BYTES:
            return None
        with os.fdopen(fd, "rb") as f:
            fd = None
            doc = json.loads(f.read(MAX_BYTES + 1).decode("utf-8"))
        return doc if isinstance(doc, dict) else None
    except (OSError, ValueError):
        return None
    finally:
        if fd is not None: os.close(fd)


def _pick(row, fields):
    return {k: row[k] for k in fields if isinstance(row, dict) and k in row and isinstance(row[k], (str, int, float, bool, type(None)))}


def public_bot(strategy, st, now):
    """The page's view of one live bot; None for a Demo bot or anything that isn't a status."""
    if not isinstance(st, dict) or st.get("env") != "live":
        return None
    try:
        age = (now - datetime.fromisoformat(st["updated"])).total_seconds()
    except (KeyError, TypeError, ValueError):
        age = None
    positions = [_pick(p, POSITION_FIELDS) for p in (st.get("positions") or []) if isinstance(p, dict)]
    history = [_pick(h, TRADE_FIELDS) for h in (st.get("history") or []) if isinstance(h, dict)][-HISTORY:]
    return {"strategy": strategy, "updated": st.get("updated"), "running": age is not None and 0 <= age < STALE_S,
            "leverage": st.get("leverage") if isinstance(st.get("leverage"), (int, float)) else None,
            "positions": positions, "history": history}


def build(ipc=IPC, now=None):
    now = now or datetime.now(timezone.utc)
    bots = [b for b in (public_bot(s, read_status(ipc / s / "live_status.json"), now) for s in STRATEGIES) if b]
    return {"updated": now.isoformat(), "bots": bots}


def write(doc, out=OUT):
    """New file in the same folder, then rename over live.json: the page never reads half a file."""
    fd, tmp = tempfile.mkstemp(dir=str(out.parent), prefix=".live-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
        os.chmod(tmp, 0o644); os.replace(tmp, out)
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise


def main():
    doc = build()
    write(doc)
    print(f"{len(doc['bots'])} live bot(s), {sum(len(b['positions']) for b in doc['bots'])} open position(s) -> {OUT}")


if __name__ == "__main__":
    sys.exit(main())
