"""The paper side: a user's own paper portfolio and its closes, the admin's closes in the paper bots, the user's
profile and plan.

Moved out of app/main.py (development-plan 3.2); the paths and behaviour are unchanged. Names the tests replace on
app.main, and state that lives there, are read as M.<name> at call time.
"""
from fastapi import APIRouter

from app import main as M
from app.auth import mfa_state
from app.main import (  # noqa: F401
    BaseModel,
    Depends,
    Field,
    HTTPException,
    PAPER_BOTS,
    UserClose,
    UserSetting,
    _drop_request,
    _gift_of,
    _time,
    datetime,
    is_admin,
    json,
    rate_limit,
    re,
    require_admin,
    require_user,
    strategy_catalog,
    timezone,
    uuid,
)

router = APIRouter()

STRATEGY_FILE = {s: strategy_catalog.LIVE_FILE[s] for s in strategy_catalog.PLANNED}
COIN_RE = re.compile(r"^[A-Z0-9]{1,20}/USDT(:USDT)?$")
PAIR_RE = re.compile(r"^[A-Z0-9]{1,20}/USDT:USDT\|[A-Z0-9]{1,20}/USDT:USDT$")

def _bot_json(name: str) -> dict:
    try: return json.loads((M.BOT_PUBLIC_DIR / f"{name}.json").read_text(encoding="utf-8"))
    except Exception: raise HTTPException(503, "bot data unavailable")

def _label(name: str, p: dict) -> str:
    """The trade's label as the site shows it: the coin, or 'LONG / SHORT' for a ratio pair."""
    if name == "ratio": return f"{p['long']['symbol'].split('/')[0]} / {p['short']['symbol'].split('/')[0]}"
    return p["symbol"].split("/")[0]

@router.get("/api/user/me")
async def user_me(user: dict = Depends(require_user)):
    admin = is_admin(user)
    return {"admin": admin, **({"mfa": mfa_state(user)} if admin else {})}

class PortfolioCloseReq(BaseModel):
    label: str = Field(max_length=60)
    opened: str = Field(max_length=40)

@router.post("/api/user/portfolio/close")
async def portfolio_close(req: PortfolioCloseReq, user: dict = Depends(require_user)):
    """Close one trade in the caller's own paper portfolio at the bot's current price. Server-side: the trade must be
    open in the bot the user follows and opened after their start — the price comes from the bot, never from the user."""
    rate_limit(user["id"], "portfolio_close", 30, 60)
    async with M.async_session() as sess:
        setting = await sess.get(UserSetting, user["id"])
        if not setting or setting.strategy not in STRATEGY_FILE:
            raise HTTPException(400, "no personal portfolio")
        name = STRATEGY_FILE[setting.strategy]; data = _bot_json(name)
        rows = data.get("pairs") if name == "ratio" else data.get("positions")
        p = next((x for x in rows or [] if _label(name, x) == req.label and x.get("opened") == req.opened), None)
        if not p: raise HTTPException(404, "this trade isn't open")
        if datetime.fromisoformat(p["opened"]) < datetime.fromisoformat(setting.started_at):
            raise HTTPException(400, "this trade opened before your portfolio started")
        key = f"{req.label}@{req.opened}"
        if await sess.get(UserClose, (user["id"], key)): raise HTTPException(409, "already closed")
        c = UserClose(user_id=user["id"], trade_key=key, bot_pnl=float(p.get("pnl") or 0),
                      exit_price=None if name == "ratio" else float(p.get("price") or 0), closed_at=datetime.now(timezone.utc).isoformat())
        sess.add(c); await sess.commit()
        return {"ok": True, "key": key, "bot_pnl": c.bot_pnl, "exit_price": c.exit_price, "closed_at": c.closed_at}

class PaperCloseReq(BaseModel):
    bot: str
    symbol: str = Field(max_length=60)

@router.post("/api/paper/close")
async def paper_close(req: PaperCloseReq, user: dict = Depends(require_admin)):
    """Admin: close one position of a paper bot. The bot runs the request within a cycle (one minute) and only closes."""
    rate_limit(user["id"], "paper_close", 20, 60)
    if req.bot not in PAPER_BOTS: raise HTTPException(400, "unknown bot")
    if not (PAIR_RE if req.bot == "ratio" else COIN_RE).match(req.symbol): raise HTTPException(400, "bad symbol")
    data = _bot_json(req.bot)
    if req.bot == "ratio": found = any(p.get("pair") == req.symbol for p in data.get("pairs") or [])
    else: found = any(p.get("symbol", "").split(":")[0] == req.symbol.split(":")[0] for p in data.get("positions") or [])
    if not found: raise HTTPException(404, "no open position on that coin")
    rid = uuid.uuid4().hex
    _drop_request(M.PAPER_IPC / req.bot / "commands", M.PAPER_IPC, rid, {"id": rid, "symbol": req.symbol, "at_epoch": _time.time(), "by": user.get("email")})
    return {"ok": True, "id": rid}

@router.get("/api/paper/close/{bot}/{rid}")
async def paper_close_result(bot: str, rid: str, user: dict = Depends(require_admin)):
    if bot not in PAPER_BOTS or not re.fullmatch(r"[0-9a-f]{32}", rid): raise HTTPException(400, "bad request")
    f = M.PAPER_IPC / bot / "results" / f"{rid}.json"
    if not f.exists(): return {"done": False, "pending": (M.PAPER_IPC / bot / "commands" / f"close-{rid}.json").exists()}
    return {"done": True, **json.loads(f.read_text(encoding="utf-8"))}


@router.get("/api/user/tier")
async def user_tier(user: dict = Depends(require_user)):
    """The caller's plan (paid or gift, the higher) — server-side verification; gift = an active gift's plan and end."""
    gift = None
    try: gift = None if is_admin(user) else await _gift_of(user["id"])
    except Exception: pass
    return {"tier": await M.get_tier(user), "gift": gift}
