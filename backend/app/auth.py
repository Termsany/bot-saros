"""
Auth for the FastAPI backend.

The frontend sends the Supabase access token as `Authorization: Bearer <jwt>`.
We verify it by asking Supabase Auth (`GET /auth/v1/user`), which works for both
legacy HS256 and the newer asymmetric signing keys, and cache the result briefly.

- require_user          -> any signed-in user
- require_admin         -> email listed in ADMIN_EMAILS (comma-separated). Fails closed if unset.
- require_admin_or_cron -> admin, or header `X-Cron-Secret: $CRON_SECRET` (for cron-job.org / GitHub Actions)

2FA (owner, 2026-11-07): once the admin has a verified authenticator (Supabase TOTP), every admin endpoint wants a
session that passed it (the token's `aal` is "aal2"); a password alone is refused. ADMIN_REQUIRE_MFA=1 also refuses an
admin who has none yet, so removing the authenticator can't drop the rule.

Env: SUPABASE_URL, SUPABASE_ANON_KEY (or SUPABASE_SERVICE_KEY), ADMIN_EMAILS, CRON_SECRET, ADMIN_REQUIRE_MFA
"""
import os, time, hashlib, hmac, json, base64
import httpx
from fastapi import Header, HTTPException, Request

_CACHE: dict = {}
_CACHE_TTL_S = 60


def _supabase_conf():
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_ANON_KEY", "") or os.getenv("SUPABASE_SERVICE_KEY", "")
    return url, key


def _admin_emails():
    return {e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()}


def _token_aal(token: str) -> str:
    """The token's assurance level. Read only after Supabase accepted this very token, so its claims are Supabase's."""
    try:
        part = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        return claims.get("aal") if claims.get("aal") in ("aal1", "aal2") else "aal1"
    except Exception:
        return "aal1"


def _mfa_required() -> bool:
    return os.getenv("ADMIN_REQUIRE_MFA", "").strip().lower() in ("1", "true", "yes")


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
            "email_confirmed": bool(j.get("email_confirmed_at")),
            "mfa_enrolled": any(f.get("status") == "verified" for f in (j.get("factors") or []) if isinstance(f, dict)),
            "aal": _token_aal(token)}
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


def _session_id(token: str):
    """Supabase's session id claim (read only after Supabase accepted this very token). It opens nothing on its own."""
    try:
        part = token.split(".")[1]
        sid = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))).get("session_id")
        return sid if isinstance(sid, str) and 0 < len(sid) <= 64 else None
    except Exception:
        return None


def _note_session(user: dict, token: str, request) -> None:
    """Security plan item 10: the first request of each sign-in session goes on the account's activity page
    (account_activity), and an admin's new session also to the owner's Telegram. Never blocks the request."""
    try:
        from app import account_activity, security_alerts
        ip = request.client.host if request is not None and request.client else None
        ua = request.headers.get("user-agent", "") if request is not None else None
        if account_activity.session_seen(user, _session_id(token), ip=ip, ua=ua) and is_admin(user):
            security_alerts.admin_session(user, ip, account_activity.device(ua))
    except Exception as e:
        print(f"session not noted: {type(e).__name__}")


async def require_user(authorization: str = Header(default=""), request: Request = None) -> dict:
    token = _bearer(authorization)
    user = await _verify_token(token)
    _note_session(user, token, request)
    return user


def is_admin(user: dict) -> bool:
    """Same rules as require_admin, as a yes/no (for showing admin buttons; every admin endpoint still checks)."""
    admins = _admin_emails()
    ids = {x.strip() for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip()}
    return bool(admins and user.get("email") in admins and user.get("email_confirmed") and (not ids or user.get("id") in ids))


async def require_admin(authorization: str = Header(default=""), request: Request = None) -> dict:
    token = _bearer(authorization)
    user = await _verify_token(token)
    _note_session(user, token, request)
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
    check_admin_mfa(user)
    return user


def mfa_state(user: dict) -> dict:
    """What the site shows the admin: whether an authenticator is set, and whether this session passed it."""
    return {"enrolled": bool(user.get("mfa_enrolled")), "aal": user.get("aal") or "aal1", "required": _mfa_required()}


def check_real_money_mfa(user: dict) -> None:
    """A user's real-money changes (owner, 2026-11-07): their keys while they trade real money, the consent, turning a
    real-money bot on or changing its numbers. Turning it off never needs the code (someone who lost their phone can
    still stop)."""
    if not user.get("mfa_enrolled"):
        raise HTTPException(403, "mfa_setup_required: real money needs 2FA — set up an authenticator app on this page first")
    if user.get("aal") != "aal2":
        raise HTTPException(403, "mfa_required: enter the code from your authenticator app")


def check_admin_mfa(user: dict) -> None:
    if user.get("mfa_enrolled") and user.get("aal") != "aal2":
        raise HTTPException(403, "mfa_required: enter the code from your authenticator app")
    if _mfa_required() and not user.get("mfa_enrolled"):
        raise HTTPException(403, "mfa_enroll_required: set up an authenticator app for the admin account")


async def require_admin_or_cron(authorization: str = Header(default=""), x_cron_secret: str = Header(default="")) -> dict:
    secret = os.getenv("CRON_SECRET", "")
    if secret and x_cron_secret and hmac.compare_digest(secret, x_cron_secret):
        return {"id": "cron", "email": "cron"}
    return await require_admin(authorization)
