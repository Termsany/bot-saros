"""Users' bots (Phase 2, docs/phase2-design.md): the rules shared by the API, which writes a user's desired state, and
the root provisioner (scripts/provision_users.py), which applies it — so both check the same thing the same way.
Stdlib only: the provisioner imports it from the real-orders code copy.

The API never trades: it writes /opt/raqm-users/desired/<uid>.json (no keys), reads the user's own bots' status
from /opt/raqm-users/ipc/<uid>/<strategy>/ and drops close requests there, like the owner's admin page does.
"""
import json, os, re
from datetime import datetime, timezone
from pathlib import Path

DESIRED = Path(os.getenv("RAQM_USERS_DESIRED", "/opt/raqm-users/desired"))
IPC_ROOT = Path(os.getenv("RAQM_USERS_IPC", "/opt/raqm-users/ipc"))

ENVS_ALLOWED = ("demo",)      # real money for users is refused (P2.2); the provisioner checks it again as root
MAX_USERS, MAX_STRATEGIES = 4, 10
STRATEGIES = ("trend_daily", "vol_breakout", "rsi2_pullback", "trend_breakout", "listing_short", "momentum_ls", "ratio_trend")
STRATEGY_SLOTS = {s: 1 for s in STRATEGIES}
STRATEGY_SLOTS["momentum_ls"] = 10
DEFAULT_RECOMMENDED_STRATEGIES = 3
UID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# the per-user bounds of the existing consent record (user_live_activation.py)
BOUNDS = {"leverage": (1, 5), "risk_per_trade_pct": (0.01, 1.0), "max_aggregate_risk_pct": (0.01, 3.0),
          "capital_usdt": (0.0, 1_000_000.0), "capital_margin_override_usdt": (0.0, 100_000.0)}
STALE_S = 300


def ipc_instance(uid, strategy, root=None):
    return (root or IPC_ROOT) / f"{uid}--{strategy}"


def strategy_policy(strategies, *, available_slots=10):
    """Pure account policy: recommend three single-leg strategies, charge basket slots, fail closed."""
    if (not isinstance(strategies, list) or not all(isinstance(s, str) for s in strategies)
            or len(set(strategies)) != len(strategies) or any(s not in STRATEGIES for s in strategies)):
        return {"accepted": False, "recommended": DEFAULT_RECOMMENDED_STRATEGIES, "slots": 0, "reason": "invalid strategies"}
    slots = sum(STRATEGY_SLOTS[s] for s in strategies)
    if isinstance(available_slots, bool) or not isinstance(available_slots, int) or available_slots < 0 or slots > available_slots:
        return {"accepted": False, "recommended": DEFAULT_RECOMMENDED_STRATEGIES, "slots": slots, "reason": "insufficient strategy slots"}
    return {"accepted": True, "recommended": DEFAULT_RECOMMENDED_STRATEGIES, "slots": slots, "reason": "ok"}


def validate(uid, doc):
    """The desired state, checked as if hostile. ValueError on anything off; the clean copy otherwise."""
    if not isinstance(uid, str) or not UID_RE.match(uid) or not isinstance(doc, dict) or doc.get("user_id") != uid:
        raise ValueError("user id")
    env = doc.get("env")
    if env not in ENVS_ALLOWED:
        raise ValueError(f"environment {env!r} not allowed")
    strategies = doc.get("strategies") or []
    if (not isinstance(strategies, list) or not all(isinstance(s, str) for s in strategies)
            or len(set(strategies)) != len(strategies) or any(s not in STRATEGIES for s in strategies)):
        raise ValueError("strategies")
    if len(strategies) > MAX_STRATEGIES:
        raise ValueError(f"more than {MAX_STRATEGIES} strategies")
    clean = {"env": env, "enabled": doc.get("enabled") is True, "strategies": list(strategies)}
    for k, (lo, hi) in BOUNDS.items():
        v = doc.get(k, 0 if k.startswith("capital") else None)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
            raise ValueError(f"{k} out of bounds")
        clean[k] = float(v)
    clean["leverage"] = int(clean["leverage"])
    if clean["risk_per_trade_pct"] > clean["max_aggregate_risk_pct"]:
        raise ValueError("risk per trade above the aggregate limit")
    if clean["capital_margin_override_usdt"] > clean["capital_usdt"]:
        raise ValueError("margin above the capital")
    available_slots = min(10, int(clean["max_aggregate_risk_pct"] / clean["risk_per_trade_pct"]))
    if not strategy_policy(strategies, available_slots=available_slots)["accepted"]:
        raise ValueError("strategy slots exceed account risk capacity")
    return clean


def write_desired(uid, doc, folder=None):
    """Validated, then written new and renamed in (group-readable: root's provisioner reads it)."""
    folder = folder or DESIRED
    clean = validate(uid, {**doc, "user_id": uid})
    out = {"user_id": uid, **clean, "updated": datetime.now(timezone.utc).isoformat()}
    tmp = folder / f".{uid}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o640)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(out))
    os.replace(tmp, folder / f"{uid}.json")
    return out


def read_desired(uid, folder=None):
    try:
        return json.loads(((folder or DESIRED) / f"{uid}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_json(path, limit=1 << 20):
    """A file a user's bot wrote: a small regular file, not followed through a link (a bot could point its status at
    another user's or the owner's), opened non-blocking (a FIFO in its place must not freeze the API). None otherwise."""
    import stat
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > limit:
            return None
        return json.loads(os.read(fd, limit + 1).decode("utf-8"))
    except (OSError, ValueError):
        return None
    finally:
        os.close(fd)


_json = read_json


def status(uid, ipc=None, now=None):
    """What the user's page shows: the provisioner's answer for them and each of their bots' status."""
    ipc, now = ipc or IPC_ROOT, now or datetime.now(timezone.utc)
    base = ipc / uid
    bots = {}
    for s in STRATEGIES:
        st = _json(ipc_instance(uid, s, ipc) / "live_status.json") or _json(base / s / "live_status.json")
        if not isinstance(st, dict):
            continue
        try:
            st["running"] = (now - datetime.fromisoformat(st["updated"])).total_seconds() < STALE_S
        except (KeyError, TypeError, ValueError):
            st["running"] = False
        bots[s] = st
    return {"provision": _json(base / "provision.json"), "bots": bots}
