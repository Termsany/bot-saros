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
    user = {"id": j.get("id"), "email": (j.get("email") or "").lower()}
    if not user["id"]:
        raise HTTPException(401, "invalid session")
    if len(_CACHE) > 1000:
        _CACHE.clear()
    _CACHE[h] = (time.time() + _CACHE_TTL_S, user)
    return user


def _bearer(authorization: str) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "login required")
    return authorization.split(" ", 1)[1].strip()


async def require_user(authorization: str = Header(default="")) -> dict:
    return await _verify_token(_bearer(authorization))


async def require_admin(authorization: str = Header(default="")) -> dict:
    user = await _verify_token(_bearer(authorization))
    admins = _admin_emails()
    if not admins:
        raise HTTPException(403, "ADMIN_EMAILS not set on the backend — admin endpoints are disabled")
    if user["email"] not in admins:
        raise HTTPException(403, "admin only")
    return user


async def require_admin_or_cron(authorization: str = Header(default=""), x_cron_secret: str = Header(default="")) -> dict:
    secret = os.getenv("CRON_SECRET", "")
    if secret and x_cron_secret and hmac.compare_digest(secret, x_cron_secret):
        return {"id": "cron", "email": "cron"}
    return await require_admin(authorization)
