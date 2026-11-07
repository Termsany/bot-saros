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

# Real money for invited users (owner, 2026-11-05 — docs/users-real-money-plan.md): momentum_ls only, each user's own
# capital and margin, the risk level computed here and accepted by the user. The provisioner starts nothing real
# unless root's switch /etc/raqm-users/live.enabled exists and the user's key passes the preflight's checks.
ENVS_ALLOWED = ("demo", "live")
LIVE_STRATEGIES = ("momentum_ls",)
LIVE_LEVERAGE, LIVE_STOP = 2, 0.40          # the strategy's, not the user's (risk_manager.PLAN_LEVERAGE / PLAN_STOP_LOSS)
LIVE_MIN_MARGIN = 2.5                       # Binance's smallest order is $5: at x2 a margin below $2.5 buys nothing
# the share of the capital kept out of trades (risk_manager.capital_plan): the user's choice within these bounds; the
# whole basket must fit what's left (owner, 2026-11-07: $300, $24 margin needs a 20% reserve)
LIVE_RESERVE_DEFAULT, LIVE_RESERVE_BOUNDS = 40.0, (10.0, 60.0)
# the gate measures a trade's risk against the account's balance (at most the capital), not the capital typed: the
# limits allow the same dollars per stop down to this share of the capital. Below it, no new basket opens until the
# owner of the account looks (a loss, fees and funding make the balance a little under the capital at once)
LIVE_EQUITY_FLOOR = 0.8
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


def close_ipc(uid, strategy, root=None):
    """Resolve the user's close IPC folder, supporting instance and legacy layouts consistently."""
    root = root or IPC_ROOT
    candidates = (ipc_instance(uid, strategy, root), root / uid / strategy)
    for folder in candidates:
        if (folder / "commands").is_dir():
            return folder
    for folder in candidates:
        if (folder / "results").is_dir():
            return folder
    return candidates[0]


def strategy_policy(strategies, *, available_slots=10):
    """Pure account policy: recommend three single-leg strategies, charge basket slots, fail closed."""
    if (not isinstance(strategies, list) or not all(isinstance(s, str) for s in strategies)
            or len(set(strategies)) != len(strategies) or any(s not in STRATEGIES for s in strategies)):
        return {"accepted": False, "recommended": DEFAULT_RECOMMENDED_STRATEGIES, "slots": 0, "reason": "invalid strategies"}
    slots = sum(STRATEGY_SLOTS[s] for s in strategies)
    if isinstance(available_slots, bool) or not isinstance(available_slots, int) or available_slots < 0 or slots > available_slots:
        return {"accepted": False, "recommended": DEFAULT_RECOMMENDED_STRATEGIES, "slots": slots, "reason": "insufficient strategy slots"}
    return {"accepted": True, "recommended": DEFAULT_RECOMMENDED_STRATEGIES, "slots": slots, "reason": "ok"}


def _num(v):
    return None if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")) else float(v)


def live_risk(capital, margin, strategies=LIVE_STRATEGIES, reserve=LIVE_RESERVE_DEFAULT):
    """What a real-money plan costs at its stops, for the user to see and accept: one stop, every leg at its stop at
    once (the worst week), as $ and % of the capital, and the level on the admin page's scale. Also whether the whole
    basket fits the capital after the reserve (max_open, as risk_manager.capital_plan counts it) and the largest margin
    that fits. None if not a plan."""
    capital, margin, reserve = _num(capital), _num(margin), _num(reserve)
    if not capital or capital <= 0 or not margin or margin <= 0 or reserve is None:
        return None
    import math
    legs = sum(STRATEGY_SLOTS.get(s, 1) for s in strategies) or 1
    one = margin * LIVE_LEVERAGE * LIVE_STOP
    per = one / capital * 100
    level = "low" if per < 1 else "medium" if per < 2 else "high" if per < 5 else "very_high"
    usable = capital * (1 - reserve / 100)
    max_open = int(math.floor(usable / margin + 1e-9)) if usable > 0 else 0
    return {"one_stop_usdt": round(one, 2), "per_trade_pct": round(per, 2), "legs": legs,
            "worst_usdt": round(one * legs, 2), "aggregate_pct": round(per * legs, 2), "level": level,
            "reserve_pct": reserve, "max_open": max_open, "fits": max_open >= legs,
            "max_margin": math.floor(usable / legs * 100) / 100 if usable > 0 else 0.0}


def _ceil2(x):
    import math
    return math.ceil(x * 100 - 1e-9) / 100


def _validate_live(env, enabled, strategies, doc, fit=True):
    """A real-money desired state: momentum only, the user's capital, margin and reserve; the limits are computed here
    from them (never taken from the request), so the gate allows exactly the dollars the user accepted per stop and
    for the whole basket, down to LIVE_EQUITY_FLOOR of the capital. `fit`: the whole basket must fit the capital after
    the reserve (a consent alone doesn't choose the reserve, so it is checked without it)."""
    if any(s not in LIVE_STRATEGIES for s in strategies):
        raise ValueError("real money: momentum_ls only")
    capital, margin = _num(doc.get("capital_usdt")), _num(doc.get("capital_margin_override_usdt"))
    if capital is None or not 0 < capital <= BOUNDS["capital_usdt"][1]:
        raise ValueError("capital_usdt out of bounds")
    if margin is None or not LIVE_MIN_MARGIN <= margin <= capital:
        raise ValueError("capital_margin_override_usdt out of bounds")
    raw = doc.get("capital_reserve_pct")
    reserve = LIVE_RESERVE_DEFAULT if raw is None else _num(raw)
    if reserve is None or not LIVE_RESERVE_BOUNDS[0] <= reserve <= LIVE_RESERVE_BOUNDS[1]:
        raise ValueError(f"capital_reserve_pct out of bounds ({LIVE_RESERVE_BOUNDS[0]:g}–{LIVE_RESERVE_BOUNDS[1]:g}%)")
    r = live_risk(capital, margin, strategies or LIVE_STRATEGIES, reserve)
    if r["aggregate_pct"] > 100:
        raise ValueError("every stop at once would lose more than the capital: lower the margin")
    if fit and not r["fits"]:
        raise ValueError(f"the basket of {r['legs']} doesn't fit: with a {reserve:g}% reserve the margin can be at most "
                         f"${r['max_margin']:g} (or lower the reserve)")
    return {"env": env, "enabled": enabled, "strategies": list(strategies), "leverage": LIVE_LEVERAGE,
            "risk_per_trade_pct": _ceil2(r["per_trade_pct"] / LIVE_EQUITY_FLOOR),
            "max_aggregate_risk_pct": _ceil2(r["aggregate_pct"] / LIVE_EQUITY_FLOOR),
            "capital_usdt": capital, "capital_margin_override_usdt": margin, "capital_reserve_pct": reserve, "level": r["level"]}


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
    if env == "live":
        return _validate_live(env, doc.get("enabled") is True, strategies, doc)
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


# The owner's day-to-day switch for real money for users, from the admin page (owner, 2026-11-07: no server command).
# Real money needs both this and root's /etc/raqm-users/live.enabled (the main lock, out of the site's reach): the
# provisioner reads both every minute. No file = off. Not a .json: read_desired and the admin list read *.json as users.
SITE_LIVE_SWITCH = "live.switch"


def read_site_live(folder=None):
    """{"on": bool, "by", "at"}: off unless the file says on is exactly true."""
    doc = read_json((folder or DESIRED) / SITE_LIVE_SWITCH, 4096)
    if not isinstance(doc, dict):
        return {"on": False, "by": None, "at": None}
    return {"on": doc.get("on") is True, "by": doc.get("by") if isinstance(doc.get("by"), str) else None,
            "at": doc.get("at") if isinstance(doc.get("at"), str) else None}


def write_site_live(on, by, folder=None):
    """Written new and renamed in, group-readable (root's provisioner reads it)."""
    folder = folder or DESIRED
    doc = {"on": on is True, "by": str(by)[:200], "at": datetime.now(timezone.utc).isoformat()}
    tmp = folder / ".live.switch.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o640)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(doc))
    os.replace(tmp, folder / SITE_LIVE_SWITCH)
    return doc


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
