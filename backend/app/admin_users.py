"""
Admin "Users & Plans & Bots" data layer.

Combines three distinct sources into one read model for the admin
dashboard's Users & Plans tab:
  * Supabase GoTrue Admin API (GET /auth/v1/admin/users) — account identity:
    id, email, created_at, last_sign_in_at, email_confirmed_at, banned_until.
    Requires the service_role key (never exposed to the frontend).
  * Supabase REST `profiles` table (id, tier) — plan/tier per user.
  * Local SQLite `user_settings` (capital, strategy, started_at, updated_at)
    — per-user bot configuration already stored by this backend. Loaded by
    the caller (main.py) and passed in as a plain dict so this module stays
    free of any DB session dependency and is trivial to unit test.

The 7 real paper bots are standalone VPS systemd services unrelated to
individual users (see live_bots_feed.py) and are NEVER conflated with the
per-user settings merged here.

Hard constraints:
  * Never log, return, or expose the Supabase service_role key, a password,
    or any other secret. Only identity/plan/settings fields are surfaced;
    fields such as "encrypted_password" from the raw GoTrue payload are
    dropped, not forwarded.
  * A failure reaching Supabase (network error, bad key, non-200 response)
    must degrade to an explicit "unavailable" state with a short, key-free
    error string — this module never raises and never fabricates user data.
  * set_user_ban() is the only mutation this module performs, and only via
    the documented GoTrue admin endpoint (PUT .../admin/users/{id} with
    ban_duration). No other side effect, no VPS/systemd access.

Testing: pass `transport=httpx.MockTransport(...)` for deterministic,
network-free tests (see backend/tests/test_admin_users_feed.py).
"""
from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_TIMEOUT_SECONDS = 8.0
# GoTrue requires ban_duration as a Go duration string; "none" lifts a ban.
# 100 years is effectively indefinite without relying on a value GoTrue might reject.
INDEFINITE_BAN = "876000h"
LIFT_BAN = "none"


def supabase_conf() -> tuple[str, str]:
    """(url, service_role key) from env — never logged, never returned to a caller."""
    return os.getenv("SUPABASE_URL", "").rstrip("/"), os.getenv("SUPABASE_SERVICE_KEY", "")


async def fetch_gotrue_users(*, page: int = 1, per_page: int = 200,
                              transport: "httpx.AsyncBaseTransport | None" = None,
                              timeout: float | None = None) -> dict:
    """List Supabase auth users via the GoTrue Admin API.

    Returns {"available": True, "error": None, "users": [...]} on success or
    {"available": False, "error": "...", "users": []} on any failure. Never
    raises and never includes the service key in the error string.
    """
    url, key = supabase_conf()
    if not url or not key:
        return {"available": False, "error": "SUPABASE_URL/SUPABASE_SERVICE_KEY not configured", "users": []}
    timeout = DEFAULT_TIMEOUT_SECONDS if timeout is None else timeout
    try:
        async with httpx.AsyncClient(transport=transport, timeout=timeout) as client:
            r = await client.get(f"{url}/auth/v1/admin/users", params={"page": page, "per_page": per_page},
                                  headers={"apikey": key, "Authorization": f"Bearer {key}"})
        if r.status_code != 200:
            return {"available": False, "error": f"gotrue admin users http {r.status_code}", "users": []}
        j = r.json()
        users = j.get("users") if isinstance(j, dict) else j
        if not isinstance(users, list):
            return {"available": False, "error": "unexpected gotrue response shape", "users": []}
        return {"available": True, "error": None, "users": users}
    except Exception as exc:  # noqa: BLE001 - isolate ANY network/parse failure, never raise
        return {"available": False, "error": f"{type(exc).__name__}", "users": []}


async def fetch_profile_tiers(*, transport: "httpx.AsyncBaseTransport | None" = None,
                               timeout: float | None = None) -> dict:
    """id -> tier for every row in the Supabase `profiles` table."""
    url, key = supabase_conf()
    if not url or not key:
        return {"available": False, "error": "SUPABASE_URL/SUPABASE_SERVICE_KEY not configured", "tiers": {}}
    timeout = DEFAULT_TIMEOUT_SECONDS if timeout is None else timeout
    try:
        async with httpx.AsyncClient(transport=transport, timeout=timeout) as client:
            r = await client.get(f"{url}/rest/v1/profiles", params={"select": "id,tier"},
                                  headers={"apikey": key, "Authorization": f"Bearer {key}"})
        if r.status_code != 200:
            return {"available": False, "error": f"profiles http {r.status_code}", "tiers": {}}
        rows = r.json()
        if not isinstance(rows, list):
            return {"available": False, "error": "unexpected profiles response shape", "tiers": {}}
        return {"available": True, "error": None,
                "tiers": {row.get("id"): row.get("tier") for row in rows if isinstance(row, dict) and row.get("id")}}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": f"{type(exc).__name__}", "tiers": {}}


async def set_user_ban(user_id: str, banned: bool, *, transport: "httpx.AsyncBaseTransport | None" = None,
                        timeout: float | None = None) -> dict:
    """Ban (indefinitely) or unban a Supabase auth user via the GoTrue Admin API.

    The only mutation this module performs; never touches any other system.
    """
    url, key = supabase_conf()
    if not url or not key:
        return {"ok": False, "error": "SUPABASE_URL/SUPABASE_SERVICE_KEY not configured"}
    timeout = DEFAULT_TIMEOUT_SECONDS if timeout is None else timeout
    try:
        async with httpx.AsyncClient(transport=transport, timeout=timeout) as client:
            r = await client.put(f"{url}/auth/v1/admin/users/{user_id}",
                                  json={"ban_duration": INDEFINITE_BAN if banned else LIFT_BAN},
                                  headers={"apikey": key, "Authorization": f"Bearer {key}"})
        if r.status_code not in (200, 201):
            return {"ok": False, "error": f"gotrue admin ban http {r.status_code}"}
        return {"ok": True, "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}"}


# Only these identity/plan fields ever leave this module for a user record —
# an allowlist, not a denylist, so a new raw GoTrue field (e.g. a future
# "encrypted_password" sibling) can never leak through by accident.
def _public_user_fields(raw: dict, tier: str, settings: dict) -> dict:
    banned_until = raw.get("banned_until")
    is_banned = bool(banned_until) and banned_until not in (None, "", "none")
    return {
        "id": raw.get("id"),
        "email": raw.get("email"),
        "created_at": raw.get("created_at"),
        "last_sign_in_at": raw.get("last_sign_in_at"),
        "email_confirmed": bool(raw.get("email_confirmed_at")),
        "banned": is_banned,
        "tier": tier,
        "capital": settings.get("capital"),
        "strategy": settings.get("strategy"),
        "bot_started_at": settings.get("started_at"),
        "settings_updated_at": settings.get("updated_at"),
    }


def merge_users(gotrue_result: dict, tiers_result: dict, local_settings: dict[str, dict]) -> dict:
    """Combine the three sources into the admin-facing user list + per-plan counts.

    `local_settings` maps user_id -> {capital, strategy, started_at, updated_at}
    already loaded by the caller from the local SQLite user_settings table.
    If GoTrue is unavailable, returns an empty, explicitly-unavailable result
    — never a fabricated or partial user list.
    """
    users_out = [
        _public_user_fields(u, tiers_result.get("tiers", {}).get(u.get("id")) or "free",
                             local_settings.get(u.get("id")) or {})
        for u in gotrue_result.get("users", [])
    ]
    plan_counts: dict[str, int] = {}
    for u in users_out:
        plan_counts[u["tier"]] = plan_counts.get(u["tier"], 0) + 1
    return {
        "available": gotrue_result.get("available", False),
        "error": gotrue_result.get("error"),
        "tiers_available": tiers_result.get("available", False),
        "tiers_error": tiers_result.get("error"),
        "users": users_out,
        "total": len(users_out),
        "plan_counts": plan_counts,
    }
