"""
Auth for the FastAPI backend.

The frontend sends the Supabase access token as `Authorization: Bearer <jwt>`.
We verify it by asking Supabase Auth (`GET /auth/v1/user`), which works for both
legacy HS256 and the newer asymmetric signing keys, and cache the result briefly.

- require_user          -> any signed-in user
- require_admin         -> email listed in ADMIN_EMAILS (comma-separated). Fails closed if unset.
- require_admin_or_cron -> admin, or header `X-Cron-Secret: $CRON_SECRET` (for cron-job.org / GitHub Actions)

Env: SUPABASE_URL, SUPABASE_ANON_KEY (or SUPABASE_SERVICE_KEY), ADMIN_EMAILS, CRON_SECRET
"""
import os, time, hashlib, hmac
import httpx
from fastapi import Header, HTTPException

_CACHE: dict = {}
_CACHE_TTL_S = 60


def _supabase_conf():
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_ANON_KEY", "") or os.getenv("SUPABASE_SERVICE_KEY", "")
    return url, key


def _admin_emails():
    return {e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()}


async def _verify_token(token: str) -> dict:
    h = hashlib.sha256(token.encode()).hexdigest()
    hit = _CACHE.get(h)
    if hit and hit[0] > time.time():
        return hit[1]
    url, key = _supabase_conf()
    if not url or not key:
        raise HTTPException(503, "auth not configured — set SUPABASE_URL and SUPABASE_ANON_KEY on the backend")
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(f"{url}/auth/v1/user", headers={"apikey": key, "Authorization": f"Bearer {token}"})
    except Exception:
        raise HTTPException(503, "auth provider unreachable")
    if r.status_code != 200:
        raise HTTPException(401, "invalid or expired session")
    j = r.json()
    user = {"id": j.get("id"), "email": (j.get("email") or "").lower(),
            # email_confirmed_at only: confirmed_at is also set by a confirmed *phone*, which proves nothing about the email
            "email_confirmed": bool(j.get("email_confirmed_at"))}
    if not user["id"]:
        raise HTTPException(401, "invalid session")
    if len(_CACHE) > 1000:   # drop expired entries first — a flood of junk tokens must not empty everyone's cache
        now = time.time()
        for k in [k for k, (exp, _) in _CACHE.items() if exp < now]: _CACHE.pop(k, None)
        while len(_CACHE) > 1000: _CACHE.pop(next(iter(_CACHE)))
    _CACHE[h] = (time.time() + _CACHE_TTL_S, user)
    return user


def _bearer(authorization: str) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "login required")
    return authorization.split(" ", 1)[1].strip()


async def require_user(authorization: str = Header(default="")) -> dict:
    return await _verify_token(_bearer(authorization))


def is_admin(user: dict) -> bool:
    """Same rules as require_admin, as a yes/no (for showing admin buttons; every admin endpoint still checks)."""
    admins = _admin_emails()
    ids = {x.strip() for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip()}
    return bool(admins and user.get("email") in admins and user.get("email_confirmed") and (not ids or user.get("id") in ids))


async def require_admin(authorization: str = Header(default="")) -> dict:
    user = await _verify_token(_bearer(authorization))
    admins = _admin_emails()
    if not admins:
        raise HTTPException(403, "ADMIN_EMAILS not set on the backend — admin endpoints are disabled")
    if user["email"] not in admins:
        raise HTTPException(403, "admin only")
    # Without this, anyone could sign up with the admin's address (if it isn't registered yet,
    # or "Confirm email" is off in Supabase) and get admin — i.e. control of the LIVE trading keys.
    if not user.get("email_confirmed"):
        raise HTTPException(403, "admin email not confirmed")
    # ADMIN_USER_IDS (Supabase user ids) pins admin to the account itself, not just an email address
    ids = {x.strip() for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip()}
    if ids and user["id"] not in ids:
        raise HTTPException(403, "admin only")
    return user


async def require_admin_or_cron(authorization: str = Header(default=""), x_cron_secret: str = Header(default="")) -> dict:
    secret = os.getenv("CRON_SECRET", "")
    if secret and x_cron_secret and hmac.compare_digest(secret, x_cron_secret):
        return {"id": "cron", "email": "cron"}
    return await require_admin(authorization)
