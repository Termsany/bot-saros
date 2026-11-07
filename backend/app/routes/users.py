"""A user's own account: their Demo keys, their consent, their own bots (Phase 2), and the admin's view and
approval of users' bots. Every user endpoint is scoped by the session's user id, never one from the request.

Moved out of app/main.py (development-plan 3.2); the paths and behaviour are unchanged. Names the tests replace on
app.main are read as M.<name> at call time.
"""
from fastapi import APIRouter

from app import main as M
from app.auth import check_real_money_mfa
from app import security_alerts
from app.main import (  # noqa: F401
    AdminModel,
    Depends,
    Field,
    HTTPException,
    LIVE_SYMBOL_RE,
    List,
    Optional,
    Request,
    _BM2,
    _admin_actor,
    _drop_request,
    _time,
    admin_control,
    live_trading_allowed,
    rate_limit,
    re,
    require_admin,
    require_user,
    user_approvals,
    uuid,
)

router = APIRouter()

# ── Per-user Keys Vault + Live Enable — any registered user, own account only.
# Separate from the admin-only /api/admin/* paths. Every endpoint here is scoped by the authenticated user's own id
# (Depends(require_user)) — never by an id supplied in the request body — so a user
# can only ever read/write their own key and their own live-enable record.

class UserSaveKeyReq(_BM2):
    # bounded: every save re-encrypts the whole shared vault on the API's single worker
    exchange: str = Field(max_length=20)
    apiKey: str = Field(max_length=256)
    secret: str = Field(max_length=256)
    passphrase: str = Field(default="", max_length=128)

def _require_confirmed(user: dict):
    if not user.get("email_confirmed"):
        raise HTTPException(403, "confirm your email first")

class UserLiveEnableReq(_BM2):
    exchange: str
    confirm: str
    leverage: Optional[int] = None
    risk_per_trade_pct: Optional[float] = None
    max_aggregate_risk_pct: Optional[float] = None
    environment: str = "demo"      # "demo": Binance Demo (play money); "live" (real money) only when asked for explicitly
    capital_usdt: Optional[float] = None    # real money: the capital and margin whose risk the user saw and accepts
    margin_usdt: Optional[float] = None

class UserBotsReq(_BM2):
    """A user's desired bots (Phase 2): checked again by app/user_bots.validate here and by the root provisioner."""
    env: str = "demo"
    enabled: bool
    strategies: List[str] = Field(max_length=7)
    leverage: int
    risk_per_trade_pct: float
    max_aggregate_risk_pct: float
    capital_usdt: float = 0
    capital_margin_override_usdt: float = 0
    capital_reserve_pct: Optional[float] = None   # real money: the share kept out of trades (user_bots.LIVE_RESERVE_BOUNDS)

class UserBotCloseReq(_BM2):
    strategy: str = Field(pattern=r"^[a-z0-9_]{1,30}$")
    symbol: str

@router.get("/api/user/keys/status")
async def user_keys_status(user: dict = Depends(require_user)):
    from app.user_keys_vault import user_key_status
    return user_key_status(user["id"])

def _trades_real_money(uid: str) -> bool:
    """A real-money consent that is on, or a real-money bot asked for."""
    from app.user_live_activation import get_user_live_record
    rec = get_user_live_record(M.USER_LIVE_ACTIVATION_PATH, user_id=uid) or {}
    d = user_bots.read_desired(uid) or {}
    return bool(rec.get("enabled") and (rec.get("environment") or "live") == "live") or bool(d.get("enabled") and d.get("env") == "live")


@router.post("/api/user/keys/save")
async def user_keys_save(req: UserSaveKeyReq, user: dict = Depends(require_user)):
    _require_confirmed(user)
    rate_limit(user["id"], "user_keys", 10, 60)
    real = _trades_real_money(user["id"])
    if real:                                    # replacing the key of a real-money bot needs the code
        check_real_money_mfa(user)
    from app.user_keys_vault import save_user_keys
    try:
        save_user_keys(user["id"], req.exchange.lower().strip(), req.apiKey.strip(), req.secret.strip(), req.passphrase.strip())
        if real:
            security_alerts.user_real_money(user, "غيّر مفتاح حساب بفلوس حقيقية", {"exchange": req.exchange.lower().strip()})
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))

@router.post("/api/user/keys/delete")
async def user_keys_delete(body: dict, user: dict = Depends(require_user)):
    rate_limit(user["id"], "user_keys", 10, 60)
    from app.user_keys_vault import delete_user_keys
    ex = str((body or {}).get("exchange", "")).lower().strip()
    if not ex:
        raise HTTPException(400, "exchange required")
    ok = delete_user_keys(user["id"], ex)
    return {"ok": bool(ok)}

@router.get("/api/user/live/status")
async def user_live_status(user: dict = Depends(require_user)):
    from app.user_live_activation import get_user_live_record
    rec = get_user_live_record(M.USER_LIVE_ACTIVATION_PATH, user_id=user["id"])
    if not rec:
        return {"enabled": False}
    return {"enabled": bool(rec["enabled"]), "exchange": rec["exchange"], "leverage": rec["leverage"],
            "risk_per_trade_pct": rec["risk_per_trade_pct"], "max_aggregate_risk_pct": rec["max_aggregate_risk_pct"],
            "consented_at": rec["consented_at"], "environment": rec.get("environment") or "live",
            "capital_usdt": rec.get("capital_usdt"), "margin_usdt": rec.get("margin_usdt")}

@router.post("/api/user/live/enable")
async def user_live_enable(req: UserLiveEnableReq, request: Request, user: dict = Depends(require_user)):
    _require_confirmed(user)
    if req.environment not in ("demo", "live"):
        raise HTTPException(400, "environment must be demo or live")
    rate_limit(user["id"], "user_live", 10, 60)
    if req.environment == "live":
        check_real_money_mfa(user)
    # real money obeys the server's switch like everything else; a Demo consent trades play money only
    if req.environment == "live" and not live_trading_allowed():
        raise HTTPException(403, "live trading is off on this server")
    from app.user_keys_vault import has_live_configured_keys
    from app.user_live_activation import enable_user_live
    ex = req.exchange.lower().strip()
    if not has_live_configured_keys(user["id"], ex):
        raise HTTPException(400, f"save your {ex} API key first — live cannot be enabled without your own keys")
    try:
        enable_user_live(M.USER_LIVE_ACTIVATION_PATH, user_id=user["id"], exchange=ex, confirm=req.confirm,
                          actor=str(user.get("email") or user["id"]), ip=(request.client.host if request.client else None),
                          leverage=req.leverage, risk_per_trade_pct=req.risk_per_trade_pct,
                          max_aggregate_risk_pct=req.max_aggregate_risk_pct, environment=req.environment,
                          capital_usdt=req.capital_usdt, margin_usdt=req.margin_usdt)
    except (PermissionError, ValueError) as e:
        raise HTTPException(400, str(e))
    if req.environment == "live":          # a Demo consent leaves the keys marked as they were
        from app.user_keys_vault import set_user_paper
        set_user_paper(user["id"], ex, False)  # the per-user vault entry itself switches to LIVE too
        security_alerts.user_real_money(user, "وافق على فلوس حقيقية", {"capital": req.capital_usdt, "margin": req.margin_usdt})
    return {"ok": True}

@router.post("/api/user/live/disable")
async def user_live_disable(user: dict = Depends(require_user)):
    rate_limit(user["id"], "user_live", 10, 60)
    from app.user_live_activation import disable_user_live
    disable_user_live(M.USER_LIVE_ACTIVATION_PATH, user_id=user["id"], reason="user disabled")
    return {"ok": True}

# ── A user's own bots (Phase 2, docs/phase2-design.md): the API writes what the user asks for and reads their bots'
# status; the root provisioner decides and runs them (the owner's approval, consent, keys, cap — Demo only). The user
# id is always the session's: a user reaches only their own desired state and their own bots' folders.
from app import user_bots

@router.get("/api/user/bots")
async def user_bots_get(user: dict = Depends(require_user)):
    return {"desired": user_bots.read_desired(user["id"]), **user_bots.status(user["id"]),
            "rules": {"envs": list(user_bots.ENVS_ALLOWED), "max_strategies": user_bots.MAX_STRATEGIES,
                      "strategies": list(user_bots.STRATEGIES), "bounds": user_bots.BOUNDS,
                      # real money (docs/users-real-money-plan.md): the page shows live_risk() for the numbers typed
                      "live": {"strategies": list(user_bots.LIVE_STRATEGIES), "leverage": user_bots.LIVE_LEVERAGE,
                               "stop": user_bots.LIVE_STOP, "min_margin": user_bots.LIVE_MIN_MARGIN,
                               "legs": user_bots.STRATEGY_SLOTS["momentum_ls"],
                               "reserve": {"default": user_bots.LIVE_RESERVE_DEFAULT, "min": user_bots.LIVE_RESERVE_BOUNDS[0],
                                           "max": user_bots.LIVE_RESERVE_BOUNDS[1]},
                               "equity_floor": user_bots.LIVE_EQUITY_FLOOR}}}

@router.get("/api/user/bots/risk")
async def user_bots_risk(capital: float, margin: float, reserve: float = user_bots.LIVE_RESERVE_DEFAULT,
                         user: dict = Depends(require_user)):
    """The risk of a real-money plan before the user accepts it — the same numbers the server will hold them to, and
    whether the whole basket fits the capital after the reserve."""
    r = user_bots.live_risk(capital, margin, reserve=reserve)
    if r is None:
        raise HTTPException(400, "capital and margin must be positive numbers")
    try:
        user_bots._validate_live("live", True, list(user_bots.LIVE_STRATEGIES),
                                 {"capital_usdt": capital, "capital_margin_override_usdt": margin, "capital_reserve_pct": reserve})
        r["ok"], r["why"] = True, None
    except ValueError as e:
        r["ok"], r["why"] = False, str(e)
    return r

@router.post("/api/user/bots")
async def user_bots_set(req: UserBotsReq, user: dict = Depends(require_user)):
    _require_confirmed(user)
    rate_limit(user["id"], "user_bots", 10, 60)
    if req.env == "live" and req.enabled:      # turning a real-money bot on or changing its numbers; off never asks
        check_real_money_mfa(user)
    try:
        desired = user_bots.write_desired(user["id"], req.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))
    if req.env == "live":
        security_alerts.user_real_money(user, "شغّل/غيّر بوت فلوس حقيقية" if req.enabled else "وقّف بوت فلوس حقيقية",
                                        {"capital": desired.get("capital_usdt"), "margin": desired.get("capital_margin_override_usdt"),
                                         "reserve": desired.get("capital_reserve_pct")} if req.enabled else None)
    return {"ok": True, "desired": desired}

@router.post("/api/user/bots/close")
async def user_bots_close(req: UserBotCloseReq, user: dict = Depends(require_user)):
    """Close one of the user's own positions: a request in that bot's folder, run within a minute (only closes)."""
    rate_limit(user["id"], "user_bots_close", 10, 60)
    if req.strategy not in user_bots.STRATEGIES:
        raise HTTPException(400, "unknown strategy")
    sym = req.symbol.strip().upper()
    if not LIVE_SYMBOL_RE.match(sym):
        raise HTTPException(400, "bad symbol")
    st = user_bots.status(user["id"])["bots"].get(req.strategy) or {}
    if not st.get("running"):
        raise HTTPException(409, "this bot isn't running — close it in Binance")
    if sym.split(":")[0] not in {p.get("symbol") for p in st.get("positions") or []}:
        raise HTTPException(404, "no open position on that coin")
    rid = uuid.uuid4().hex
    base = user_bots.close_ipc(user["id"], req.strategy)
    _drop_request(base / "commands", base, rid,
                  {"id": rid, "symbol": sym, "at_epoch": _time.time(), "by": user.get("email")}, mode=0o644)
    return {"ok": True, "id": rid}

@router.get("/api/user/bots/close/{strategy}/{rid}")
async def user_bots_close_result(strategy: str, rid: str, user: dict = Depends(require_user)):
    if strategy not in user_bots.STRATEGIES or not re.fullmatch(r"[0-9a-f]{32}", rid):
        raise HTTPException(400, "bad request")
    d = user_bots.close_ipc(user["id"], strategy)
    res = user_bots.read_json(d / "results" / f"{rid}.json")      # the user's bot wrote it: no link followed
    if res is None:
        return {"done": False, "pending": (d / "commands" / f"close-{rid}.json").exists()}
    return {"done": True, **(res if isinstance(res, dict) else {})}

@router.get("/api/admin/user-bots")
async def admin_user_bots(user: dict = Depends(require_admin)):
    """Every user who asked for bots or is approved: what they asked, whether the owner approved them, the
    provisioner's answer, their bots' positions and problems."""
    approved = user_approvals.read()
    out = []
    try:
        files = sorted(user_bots.DESIRED.glob("*.json"))
    except OSError:
        files = []
    for f in files:
        uid = f.stem
        if not user_bots.UID_RE.match(uid):
            continue
        st = user_bots.status(uid)
        bots = {s: {"running": b.get("running"), "positions": len(b.get("positions") or []),
                    "entry_block": b.get("entry_block") or "", "review": bool(b.get("review")),
                    "unprotected": any(p.get("unprotected") or p.get("sl_unverified") for p in b.get("positions") or [])}
                for s, b in st["bots"].items()}
        out.append({"user_id": uid, "desired": user_bots.read_desired(uid), "provision": st["provision"], "bots": bots,
                    "approved": uid in approved})
    seen = {u["user_id"] for u in out}
    out += [{"user_id": uid, "desired": None, "provision": None, "bots": {}, "approved": True} for uid in approved if uid not in seen]
    # the account's email, so the owner knows who it is (owner, 2026-11-07); Supabase unreachable: no email, no error
    from app import admin_users
    accounts = await admin_users.fetch_gotrue_users()
    email = {a.get("id"): a.get("email") for a in accounts.get("users") or [] if isinstance(a, dict)}
    for u in out:
        u["email"] = email.get(u["user_id"])
    return {"users": out, "max_users": user_bots.MAX_USERS, "approved": len(approved)}

class UserApproveReq(AdminModel):
    on: bool

@router.post("/api/admin/user-bots/{uid}/approve")
async def admin_user_bots_approve(uid: str, req: UserApproveReq, user: dict = Depends(require_admin)):
    """The owner approves (or removes) an account for its own Demo bots. Removing stops new entries at the next
    provisioner run; open trades still exit on their own rules and stops."""
    if not user_bots.UID_RE.match(uid): raise HTTPException(400, "bad user id")
    try:
        now = user_approvals.set_approved(uid, req.on)
    except OSError as e:
        raise HTTPException(503, f"approval list can't be written: {type(e).__name__}")
    admin_control.audit(M.BOT_DIR, await _admin_actor(user), "demo_bots_approve" if req.on else "demo_bots_remove", "ok", {"user": uid[:8]})
    return {"ok": True, "approved": uid in now}

class UsersLiveReq(AdminModel):
    on: bool
    confirm: bool = False

@router.get("/api/admin/users-live")
async def admin_users_live(user: dict = Depends(require_admin)):
    """The owner's switch for real money for invited users (the provisioner also needs root's main lock)."""
    return user_bots.read_site_live()

@router.post("/api/admin/users-live")
async def admin_users_live_set(req: UsersLiveReq, user: dict = Depends(require_admin)):
    """On: invited users whose keys pass the server's checks and who agreed to their numbers can start real money.
    Off: no real-money user bot starts, and the running ones stop opening new baskets at the next provisioner run
    (their open trades still exit on their own rules and stops)."""
    rate_limit(user["id"], "admin_mutation", 30, 60)
    if not req.confirm:
        raise HTTPException(400, "confirmation required")
    actor = await _admin_actor(user)
    try:
        doc = user_bots.write_site_live(req.on, actor)
    except OSError as e:
        raise HTTPException(503, f"the switch can't be written: {type(e).__name__}")
    admin_control.audit(M.BOT_DIR, actor, "users_live_on" if req.on else "users_live_off", "ok", {})
    return {"ok": True, **doc}
