"""
Read-only data layer for the 7 REAL standalone VPS paper-trading bots.

These bots run as independent systemd services on the production VPS,
completely separate from this backend's SQL `Trade` table / `bot_loop`
machinery. They each publish a small, public, read-only JSON status file
(no auth, CORS-enabled) via nginx at ``{base}/{file}``. This module fetches
those files, normalizes them into one schema, and classifies freshness.

Hard constraints (see task context — do not relax these):
  * HTTP GET only. Never POST/PUT/DELETE anything to the VPS or an exchange.
  * No systemctl / lifecycle control of the 7 services from here or anywhere
    reachable from this module — that is explicitly out of scope.
  * A failure fetching any one bot's file must never raise out of
    ``fetch_all`` or affect any other bot's result.
  * ``default`` has no running service and no public
    file. They must always report a "no_service" status — never be
    fabricated into a fake "running" state.

Testing: pass ``transport=httpx.MockTransport(...)`` to ``fetch_all`` for
fully deterministic, network-free tests (see backend/tests/test_live_bots_feed.py).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://bot.da3m.io"
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_STALE_SECONDS = 300.0  # 5 minutes with no update => considered stale

# strategy_id -> public status file name, for the 7 REAL systemd bots.
STRATEGY_FILES: dict[str, str] = {
    "trend_daily": "status.json",
    "listing_short": "listing.json",
    "momentum_ls": "momentum.json",
    "ratio_trend": "ratio.json",
    "vol_breakout": "breakout.json",
    "rsi2_pullback": "rsi2.json",
    "trend_breakout": "tbreak.json",
}

# Strategy ids present in admin_control.STRATEGIES that have NO running
# production service and NO public status file.
NO_SERVICE_STRATEGIES: tuple[str, ...] = ("default",)

ALL_STRATEGY_IDS: tuple[str, ...] = tuple(STRATEGY_FILES) + NO_SERVICE_STRATEGIES

LIFECYCLE_CONTROL_NOTE = (
    "Read-only: the admin API has no lifecycle control (start/stop/pause) over "
    "the 7 VPS systemd services. They are managed directly on the VPS via "
    "systemctl and are intentionally out of scope for this feature."
)


def base_url() -> str:
    return os.getenv("LIVE_BOTS_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def timeout_seconds() -> float:
    try:
        return float(os.getenv("LIVE_BOTS_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def stale_seconds() -> float:
    try:
        return float(os.getenv("LIVE_BOTS_STALE_SECONDS", DEFAULT_STALE_SECONDS))
    except ValueError:
        return DEFAULT_STALE_SECONDS


def _parse_updated(value: Any):
    if not isinstance(value, str) or not value:
        return None
    try:
        s = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def no_service_entry(strategy_id: str) -> dict:
    """The explicit, non-fabricated state for default."""
    return {
        "id": strategy_id,
        "status": "no_service",
        "updated": None,
        "age_seconds": None,
        "mode": None,
        "stats": {},
        "positions": [],
        "history": [],
        "extra": {},
        "error": "no live service configured for this strategy",
    }


def normalize_bot_file(strategy_id: str, raw: dict | None, *, now: datetime | None = None,
                        stale_after: float | None = None) -> dict:
    """Normalize one bot's raw JSON (or None on fetch failure) into the
    unified schema. Never fabricates positions/history/stats that weren't
    actually present in the source payload."""
    now = now or datetime.now(timezone.utc)
    stale_after = stale_seconds() if stale_after is None else stale_after

    if not isinstance(raw, dict):
        return {
            "id": strategy_id, "status": "unavailable", "updated": None, "age_seconds": None,
            "mode": None, "stats": {}, "positions": [], "history": [], "extra": {},
            "error": "fetch_failed",
        }

    updated_raw = raw.get("updated")
    dt = _parse_updated(updated_raw)
    age = (now - dt).total_seconds() if dt is not None else None

    if dt is None:
        status = "unavailable"
        error = "missing or unparseable 'updated' timestamp"
    elif age is not None and age > stale_after:
        status = "stale"
        error = None
    else:
        status = "running"
        error = None

    known = {"updated", "mode", "stats", "positions", "history"}
    extra = {k: v for k, v in raw.items() if k not in known}

    return {
        "id": strategy_id,
        "status": status,
        "updated": updated_raw,
        "age_seconds": age,
        "mode": raw.get("mode", "paper"),
        "stats": raw.get("stats") or {},
        "positions": raw.get("positions") or [],
        "history": raw.get("history") or [],
        "extra": extra,
        "error": error,
    }


async def _fetch_one(client: httpx.AsyncClient, strategy_id: str, url: str, timeout: float,
                      now: datetime, stale_after: float) -> dict:
    try:
        resp = await client.get(url, timeout=timeout)
        if resp.status_code != 200:
            entry = normalize_bot_file(strategy_id, None, now=now, stale_after=stale_after)
            entry["error"] = f"http {resp.status_code}"
            return entry
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 - isolate ANY per-file failure
        entry = normalize_bot_file(strategy_id, None, now=now, stale_after=stale_after)
        entry["error"] = f"{type(exc).__name__}: {exc}"
        return entry
    return normalize_bot_file(strategy_id, data, now=now, stale_after=stale_after)


async def fetch_all(strategies: list[str] | tuple[str, ...] | None = None, *,
                     base: str | None = None, timeout: float | None = None,
                     stale_after: float | None = None,
                     transport: "httpx.AsyncBaseTransport | None" = None) -> dict[str, dict]:
    """Fetch & normalize every requested strategy's live status.

    One file's failure (timeout, connection error, non-200, bad JSON) is
    isolated and reported as that strategy's own "unavailable" entry; it
    never raises out of this function and never affects any other entry.
    """
    strategies = list(strategies) if strategies is not None else list(ALL_STRATEGY_IDS)
    base = (base or base_url()).rstrip("/")
    timeout = timeout_seconds() if timeout is None else timeout
    stale_after = stale_seconds() if stale_after is None else stale_after
    now = datetime.now(timezone.utc)

    result: dict[str, dict] = {}
    no_service_ids = [s for s in strategies if s in NO_SERVICE_STRATEGIES or s not in STRATEGY_FILES]
    fetch_ids = [s for s in strategies if s in STRATEGY_FILES]

    for sid in no_service_ids:
        result[sid] = no_service_entry(sid)

    if fetch_ids:
        async with httpx.AsyncClient(transport=transport) as client:
            for sid in fetch_ids:
                url = f"{base}/{STRATEGY_FILES[sid]}"
                result[sid] = await _fetch_one(client, sid, url, timeout, now, stale_after)

    return result


def aggregate_summary(feed_result: dict[str, dict]) -> dict:
    """Aggregate PnL / open positions / status counts across real bots only.
    no_service strategies contribute zero and are counted separately."""
    totals = {"running": 0, "stale": 0, "unavailable": 0, "no_service": 0}
    open_positions = 0
    realized = 0.0
    unrealized = 0.0
    for entry in feed_result.values():
        status = entry.get("status", "unavailable")
        totals[status] = totals.get(status, 0) + 1
        stats = entry.get("stats") or {}
        open_positions += int(stats.get("open", len(entry.get("positions") or [])) or 0)
        realized += float(stats.get("realized") or 0)
        unrealized += float(stats.get("unrealized") or 0)
    return {
        "strategies_total": len(feed_result),
        "running": totals["running"],
        "stale": totals["stale"],
        "unavailable": totals["unavailable"],
        "no_service": totals["no_service"],
        "open_positions": open_positions,
        "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unrealized, 2),
        "total_pnl": round(realized + unrealized, 2),
    }
