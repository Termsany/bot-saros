"""
Plan prices the admin can change, and invitations to a plan by email.

  * Prices: the admin sets each paid plan's monthly price; a plan never set costs its default
    (admin_users.TIER_PRICES_USD, the same numbers as lib/strategies.ts). New Stripe checkouts charge
    the current price (app/api/stripe/checkout); people already subscribed keep what they pay.
  * Invitations, one email address each, three kinds:
      gift  - the plan for N days, no payment. Kept here as a grant on top of the user's paid plan
              (the higher one counts) and simply stops counting when it ends.
      trial - a Stripe subscription with N free days before the first charge.
      paid  - a Stripe checkout link for the plan.
    The link is /invite/<id>; only the account with that email (confirmed) can use it.
  * Email goes through Resend when RESEND_API_KEY and INVITE_FROM_EMAIL are set. Without them the
    invitation is still created and the admin copies the link.

Pure helpers here; the endpoints live in main.py.
"""
from __future__ import annotations

import html
import os
import secrets
from datetime import datetime, timedelta, timezone

import httpx

from app.admin_users import TIER_PRICES_USD

PAID_TIERS = ("starter", "pro", "elite")
TIER_RANK = {"free": 0, "starter": 1, "pro": 2, "elite": 3}
TIER_NAMES = {"free": "Free", "starter": "Starter", "pro": "Pro", "elite": "Elite"}
KINDS = ("gift", "trial", "paid")
MAX_PRICE_USD = 10_000
MAX_DAYS = 365
LINK_DAYS = 14                      # an unused invitation link stops working after this
REMIND_BEFORE_DAYS = 3


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def parse(ts: str | None) -> datetime | None:
    if not ts: return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def new_invite_id() -> str:
    return secrets.token_urlsafe(18)


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def valid_email(email: str) -> bool:
    e = normalize_email(email)
    if len(e) > 254 or e.count("@") != 1: return False
    local, domain = e.split("@")
    return bool(local) and "." in domain and not domain.startswith(".") and not domain.endswith(".") and " " not in e


def mask_email(email: str) -> str:
    """s***@example.com — enough for the invitee to recognise their address, not enough to harvest it."""
    e = normalize_email(email)
    if "@" not in e: return "***"
    local, domain = e.split("@", 1)
    return f"{local[:1]}***@{domain}"


def effective_prices(saved: dict[str, int]) -> dict[str, int]:
    """Every plan's current monthly price: the admin's, else the default. Free is always 0."""
    out = dict(TIER_PRICES_USD)
    for tier, price in saved.items():
        if tier in PAID_TIERS and isinstance(price, int) and 0 <= price <= MAX_PRICE_USD:
            out[tier] = price
    out["free"] = 0
    return out


def validate_prices(patch: dict) -> dict[str, int]:
    """The admin's new prices: paid plans only, whole dollars 1..MAX_PRICE_USD. Raises ValueError otherwise."""
    if not isinstance(patch, dict) or not patch:
        raise ValueError("no prices given")
    out = {}
    for tier, price in patch.items():
        if tier not in PAID_TIERS:
            raise ValueError(f"unknown or unpriced plan: {tier}")
        if isinstance(price, bool) or not isinstance(price, (int, float)) or price != int(price):
            raise ValueError(f"{tier}: price must be whole dollars")
        if not 1 <= int(price) <= MAX_PRICE_USD:
            raise ValueError(f"{tier}: price must be between 1 and {MAX_PRICE_USD}")
        out[tier] = int(price)
    return out


def higher_tier(a: str, b: str) -> str:
    return a if TIER_RANK.get(a, 0) >= TIER_RANK.get(b, 0) else b


def active_grant_tier(grant: dict | None, at: datetime | None = None) -> str | None:
    """The gift's plan while it lasts, else None."""
    if not grant: return None
    end = parse(grant.get("expires_at"))
    if not end or end <= (at or now()) or grant.get("tier") not in PAID_TIERS: return None
    return grant["tier"]


def invite_state(inv: dict, at: datetime | None = None) -> str:
    """pending | accepted | revoked | expired (an unused link past its date)."""
    status = inv.get("status") or "pending"
    if status != "pending": return status
    end = parse(inv.get("link_expires_at"))
    return "expired" if end and end <= (at or now()) else "pending"


def invite_link(invite_id: str) -> str:
    base = (os.getenv("SITE_URL") or "https://bot-saros.vercel.app").rstrip("/")
    return f"{base}/invite/{invite_id}"


def offer_text(tier: str, kind: str, days: int | None, price: int | None) -> str:
    name = TIER_NAMES.get(tier, tier)
    if kind == "gift": return f"باقة {name} هدية لمدة {days} يوم"
    if kind == "trial": return f"باقة {name} مجانًا {days} يوم، وبعدها ${price} في الشهر"
    return f"اشتراك باقة {name} بـ ${price} في الشهر"


def invite_email(tier: str, kind: str, days: int | None, price: int | None, link: str) -> tuple[str, str]:
    """(subject, html) for the invitation email. RTL, inline styles only (email clients drop <style>)."""
    offer = html.escape(offer_text(tier, kind, days, price))
    cta = {"gift": "فعّل الباقة", "trial": "ابدأ التجربة", "paid": "اشترك دلوقتي"}[kind]
    subject = f"دعوة لـ رقم: {offer_text(tier, kind, days, price)}"
    body = f"""<!doctype html><html dir="rtl" lang="ar"><body style="margin:0;background:#07080D;padding:32px 12px;font-family:Tahoma,Arial,sans-serif">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr><td align="center">
<table role="presentation" width="100%" style="max-width:520px;background:#0F1118;border:1px solid #232838;border-radius:16px" cellspacing="0" cellpadding="0">
<tr><td style="padding:28px 28px 8px;text-align:right;color:#F5B841;font-weight:bold;letter-spacing:2px;font-size:14px">RAQM · رقم</td></tr>
<tr><td style="padding:8px 28px;text-align:right;color:#F2F3F7;font-size:22px;font-weight:bold">اتدعيت لمنصة رقم</td></tr>
<tr><td style="padding:4px 28px 20px;text-align:right;color:#8B91A7;font-size:15px;line-height:1.8">{offer}.<br>بوتات تداول مختبرة على Binance، وكل صفقة بتوصلك على تليجرام.</td></tr>
<tr><td style="padding:0 28px 24px;text-align:right"><a href="{html.escape(link)}" style="display:inline-block;background:#F5B841;color:#07080D;text-decoration:none;font-weight:bold;font-size:15px;padding:12px 28px;border-radius:12px">{cta}</a></td></tr>
<tr><td style="padding:0 28px 28px;text-align:right;color:#5D6378;font-size:12px;line-height:1.7">الرابط شغال {LINK_DAYS} يوم، ولازم تدخل بنفس الإيميل ده. لو ماكنتش مستني الدعوة دي، تجاهلها.</td></tr>
</table></td></tr></table></body></html>"""
    return subject, body


def reminder_email(tier: str, days_left: int, link: str) -> tuple[str, str]:
    name = TIER_NAMES.get(tier, tier)
    subject = f"هدية باقة {name} بتخلص بعد {days_left} يوم"
    body = f"""<!doctype html><html dir="rtl" lang="ar"><body style="margin:0;background:#07080D;padding:32px 12px;font-family:Tahoma,Arial,sans-serif">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr><td align="center">
<table role="presentation" width="100%" style="max-width:520px;background:#0F1118;border:1px solid #232838;border-radius:16px" cellspacing="0" cellpadding="0">
<tr><td style="padding:28px 28px 8px;text-align:right;color:#F5B841;font-weight:bold;letter-spacing:2px;font-size:14px">RAQM · رقم</td></tr>
<tr><td style="padding:8px 28px;text-align:right;color:#F2F3F7;font-size:20px;font-weight:bold">{html.escape(subject)}</td></tr>
<tr><td style="padding:4px 28px 20px;text-align:right;color:#8B91A7;font-size:15px;line-height:1.8">بعدها حسابك هيرجع للباقة المجانية. عشان تكمّل بنفس البوتات اشترك في الباقة.</td></tr>
<tr><td style="padding:0 28px 28px;text-align:right"><a href="{html.escape(link)}" style="display:inline-block;background:#F5B841;color:#07080D;text-decoration:none;font-weight:bold;font-size:15px;padding:12px 28px;border-radius:12px">اشترك</a></td></tr>
</table></td></tr></table></body></html>"""
    return subject, body


def email_configured() -> bool:
    return bool(os.getenv("RESEND_API_KEY") and os.getenv("INVITE_FROM_EMAIL"))


async def send_email(to: str, subject: str, body_html: str, *, transport: "httpx.AsyncBaseTransport | None" = None) -> dict:
    """Send through Resend. {"ok": bool, "error": str|None}; never raises, never returns the key."""
    key, sender = os.getenv("RESEND_API_KEY", ""), os.getenv("INVITE_FROM_EMAIL", "")
    if not key or not sender:
        return {"ok": False, "error": "email not configured (RESEND_API_KEY / INVITE_FROM_EMAIL)"}
    try:
        async with httpx.AsyncClient(transport=transport, timeout=10) as client:
            r = await client.post("https://api.resend.com/emails", headers={"Authorization": f"Bearer {key}"},
                                  json={"from": sender, "to": [to], "subject": subject, "html": body_html})
        if r.status_code not in (200, 201, 202):
            # Resend says why ("The da3m.io domain is not verified", "API key is invalid", ...): keep it for the admin.
            # Its error body never echoes the key.
            try: why = str((r.json() or {}).get("message") or "")[:200]
            except Exception: why = ""
            return {"ok": False, "error": f"resend http {r.status_code}" + (f": {why}" if why else "")}
        return {"ok": True, "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": type(exc).__name__}


def grant_end(existing: dict | None, tier: str, days: int, at: datetime | None = None) -> tuple[str, datetime]:
    """Tier and end date after a gift: a second gift adds its days after an active one, and keeps the higher plan."""
    start = at or now()
    cur_end = parse(existing.get("expires_at")) if existing else None
    if existing and active_grant_tier(existing, start) and cur_end:
        return higher_tier(existing["tier"], tier), cur_end + timedelta(days=days)
    return tier, start + timedelta(days=days)
