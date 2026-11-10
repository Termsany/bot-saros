"""Plan prices and invitations: the pricing page's prices, the admin's invitations (gift / trial / paid),
accepting one, the gift reminder. Rules in app/plans_invites.py.

Moved out of app/main.py (development-plan 3.2); the paths and behaviour are unchanged. Names the tests replace on
app.main are read as M.<name> at call time, and so is the plan cache (a test reloads app.main, which makes a new one).
"""
from fastapi import APIRouter

from app import main as M
from app.main import (  # noqa: F401
    AdminModel,
    Depends,
    Field,
    HTTPException,
    Invitation,
    Optional,
    PlanGrant,
    PlanPrice,
    Request,
    _admin_actor,
    _grants,
    _saved_prices,
    admin_control,
    admin_users,
    asyncio,
    desc,
    os,
    pi,
    rate_limit,
    re,
    require_admin,
    require_user,
    select,
    user_approvals,
)

router = APIRouter()

# ── Plan prices and invitations (app/plans_invites.py has the rules)
@router.get("/api/plans")
async def plans_public():
    """Every plan's current monthly price (USD) — the pricing page and the Stripe checkout read this."""
    return {"currency": "usd", "prices": pi.effective_prices(await _saved_prices())}

@router.get("/api/admin/plans")
async def admin_plans(user: dict = Depends(require_admin)):
    async with M.async_session() as sess:
        rows = (await sess.execute(select(PlanPrice))).scalars().all()
    saved = {r.tier: r.price_usd for r in rows}
    return {"prices": pi.effective_prices(saved), "defaults": dict(admin_users.TIER_PRICES_USD),
            "changed": {r.tier: {"price_usd": r.price_usd, "updated_at": r.updated_at, "updated_by": r.updated_by} for r in rows}}

class PlanPricesReq(AdminModel):
    prices: dict
    confirm: bool = False

@router.post("/api/admin/plans")
async def admin_plans_set(req: PlanPricesReq, user: dict = Depends(require_admin)):
    """Change paid plans' monthly prices. New checkouts charge them; existing Stripe subscribers keep their price."""
    rate_limit(user["id"], "admin_mutation", 30, 60)
    if not req.confirm: raise HTTPException(400, "confirmation required")
    try: patch = pi.validate_prices(req.prices)
    except ValueError as e: raise HTTPException(400, str(e))
    actor, at = await _admin_actor(user), pi.iso(pi.now())
    async with M.async_session() as sess:
        for tier, price in patch.items():
            row = await sess.get(PlanPrice, tier)
            if row is None: sess.add(PlanPrice(tier=tier, price_usd=price, updated_at=at, updated_by=actor))
            else: row.price_usd, row.updated_at, row.updated_by = price, at, actor
        await sess.commit()
    admin_control.audit(M.BOT_DIR, actor, "plan_prices", "ok", patch)
    return {"ok": True, "prices": pi.effective_prices(await _saved_prices())}

def _invite_out(inv: Invitation, prices: dict, paid_tier_by_email: dict | None = None) -> dict:
    d = {c: getattr(inv, c) for c in ("id", "email", "tier", "kind", "days", "status", "note", "created_at", "created_by",
                                     "link_expires_at", "emailed_at", "email_error", "opened_checkout_at", "accepted_at")}
    d["state"] = pi.invite_state(d)
    if inv.kind in ("trial", "paid") and d["state"] == "pending" and paid_tier_by_email is not None:
        if pi.TIER_RANK.get(paid_tier_by_email.get(inv.email, "free"), 0) >= pi.TIER_RANK.get(inv.tier, 0):
            d["state"] = "subscribed"
    d["link"] = pi.invite_link(inv.id)
    d["offer"] = pi.offer_text(inv.tier, inv.kind, inv.days, prices.get(inv.tier))
    return d

@router.get("/api/admin/invites")
async def admin_invites(user: dict = Depends(require_admin)):
    rate_limit(user["id"], "admin_users", 20, 60)
    prices = pi.effective_prices(await _saved_prices())
    gotrue = await admin_users.fetch_gotrue_users()
    tiers = await admin_users.fetch_profile_tiers()
    by_email = {pi.normalize_email(u.get("email")): tiers.get("tiers", {}).get(u.get("id")) or "free"
                for u in gotrue.get("users", []) if u.get("email")}
    async with M.async_session() as sess:
        rows = (await sess.execute(select(Invitation).order_by(desc(Invitation.created_at)).limit(200))).scalars().all()
    grants = await _grants()
    at = pi.now()
    return {"email_configured": pi.email_configured(),
            "invites": [_invite_out(r, prices, by_email if gotrue.get("available") else None) for r in rows],
            "grants": [{"user_id": uid, **g, "active": bool(pi.active_grant_tier(g, at))} for uid, g in grants.items()]}

class InviteReq(AdminModel):
    email: str = Field(max_length=254)
    tier: str
    kind: str
    days: Optional[int] = Field(None, ge=1, le=pi.MAX_DAYS)
    note: Optional[str] = Field(None, max_length=200)
    send_email: bool = True
    confirm: bool = False

async def _email_invite(inv: Invitation, prices: dict) -> dict:
    subject, body = pi.invite_email(inv.tier, inv.kind, inv.days, prices.get(inv.tier), pi.invite_link(inv.id))
    return await pi.send_email(inv.email, subject, body)

@router.post("/api/admin/invites")
async def admin_invite_create(req: InviteReq, user: dict = Depends(require_admin)):
    rate_limit(user["id"], "admin_mutation", 30, 60)
    if not req.confirm: raise HTTPException(400, "confirmation required")
    email = pi.normalize_email(req.email)
    if not pi.valid_email(email): raise HTTPException(400, "invalid email")
    if req.tier not in pi.PAID_TIERS: raise HTTPException(400, f"tier must be one of {pi.PAID_TIERS}")
    if req.kind not in pi.KINDS: raise HTTPException(400, f"kind must be one of {pi.KINDS}")
    if req.kind in ("gift", "trial") and not req.days: raise HTTPException(400, "days required for a gift or a trial")
    at = pi.now()
    async with M.async_session() as sess:
        open_ = (await sess.execute(select(Invitation).where(Invitation.email == email, Invitation.status == "pending"))).scalars().all()
        if any(pi.invite_state({"status": r.status, "link_expires_at": r.link_expires_at}, at) == "pending" for r in open_):
            raise HTTPException(409, "there is already a pending invitation for this email — revoke or resend it")
        inv = Invitation(id=pi.new_invite_id(), email=email, tier=req.tier, kind=req.kind,
                         days=req.days if req.kind != "paid" else None, status="pending", note=(req.note or "").strip() or None,
                         created_at=pi.iso(at), created_by=await _admin_actor(user),
                         link_expires_at=pi.iso(at + pi.timedelta(days=pi.LINK_DAYS)))
        sess.add(inv)
        await sess.commit()
    prices = pi.effective_prices(await _saved_prices())
    sent = {"ok": False, "error": None}
    if req.send_email:
        sent = await _email_invite(inv, prices)
        async with M.async_session() as sess:
            row = await sess.get(Invitation, inv.id)
            if sent["ok"]: row.emailed_at = pi.iso(pi.now())
            row.email_error = sent["error"]
            await sess.commit()
            inv = row
    admin_control.audit(M.BOT_DIR, inv.created_by, "invite_create", "ok",
                         {"invite": inv.id[:6], "email": email, "tier": req.tier, "kind": req.kind, "days": inv.days, "emailed": sent["ok"]})
    return {"ok": True, "invite": _invite_out(inv, prices), "emailed": sent["ok"], "email_error": sent["error"]}

class InviteActionReq(AdminModel):
    confirm: bool = False

@router.post("/api/admin/invites/{invite_id}/revoke")
async def admin_invite_revoke(invite_id: str, req: InviteActionReq, user: dict = Depends(require_admin)):
    rate_limit(user["id"], "admin_mutation", 30, 60)
    if not req.confirm: raise HTTPException(400, "confirmation required")
    async with M.async_session() as sess:
        inv = await sess.get(Invitation, invite_id)
        if inv is None: raise HTTPException(404, "invitation not found")
        if inv.status != "pending": raise HTTPException(409, f"invitation is {inv.status}")
        inv.status = "revoked"
        await sess.commit()
    admin_control.audit(M.BOT_DIR, await _admin_actor(user), "invite_revoke", "ok", {"invite": invite_id[:6], "email": inv.email})
    return {"ok": True}

@router.post("/api/admin/invites/{invite_id}/resend")
async def admin_invite_resend(invite_id: str, req: InviteActionReq, user: dict = Depends(require_admin)):
    """Email the invitation again; the link gets a fresh LINK_DAYS."""
    rate_limit(user["id"], "admin_mutation", 30, 60)
    if not req.confirm: raise HTTPException(400, "confirmation required")
    async with M.async_session() as sess:
        inv = await sess.get(Invitation, invite_id)
        if inv is None: raise HTTPException(404, "invitation not found")
        if inv.status != "pending": raise HTTPException(409, f"invitation is {inv.status}")
        inv.link_expires_at = pi.iso(pi.now() + pi.timedelta(days=pi.LINK_DAYS))
        await sess.commit()
    prices = pi.effective_prices(await _saved_prices())
    sent = await _email_invite(inv, prices)
    async with M.async_session() as sess:
        row = await sess.get(Invitation, invite_id)
        if sent["ok"]: row.emailed_at = pi.iso(pi.now())
        row.email_error = sent["error"]
        await sess.commit()
    admin_control.audit(M.BOT_DIR, await _admin_actor(user), "invite_resend", "ok" if sent["ok"] else "failed", {"invite": invite_id[:6], "email": inv.email})
    return {"ok": True, "emailed": sent["ok"], "email_error": sent["error"]}

@router.post("/api/admin/grants/{target_user_id}/end")
async def admin_grant_end(target_user_id: str, req: InviteActionReq, user: dict = Depends(require_admin)):
    """End a gift now: the user is back on their paid plan (or free)."""
    rate_limit(user["id"], "admin_mutation", 30, 60)
    if not req.confirm: raise HTTPException(400, "confirmation required")
    async with M.async_session() as sess:
        g = await sess.get(PlanGrant, target_user_id)
        if g is None: raise HTTPException(404, "no gift for this user")
        g.expires_at = pi.iso(pi.now())
        await sess.commit()
    M._tier_cache.pop(target_user_id, None)
    admin_control.audit(M.BOT_DIR, await _admin_actor(user), "gift_end", "ok", {"target_user_id": target_user_id})
    return {"ok": True}

async def _load_invite(invite_id: str) -> Invitation:
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", invite_id or ""): raise HTTPException(404, "invitation not found")
    async with M.async_session() as sess:
        inv = await sess.get(Invitation, invite_id)
    if inv is None: raise HTTPException(404, "invitation not found")
    return inv

@router.get("/api/invites/{invite_id}")
async def invite_public(invite_id: str, request: Request):
    """What the invitation offers, for its page. The email is masked: the link alone doesn't reveal the address."""
    rate_limit(request.client.host if request.client else "?", "invite_view", 30, 60)
    inv = await _load_invite(invite_id)
    prices = pi.effective_prices(await _saved_prices())
    return {"state": pi.invite_state({"status": inv.status, "link_expires_at": inv.link_expires_at}), "tier": inv.tier,
            "kind": inv.kind, "days": inv.days, "price_usd": prices.get(inv.tier), "email_hint": pi.mask_email(inv.email),
            "offer": pi.offer_text(inv.tier, inv.kind, inv.days, prices.get(inv.tier))}

def _check_invitee(inv: Invitation, user: dict):
    if pi.invite_state({"status": inv.status, "link_expires_at": inv.link_expires_at}) != "pending":
        raise HTTPException(409, "invitation is no longer valid")
    if not user.get("email_confirmed"): raise HTTPException(403, "confirm your email first")
    if pi.normalize_email(user.get("email")) != inv.email: raise HTTPException(403, "this invitation is for another email")

@router.post("/api/invites/{invite_id}/accept")
async def invite_accept(invite_id: str, user: dict = Depends(require_user)):
    """Take a gift invitation: the plan for its days, on top of the paid plan (the higher one counts)."""
    rate_limit(user["id"], "invite_accept", 10, 60)
    inv = await _load_invite(invite_id)
    _check_invitee(inv, user)
    if inv.kind != "gift": raise HTTPException(400, "this invitation is taken through checkout")
    at = pi.now()
    async with M.async_session() as sess:
        row = await sess.get(Invitation, invite_id)
        if row.status != "pending": raise HTTPException(409, "invitation is no longer valid")
        g = await sess.get(PlanGrant, user["id"])
        tier, end = pi.grant_end({"tier": g.tier, "expires_at": g.expires_at} if g else None, inv.tier, inv.days or 0, at)
        if g is None:
            sess.add(PlanGrant(user_id=user["id"], email=inv.email, tier=tier, expires_at=pi.iso(end), invite_id=inv.id, granted_at=pi.iso(at)))
        else:
            g.tier, g.expires_at, g.invite_id, g.granted_at, g.reminded_at, g.email = tier, pi.iso(end), inv.id, pi.iso(at), None, inv.email
        row.status, row.accepted_at, row.accepted_user_id = "accepted", pi.iso(at), user["id"]
        await sess.commit()
    M._tier_cache.pop(user["id"], None)
    admin_control.audit(M.BOT_DIR, inv.email, "invite_accept", "ok", {"invite": inv.id[:6], "tier": tier, "until": pi.iso(end)})
    # the owner's invitation is the owner's approval for the account's own Demo bots (plan 4.1): the provisioner still
    # checks consent, keys, Demo only and the cap itself. A failure here leaves the plan granted and is shown in the admin.
    try:
        user_approvals.set_approved(user["id"], True)
        admin_control.audit(M.BOT_DIR, inv.email, "demo_bots_approve", "ok", {"user": user["id"][:8], "by": "invite " + inv.id[:6]})
    except Exception as e:
        admin_control.audit(M.BOT_DIR, inv.email, "demo_bots_approve", "failed", {"user": user["id"][:8], "error": type(e).__name__})
    return {"ok": True, "kind": "gift", "tier": tier, "expires_at": pi.iso(end)}

@router.post("/api/invites/{invite_id}/checkout")
async def invite_checkout_terms(invite_id: str, user: dict = Depends(require_user)):
    """For the Stripe checkout route: the plan, price and free days of a trial/paid invitation, for its invitee only."""
    rate_limit(user["id"], "invite_accept", 10, 60)
    inv = await _load_invite(invite_id)
    _check_invitee(inv, user)
    if inv.kind not in ("trial", "paid"): raise HTTPException(400, "a gift needs no checkout")
    if pi.TIER_RANK.get(await M._paid_tier(user), 0) >= pi.TIER_RANK.get(inv.tier, 0):
        async with M.async_session() as sess:
            row = await sess.get(Invitation, invite_id)
            row.status, row.accepted_at, row.accepted_user_id = "accepted", pi.iso(pi.now()), user["id"]
            await sess.commit()
        raise HTTPException(409, "you already have this plan or a higher one")
    async with M.async_session() as sess:
        row = await sess.get(Invitation, invite_id)
        row.opened_checkout_at = pi.iso(pi.now())
        await sess.commit()
    prices = pi.effective_prices(await _saved_prices())
    return {"tier": inv.tier, "kind": inv.kind, "trial_days": inv.days if inv.kind == "trial" else None, "price_usd": prices.get(inv.tier)}

async def _gift_reminder_loop():
    """Hourly: email gifts ending within REMIND_BEFORE_DAYS once (only when email is configured)."""
    while True:
        try:
            if pi.email_configured():
                at = pi.now()
                async with M.async_session() as sess:
                    rows = (await sess.execute(select(PlanGrant).where(PlanGrant.reminded_at.is_(None)))).scalars().all()
                    for g in rows:
                        end = pi.parse(g.expires_at)
                        if not g.email or not end or not (at < end <= at + pi.timedelta(days=pi.REMIND_BEFORE_DAYS)): continue
                        subject, body = pi.reminder_email(g.tier, max(1, (end - at).days or 1),
                                                          (os.getenv("SITE_URL") or "https://bot-saros.vercel.app").rstrip("/") + "/#pricing")
                        if (await pi.send_email(g.email, subject, body))["ok"]: g.reminded_at = pi.iso(at)
                    await sess.commit()
        except Exception as e:
            print(f"gift reminder: {type(e).__name__}")
        await asyncio.sleep(3600)
