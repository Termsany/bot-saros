
import os, json, asyncio
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import List, Optional
import sys, re, uuid

# Add parent to path for bot strategies
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import init_db, async_session, Trade, BacktestRun, UserSetting, UserClose, PlanPrice, Invitation, PlanGrant
from app.auth import require_user, require_admin, require_admin_or_cron, is_admin
from app import live_activation
from sqlalchemy import select, desc
import ccxt, pandas as pd, numpy as np
from datetime import datetime, timezone
from . import admin_control
from app import risk_manager
from app import live_bots_feed
from app import admin_users
from app import plans_invites as pi

try:
    from dotenv import load_dotenv; load_dotenv()
except: pass

BOT_DIR = Path(__file__).parent.parent.parent
LIVE_ACTIVATION_PATH = risk_manager.ledger_dir(BOT_DIR) / "live_activation.sqlite3"   # shared with the live bot (RAQM_RISK_DIR)

def _supabase_key_kind(key: str) -> str:
    """'service', 'public' or 'unknown' — from the key's own format, without calling Supabase."""
    if key.startswith("sb_secret_"): return "service"
    if key.startswith("sb_publishable_"): return "public"
    try:  # legacy keys are JWTs with a "role" claim
        import base64
        payload = key.split(".")[1]
        role = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))).get("role")
        return {"service_role": "service", "anon": "public"}.get(role, "unknown")
    except Exception:
        return "unknown"

async def check_supabase_service_key():
    """Log once at startup whether SUPABASE_SERVICE_KEY can read plans. Never logs the key."""
    url, key = os.getenv("SUPABASE_URL", "").rstrip("/"), os.getenv("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        print("SUPABASE_SERVICE_KEY check: MISSING (SUPABASE_URL or SUPABASE_SERVICE_KEY not set) — plan lookups fall back to free")
        return
    kind = _supabase_key_kind(key)
    if kind == "public":
        print("SUPABASE_SERVICE_KEY check: WRONG KEY — this is the public anon/publishable key, use the service_role/secret key")
        return
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{url}/rest/v1/profiles", params={"select": "id", "limit": "1"},
                                 headers={"apikey": key, "Authorization": f"Bearer {key}"})
        print(f"SUPABASE_SERVICE_KEY check: {'OK' if r.status_code == 200 else f'INVALID (HTTP {r.status_code})'}"
              + (" (key type unrecognized)" if kind == "unknown" and r.status_code == 200 else ""))
    except Exception as e:
        print(f"SUPABASE_SERVICE_KEY check: could not reach Supabase ({type(e).__name__})")

async def _resume_bot_after_restart():
    """A restart (deploy, crash, reboot) used to drop the trading loop silently, leaving open positions without the
    bot's exits / breakeven / reconciliation. If it was running, start it again and say so on Telegram."""
    global bot_task
    try:
        cfg_path = BOT_DIR / "api_bot_config.json"
        if not cfg_path.exists(): return
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        if not cfg.get("running"): return
        from app.telegram_bot import send_telegram
        if not cfg.get("paper", True):
            # real orders run only as the daily trend's own service; an old config must not bring this loop back live
            await send_telegram("⚠️ API restarted: an old dashboard config asked for real orders — not resumed (real orders run only as the trend service).")
            return
        global _bot_task_id
        _bot_task_id = uuid.uuid4().hex
        bot_task = asyncio.create_task(bot_loop(cfg, task_id=_bot_task_id))
        await send_telegram(f"♻️ API restarted — bot loop resumed ({'paper' if cfg.get('paper', True) else 'LIVE'})")
    except Exception as e:
        print(f"bot resume failed: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    print("DB ready")
    asyncio.create_task(check_supabase_service_key())  # don't delay startup on a slow Supabase
    asyncio.create_task(_resume_bot_after_restart())
    asyncio.create_task(_gift_reminder_loop())
    yield

# API docs list every endpoint — off in production unless ENABLE_API_DOCS=true
_docs = os.getenv("ENABLE_API_DOCS", "").lower() == "true"
app = FastAPI(title="Raqm API", version="2.0.0", lifespan=lifespan,
              docs_url="/docs" if _docs else None, redoc_url=None, openapi_url="/openapi.json" if _docs else None)

ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "https://bot-saros.vercel.app,http://localhost:3000").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])

def llm_lab_allowed() -> bool:
    """Running LLM-written code is opt-in (ENABLE_LLM_LAB=true) and never on a server that can trade real money:
    the sandbox is an AST blocklist + child process as the same OS user, which can read .env and vault.json.
    RAQM_RISK_DIR set means this API shares the real-money bot's risk ledger and activation record (and its IPC):
    that bot keeps trading on its own flag even if this API's ALLOW_LIVE_TRADING is switched off."""
    return (os.getenv("ENABLE_LLM_LAB", "").strip().lower() == "true" and not live_trading_allowed()
            and not os.getenv("RAQM_RISK_DIR", "").strip())

def _require_llm_lab():
    if not llm_lab_allowed():
        raise HTTPException(403, "LLM lab is off on this server (ENABLE_LLM_LAB, never together with ALLOW_LIVE_TRADING)")

def live_trading_allowed() -> bool:
    """Global kill switch: real orders only if ALLOW_LIVE_TRADING=true on the server."""
    return os.getenv("ALLOW_LIVE_TRADING", "").strip().lower() == "true"

TIMEFRAMES = {"1m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"}
SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,15}/[A-Z]{3,5}$")
_backtest_slots = asyncio.Semaphore(int(os.getenv("MAX_CONCURRENT_BACKTESTS", "2")))
_backtest_slots_llm = asyncio.Semaphore(int(os.getenv("MAX_CONCURRENT_LLM", "1")))
_evolve_lock = asyncio.Lock()  # P1-05: only one optimizer/evolve at a time

# Per-user rate limit for expensive endpoints (signup is open, Render free has 0.1 CPU)
import time as _time
from collections import defaultdict, deque
_rate_hits: dict = defaultdict(deque)
def rate_limit(user_id: str, key: str, max_calls: int, per_s: int):
    q = _rate_hits[(key, user_id)]
    now = _time.monotonic()
    while q and now - q[0] > per_s: q.popleft()
    if len(q) >= max_calls:
        raise HTTPException(429, f"too many requests — wait {int(per_s - (now - q[0])) + 1}s")
    q.append(now)

# Plan limits — enforced here, not only in the UI (a plan unlocks the first N of this list).
# Keep in sync with lib/strategies.ts STRATEGIES order and TIERS counts: the four paper bots on the VPS.
STRATEGY_ORDER = ["trend_daily", "momentum_ls", "listing_short", "ratio_trend"]
TIER_STRATEGY_COUNT = {"free": 1, "starter": 2, "pro": 3, "elite": 4}
SOLO_STRATEGIES = ("trend_daily", "momentum_ls", "listing_short", "ratio_trend")  # own entries/exits
PER_COIN = ("trend_daily",)  # the others trade a whole portfolio of coins — no single-coin backtest
# Max backtest range in days (end date inclusive). None = unlimited. Keep in sync with lib/strategies.ts BACKTEST_DAYS.
TIER_BACKTEST_DAYS = {"free": 7, "starter": 30, "pro": 90, "elite": None}
TF_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240, "1d": 1440}

def backtest_span_days(req) -> float:
    """Days of history a backtest request covers, counted the way backtest.py fetches it."""
    from datetime import date
    if req.to_date and not req.from_date:
        raise HTTPException(422, "from date is required when to date is given")
    if req.from_date:
        start = date.fromisoformat(req.from_date)
        end = date.fromisoformat(req.to_date) if req.to_date else datetime.now(timezone.utc).date()
        if end < start: raise HTTPException(422, "to date is before from date")
        return (end - start).days + 1  # backtest.py includes the whole end day
    # no start date: backtest.py fetches the last `limit` candles
    return req.limit * TF_MINUTES[req.timeframe] / 1440
_tier_cache: dict = {}

async def _paid_tier(user: dict) -> str:
    """The plan in Supabase profiles (Stripe writes it). Raises on a failed lookup (callers decide what that means)."""
    url, key = os.getenv("SUPABASE_URL", "").rstrip("/"), os.getenv("SUPABASE_SERVICE_KEY", "")
    if not (url and key): return "free"
    import httpx
    async with httpx.AsyncClient(timeout=8) as client:
        r = await client.get(f"{url}/rest/v1/profiles", params={"id": f"eq.{user['id']}", "select": "tier"},
                             headers={"apikey": key, "Authorization": f"Bearer {key}"})
    rows = r.json() if r.status_code == 200 else []
    return rows[0]["tier"] if rows and rows[0].get("tier") in TIER_STRATEGY_COUNT else "free"

async def _gift_of(user_id: str) -> dict | None:
    """The user's gift while it lasts: {"tier", "expires_at"}, else None."""
    async with async_session() as sess:
        g = await sess.get(PlanGrant, user_id)
    if g is None: return None
    grant = {"tier": g.tier, "expires_at": g.expires_at}
    return grant if pi.active_grant_tier(grant) else None

async def get_tier(user: dict) -> str:
    """Paid plan (Supabase profiles) or an active gift, whichever is higher. Fails closed to 'free'; admins get everything."""
    if is_admin(user):
        return "elite"
    hit = _tier_cache.get(user["id"])
    if hit and hit[0] > _time.monotonic():
        return hit[1]
    try:
        gift = await _gift_of(user["id"])
    except Exception as e:
        print(f"get_tier gift error: {type(e).__name__}")
        gift = None
    try:
        tier = await _paid_tier(user)
    except Exception as e:
        print(f"get_tier error: {e}")
        return gift["tier"] if gift else "free"  # don't cache failures
    if gift: tier = pi.higher_tier(tier, gift["tier"])
    if len(_tier_cache) > 5000: _tier_cache.clear()
    # a gift ending inside the cache window must not outlive its end
    ttl = 60 if not gift else max(1, min(60, (pi.parse(gift["expires_at"]) - pi.now()).total_seconds()))
    _tier_cache[user["id"]] = (_time.monotonic() + ttl, tier)
    return tier

def _cleanup_backtest_files(max_age_s: int = 3600):
    """Each backtest writes a .json + .png to BOT_DIR; without cleanup the disk fills up."""
    cutoff = _time.time() - max_age_s
    for p in BOT_DIR.glob("backtest_*_*.*"):
        if p.suffix in (".json", ".png") and re.fullmatch(r"backtest_[A-Za-z0-9_]+_[0-9a-f]{10}", p.stem):
            try:
                if p.stat().st_mtime < cutoff: p.unlink()
            except OSError: pass

def _scrub(text: str) -> str:
    """Don't show server paths (from tracebacks) to users."""
    return text.replace(str(BOT_DIR), ".")

# ── Health
@app.get("/api/health")
async def health():
    return {"ok": True, "name": "Raqm", "version": "2.0.0"}

# Public, for an uptime check outside the server (owner, 2026-11-01): the watchdog on the VPS (scripts/watchdog.py)
# writes a heartbeat every 5 minutes; 503 when it is missing or older than 15 — the timer stopped or the bots' side of
# the server is stuck. The VPS itself down shows as no answer at all. Only an age and a count, nothing about trades.
HEARTBEAT_MAX_AGE_S = 900

# HEAD too: UptimeRobot checks with HEAD first, and a 405 there is a failed check
@app.api_route("/api/health/bots", methods=["GET", "HEAD"])
async def health_bots():
    try:
        hb = json.loads((IPC_DIR / "watchdog_heartbeat.json").read_text(encoding="utf-8"))
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(hb["at"])).total_seconds()
        problems = int(hb.get("problems") or 0)
    except Exception:
        return JSONResponse({"ok": False, "reason": "no watchdog heartbeat"}, status_code=503)
    if not 0 <= age <= HEARTBEAT_MAX_AGE_S:
        return JSONResponse({"ok": False, "reason": "watchdog heartbeat stale", "age_s": int(age)}, status_code=503)
    return {"ok": True, "age_s": int(age), "problems": problems}

# ── Backtest: proxy to backtest.py (same logic, now via API + DB)
class BacktestReq(BaseModel):
    # frontend sends {from, to}; accept both spellings
    model_config = ConfigDict(populate_by_name=True)
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    from_date: Optional[str] = Field(None, alias="from")  # YYYY-MM-DD
    to_date: Optional[str] = Field(None, alias="to")
    limit: int = Field(300, ge=50, le=1000)
    strategies: Optional[List[str]] = None
    amount: float = Field(20, gt=0, le=100000)
    leverage: int = Field(5, ge=1, le=125)
    fee: float = Field(0.0004, ge=0, le=0.01)

    @field_validator("symbol")
    @classmethod
    def _sym(cls, v):
        v = v.upper().strip()
        if not SYMBOL_RE.match(v): raise ValueError("bad symbol")
        return v

    @field_validator("timeframe")
    @classmethod
    def _tf(cls, v):
        if v not in TIMEFRAMES: raise ValueError("bad timeframe")
        return v

    @field_validator("from_date", "to_date")
    @classmethod
    def _date(cls, v):
        if v and not re.match(r"^\d{4}-\d{2}-\d{2}$", v): raise ValueError("date must be YYYY-MM-DD")
        if v:
            from datetime import date
            date.fromisoformat(v)  # rejects impossible dates like 2026-13-45 (ValueError -> 422)
        return v or None

    @field_validator("strategies")
    @classmethod
    def _strats(cls, v):
        if v and not all(re.match(r"^[a-z0-9_]{1,30}$", x) for x in v): raise ValueError("bad strategy name")
        return v

@app.post("/api/backtest")
async def api_backtest(req: BacktestReq, user: dict = Depends(require_user)):
    rate_limit(user["id"], "backtest", int(os.getenv("BACKTEST_PER_MIN", "5")), 60)
    tier = await get_tier(user)
    max_days = TIER_BACKTEST_DAYS[tier]
    if max_days is not None:
        span = backtest_span_days(req)
        if span > max_days:
            raise HTTPException(403, f"backtest range is {span:g} days — your {tier} plan allows up to {max_days} days. Upgrade for longer backtests")
    allowed = STRATEGY_ORDER[:TIER_STRATEGY_COUNT[tier]]
    if req.strategies:
        locked = [s for s in req.strategies if s not in allowed]
        if locked:
            raise HTTPException(403, f"strategies not in your plan: {', '.join(locked)} — upgrade to unlock")
    else:
        req.strategies = ["trend_daily"]  # empty = the one strategy that backtests on a single coin
    if any(s not in PER_COIN for s in req.strategies):
        raise HTTPException(400, "only the daily trend backtests on one coin — the other bots trade a portfolio (results on the home page)")
    req.strategies = ["trend_daily"]
    req.timeframe = "1d"
    _cleanup_backtest_files()
    import json as js
    sym_file = req.symbol.replace("/","")
    # unique output per run so concurrent backtests don't read each other's results
    run_name = f"backtest_{sym_file}_{req.timeframe}_{uuid.uuid4().hex[:10]}"
    json_path = BOT_DIR / f"{run_name}.json"
    args = ["--out-json", str(json_path), "--out", str(BOT_DIR / f"{run_name}.png"), "--symbol", req.symbol, "--timeframe", req.timeframe, "--amount", str(req.amount), "--leverage", str(req.leverage), "--fee", str(req.fee)]
    if req.from_date: args += ["--from", req.from_date]
    if req.to_date: args += ["--to", req.to_date]
    if not req.from_date and not req.to_date: args += ["--limit", str(req.limit)]
    if req.strategies: args += ["--strategies", ",".join(req.strategies)]

    async with _backtest_slots:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(BOT_DIR / "backtest.py"), *args,
            cwd=str(BOT_DIR), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=110)
        except asyncio.TimeoutError:
            proc.kill(); raise HTTPException(504, "backtest timeout")
    out = stdout.decode(errors="ignore")
    err = stderr.decode(errors="ignore")

    # Read JSON
    data = None
    if json_path.exists():
        try: data = js.loads(json_path.read_text(encoding="utf-8"))
        except: pass

    # Save to DB
    try:
        async with async_session() as sess:
            rec = BacktestRun(user_id=user["id"], symbol=req.symbol, timeframe=req.timeframe, from_date=req.from_date, to_date=req.to_date, strategies=js.dumps(req.strategies or []), stats=js.dumps(data.get("stats",{}) if data else {}), created_at=datetime.now(timezone.utc).isoformat(), chart_file=f"{run_name}.png", run_name=run_name)
            sess.add(rec); await sess.commit()
    except: pass

    return {"ok": proc.returncode==0, "code": proc.returncode, "stdout": _scrub(out[-8000:]), "stderr": _scrub(err[-2000:]), "data": data, "chart": f"{run_name}.png"}

@app.get("/api/backtest/history")
async def backtest_history(limit: int = 20, user: dict = Depends(require_user)):
    limit = max(1, min(limit, 100))
    async with async_session() as sess:
        # only the caller's own runs (this used to list every user's backtests)
        res = await sess.execute(select(BacktestRun).where(BacktestRun.user_id == user["id"]).order_by(desc(BacktestRun.id)).limit(limit))
        rows = res.scalars().all()
        return [{"id":r.id,"symbol":r.symbol,"timeframe":r.timeframe,"from":r.from_date,"to":r.to_date,"strategies":r.strategies,"stats":r.stats,"at":r.created_at} for r in rows]

@app.get("/api/chart")
async def api_chart(file: str, user: dict = Depends(require_user)):
    # Stage C: strict file->run binding - any owned run no longer unlocks every file
    if not re.fullmatch(r"backtest_[A-Za-z0-9_]+\.(png|json)", file):
        raise HTTPException(400, "bad file")
    stem = file.rsplit(".", 1)[0]
    async with async_session() as sess:
        res = await sess.execute(select(BacktestRun).where((BacktestRun.user_id==user["id"]) & ((BacktestRun.run_name==stem) | (BacktestRun.chart_file==file))).limit(1))
        row = res.scalars().first()
        if row is None:
            raise HTTPException(403, "not your chart")
    p = BOT_DIR / file
    if not p.exists(): raise HTTPException(404, "not found")
    ct = "image/png" if file.endswith(".png") else "application/json"
    return FileResponse(str(p), media_type=ct)

# ── Bot control: status, start/stop (paper), trades
bot_task = None
_bot_task_id = None
_control_wakeup = asyncio.Event()

def _wake_managed_loop():
    _control_wakeup.set()

async def _sleep_until_wakeup(seconds):
    try:
        await asyncio.wait_for(_control_wakeup.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass
    _control_wakeup.clear()

def execute_strategy_cycle(root, strategy, protection, entry):
    """Run protection regardless of desired state; gate only new entries."""
    protection()
    active = admin_control.controls(root, strategy)["active"]
    if active: entry()
    return {"entries_enabled": active}

async def _wait_strategy_runtime(strategy, *, active: bool, expected_task_id=None, action_at=None, timeout: float = 5.0):
    deadline = _time.monotonic() + timeout
    while _time.monotonic() < deadline:
        runtime = admin_control.get_runtime(BOT_DIR, strategy)
        if active and runtime["status"] == "running" and runtime.get("heartbeat"):
            task_matches = expected_task_id is None or runtime.get("task_id") == expected_task_id
            heartbeat_fresh = True
            if action_at:
                try:
                    heartbeat_fresh = datetime.fromisoformat(runtime["heartbeat"]) >= datetime.fromisoformat(action_at)
                except (TypeError, ValueError):
                    heartbeat_fresh = False
            if task_matches and heartbeat_fresh:
                return runtime
        if not active and runtime["status"] in ("stopped", "paused"):
            return runtime
        await asyncio.sleep(0.02)
    return admin_control.get_runtime(BOT_DIR, strategy)

def _ensure_managed_loop():
    global bot_task, _bot_task_id
    if bot_task is None or bot_task.done():
        cfg_path = BOT_DIR / "api_bot_config.json"
        cfg = _safe_json_file(cfg_path) or {"paper": True, "running": True}
        cfg["paper"] = True; cfg["running"] = True
        _bot_task_id = uuid.uuid4().hex
        bot_task = asyncio.create_task(bot_loop(cfg, task_id=_bot_task_id))
    return bot_task

@app.get("/api/bot/status")
async def bot_status(user: dict = Depends(require_admin)):
    from app.db import Trade as T
    async with async_session() as sess:
        res = await sess.execute(select(T).where(T.status=="open"))
        opens = res.scalars().all()
        res2 = await sess.execute(select(T))
        all_trades = res2.scalars().all()
        wins = sum(1 for t in all_trades if t.pnl and t.pnl>0)
        losses = sum(1 for t in all_trades if t.pnl and t.pnl<0)
        pnl = sum(t.pnl or 0 for t in all_trades)
        return {"running": bot_task is not None and not bot_task.done(), "open": len(opens), "positions": [{"symbol":t.symbol,"side":t.side,"entry":t.entry,"qty":t.qty,"sl":t.sl,"tp":t.tp} for t in opens], "stats": {"total": len(all_trades), "wins": wins, "losses": losses, "pnl": round(pnl,2)}}

class BotStartReq(BaseModel):
    symbols: Optional[List[str]] = None
    strategies: Optional[List[str]] = None
    timeframe: str = "1h"
    paper: bool = True
    leverage: Optional[int] = Field(None, ge=1, le=5)  # None = 2 for the daily trend, 5 otherwise

    @field_validator("symbols")
    @classmethod
    def _syms(cls, v):
        if v is None: return v
        v = [s.upper().strip() for s in v][:30]
        if not all(SYMBOL_RE.match(s) for s in v): raise ValueError("bad symbol")
        return v

    @field_validator("strategies")
    @classmethod
    def _strats(cls, v):
        if v and not all(re.match(r"^[a-z0-9_]{1,30}$", x) for x in v): raise ValueError("bad strategy name")
        return v

    @field_validator("timeframe")
    @classmethod
    def _tf(cls, v):
        if v not in TIMEFRAMES: raise ValueError("bad timeframe")
        return v

@app.post("/api/bot/start")
async def bot_start(req: BotStartReq, bg: BackgroundTasks, user: dict = Depends(require_admin)):
    global bot_task
    if bot_task and not bot_task.done():
        return {"ok": False, "msg": "already running"}
    if not req.paper:
        # this loop runs the old score strategies, never tested with real orders; the daily trend's real orders
        # run as their own service (bot.py --live, deploy/vps/raqm-demo@.service / raqm-live@.service), not from the dashboard
        raise HTTPException(400, "real orders don't start from the dashboard — the daily trend runs them as its own service on the server")
    solo = [s for s in (req.strategies or []) if s in SOLO_STRATEGIES]
    if not req.paper and solo:
        # Wave Flats: partial take-profit + moving stop aren't exchange orders yet (and it lost money in testing);
        # daily trend: paper first, compared with the backtest for a few weeks before any real money
        raise HTTPException(400, f"{solo[0]} runs in paper mode only for now")
    if solo:
        req.strategies = solo[:1]  # own entries/exits — can't be mixed with the score strategies
    if req.strategies == ["trend_daily"]: req.timeframe = "1d"
    # Save config for bot loop
    lev = req.leverage or (2 if req.strategies == ["trend_daily"] else 5)
    cfg = {"symbols": req.symbols, "strategies": req.strategies, "timeframe": req.timeframe, "paper": req.paper, "leverage": lev, "running": True}
    (BOT_DIR / "api_bot_config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    for strategy in (req.strategies or admin_control.STRATEGIES):
        if strategy in admin_control.STRATEGIES:
            admin_control.set_strategy_lifecycle(BOT_DIR, strategy, "start", str(user.get("email") or user.get("id") or "admin"))
    global _bot_task_id
    _bot_task_id = uuid.uuid4().hex
    bot_task = asyncio.create_task(bot_loop(cfg, task_id=_bot_task_id))
    return {"ok": True, "msg": "started", "config": cfg}

@app.post("/api/bot/stop")
async def bot_stop(user: dict = Depends(require_admin)):
    global bot_task
    if bot_task: bot_task.cancel()
    try:   # stopped on purpose: don't resume after the next restart
        cfg_path = BOT_DIR / "api_bot_config.json"
        if cfg_path.exists():
            cfg = json.loads(cfg_path.read_text(encoding="utf-8")); cfg["running"] = False
            cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    except Exception as e: print(f"bot stop config {e}")
    return {"ok": True}


def _get_exchange_for_cycle(paper: bool):
    """Returns (name, instance, is_paper) or None.
    LIVE trades on the first LIVE exchange only — positions state is shared, so executing the
    same signal on several exchanges would corrupt it. If LIVE was requested but nothing is
    available, returns None (skip the cycle) instead of silently falling back to paper, which
    would "close" real positions only in the local state."""
    import ccxt as _ccxt
    if paper:
        return ("paper", _ccxt.bybit({"enableRateLimit": True}), True)
    if not live_trading_allowed():
        print("LIVE requested but ALLOW_LIVE_TRADING is not true — skipping cycle")
        return None
    try:
        from app.exchange_manager import get_all_instances
        instances = get_all_instances("live")
    except Exception as e:
        print(f"exchange_manager fail {e}")
        return None
    if not instances:
        print("LIVE requested but no exchange is LIVE in the vault — skipping cycle")
        return None
    name, inst = next(iter(instances.items()))
    if len(instances) > 1:
        print(f"WARNING: {len(instances)} LIVE exchanges — only {name} will trade")
    return (name, inst, False)

async def bot_loop(cfg, task_id=None):
    """يحلل كل poll_seconds ويحفظ في DB + يرسل تليجرام"""
    import strategies_advanced as adv
    import bot as botmod
    # Override enabled
    if cfg.get("strategies"): botmod.CONFIG["enabled_strategies"] = cfg["strategies"]
    if cfg.get("timeframe"): botmod.CONFIG["timeframe"] = cfg["timeframe"]
    if cfg.get("symbols"): botmod.CONFIG["symbols"] = cfg["symbols"]
    if cfg.get("leverage"): botmod.CONFIG["leverage"] = int(cfg["leverage"])
    from app.telegram_bot import send_telegram, format_entry, format_exit
    from app.oco import place_oco_orders, cancel_oco_orders
    is_paper = True   # the dashboard loop is paper only: real orders run as the trend's own service (bot.py --live)
    if not cfg.get("paper", True):
        print("bot_loop: real orders refused — paper only"); return
    print(f"Bot loop started {cfg}")
    while True:
        try:
            controls = {s: admin_control.controls(BOT_DIR, s) for s in admin_control.STRATEGIES}
            active_strategies = [s for s, c in controls.items() if c["active"]]
            for strategy, control in controls.items():
                if control["active"]:
                    admin_control.mark_runtime(BOT_DIR, strategy, status="running", heartbeat=admin_control.now(), last_cycle=admin_control.now(), task_id=task_id)
                else:
                    admin_control.mark_runtime(BOT_DIR, strategy, status="paused" if control["paused"] else "stopped", task_id=task_id)
            botmod.CONFIG["enabled_strategies"] = active_strategies
            picked = _get_exchange_for_cycle(is_paper)
            if picked is None:
                await _sleep_until_wakeup(int(botmod.CONFIG.get("poll_seconds",60)))
                continue
            ex_name, ex, cycle_paper = picked
            botmod.CONFIG["paper_trading"] = cycle_paper
            # real positions get their own file: a paper cycle must never "close" them in a shared record
            botmod.STATE_PATH = BOT_DIR / ("state.json" if cycle_paper else "state_live.json")
            botmod.LOG_PATH = BOT_DIR / ("trades.log" if cycle_paper else "trades_live.log")
            state = botmod.load_state()
            prices={}; analyses={}
            for sym in botmod.CONFIG["symbols"]:
                try:
                    df=botmod.fetch_ohlcv(sym, botmod.CONFIG["timeframe"], limit=botmod.candles_needed(), ex=ex)
                    a=botmod.analyze(sym, df); analyses[sym]=a; prices[sym]=a["price"]
                except Exception as e: print(f"{sym} {e}")
            before = set(state.get("positions",{}).keys())
            # P0-03 Stage C: validated reconciliation with state machine - never auto-delete on incomplete data
            if not cycle_paper:
                try:
                    state.setdefault("_reconcile", {})
                    recon = state["_reconcile"]
                    recon["state"] = "ok"   # decided again every cycle from what the exchange shows now (pending counts carry over)
                    # positions on the exchange that we didn't open (manual trades, another bot, a lost record)
                    try:
                        mine = {k.split(":")[0] for k in state.get("positions", {})}
                        unknown = []
                        for pp in ex.fetch_positions() or []:
                            s_ = (pp.get("symbol") or "").split(":")[0]
                            c_ = pp.get("contracts") if pp.get("contracts") is not None else (pp.get("info") or {}).get("size")
                            if s_ and s_ not in mine and float(c_ or 0) != 0:
                                unknown.append(s_)
                        recon["unknown"] = unknown
                        if unknown:
                            print(f"reconcile: positions on {ex_name} the bot didn't open: {unknown} — use a sub-account only for the bot")
                            recon["state"] = "reconciling"
                    except Exception as e:
                        print(f"reconcile: fetch all positions failed {e}")
                        recon["state"] = "reconciling"
                    local_items = list(state.get("positions", {}).items())
                    validated_syms = []
                    has_invalid = False
                    for sym, pos in local_items:
                        side = pos.get("side")
                        qty = pos.get("qty")
                        sym_ok = isinstance(sym, str) and "/" in sym
                        side_ok = side in ("long", "short")
                        try:
                            qty_ok = isinstance(qty, (int,float)) and float(qty) > 0
                        except Exception:
                            qty_ok = False
                        # exchange/positionMode presence check (symbol/side/qty/exchange/positionMode)
                        exch = pos.get("exchange") or ex_name
                        pmode = pos.get("positionMode") or pos.get("position_mode")
                        # require side/qty/symbol; exchange/mode get defaults but flag incomplete
                        if not (sym_ok and side_ok and qty_ok):
                            print(f"reconcile: {sym} invalid fields side={side!r} qty={qty!r} -> reconciling")
                            recon["state"] = "reconciling"
                            has_invalid = True
                        else:
                            validated_syms.append(sym)
                    if not local_items:
                        recon.pop("pending", None)
                    elif has_invalid and not validated_syms:
                        recon["state"] = "reconciling"
                    elif validated_syms:
                        fetched = ex.fetch_positions(validated_syms)
                        if fetched is None:
                            print("reconcile: fetch_positions returned None -> reconciling")
                            recon["state"] = "reconciling"
                        elif not isinstance(fetched, list):
                            print(f"reconcile: bad fetch_positions type {type(fetched).__name__} -> reconciling")
                            recon["state"] = "reconciling"
                        else:
                            ex_map = {}
                            for pp in fetched:
                                s = pp.get("symbol") or (pp.get("info") or {}).get("symbol") or ""
                                if s:
                                    ex_map[s] = pp
                                    base = s.split(":")[0]
                                    if base not in ex_map:
                                        ex_map[base] = pp
                            if not ex_map:
                                print("reconcile: empty ex_map -> incomplete, reconciling")
                                recon["state"] = "reconciling"
                                recon.setdefault("pending", {})
                                for s in validated_syms:
                                    recon["pending"][s] = recon["pending"].get(s, 0) + 1
                            else:
                                pending = recon.setdefault("pending", {})
                                for sym in validated_syms:
                                    pos = state.get("positions", {}).get(sym)
                                    if pos is None:
                                        pending.pop(sym, None)
                                        continue
                                    ep = ex_map.get(sym) or ex_map.get(sym.split(":")[0])
                                    if ep is None:
                                        print(f"reconcile: {sym} missing from fetch -> reconciling")
                                        recon["state"] = "reconciling"
                                        pending[sym] = pending.get(sym, 0) + 1
                                        continue
                                    # validate contracts field exists
                                    try:
                                        raw = ep.get("contracts")
                                        if raw is None:
                                            raw = (ep.get("info") or {}).get("size")
                                        if raw is None:
                                            print(f"reconcile: {sym} no contracts/size -> reconciling")
                                            recon["state"] = "reconciling"
                                            continue
                                        contracts = float(raw or 0)
                                    except Exception:
                                        print(f"reconcile: {sym} bad contracts -> reconciling")
                                        recon["state"] = "reconciling"
                                        continue
                                    if contracts == 0:
                                        cnt = pending.get(sym, 0)
                                        if cnt < 1:
                                            print(f"reconcile: {sym} flat -> pending reconciling")
                                            pending[sym] = cnt + 1
                                            recon["state"] = "reconciling"
                                        else:
                                            print(f"reconcile: {sym} flat 2x -> closing local")
                                            state["positions"].pop(sym, None)
                                            state["last_trade"][sym] = datetime.now(timezone.utc).isoformat()
                                            pending.pop(sym, None)
                                    else:
                                        pending.pop(sym, None)
                                        try:
                                            local_qty = float(pos.get("qty", 0))
                                            if abs(local_qty - contracts) / max(1e-9, abs(contracts)) > 0.05:
                                                print(f"reconcile: {sym} qty mismatch {local_qty} vs {contracts} -> reconciling")
                                                recon["state"] = "reconciling"
                                        except Exception:
                                            pass
                                if not recon.get("pending"):
                                    if recon.get("state") != "reconciling":
                                        recon["state"] = "ok"
                                else:
                                    recon["state"] = "reconciling"
                except Exception as e:
                    print(f"reconcile warn: {e}")
                    try:
                        state.setdefault("_reconcile", {})["state"] = "reconciling"
                    except Exception:
                        pass
                try: botmod.save_state(state)   # pending counts must survive to the next cycle
                except Exception as e: print(f"reconcile save {e}")
            if prices: botmod.check_sl_tp(state, prices, ex)
            # no new position while the exchange and our record disagree, or a position needs a human
            blocked = None
            admin_state = admin_control.read_state(BOT_DIR)
            if admin_state.get("entry_paused", {}).get("paused"):
                blocked = f"entries paused: {admin_state['entry_paused'].get('reason') or 'operator pause'}"
            if not cycle_paper and (state.get("_reconcile") or {}).get("state") == "reconciling":
                blocked = "reconciling with the exchange"
            if state.get("recovery_required"):
                blocked = f"needs review: {', '.join(state['recovery_required'])}"
            review_before = set(state.get("recovery_required") or {})
            if blocked or not active_strategies:
                print(f"entries blocked — {blocked}")
            else:
                for sym,a in analyses.items():
                    try: botmod.try_enter(sym,a,state,ex)
                    except Exception as e: print(f"enter {sym} {e}")
            for sym in set(state.get("recovery_required") or {}) - review_before:
                info = state["recovery_required"][sym]
                await send_telegram(f"🚨 {ex_name} {sym}: {info.get('reason', 'needs review')} — new entries are blocked until it is resolved")
            after = set(state.get("positions",{}).keys())
            # Persist to DB
            try:
                async with async_session() as sess:
                    # New entries — OCO is now handled atomically inside bot.py:try_enter for LIVE (P0-01); bot_loop only persists
                    for sym in (after - before):
                        pos=state["positions"][sym]
                        if not cycle_paper and not pos.get("oco_ids"):
                            # Should not happen: LIVE entry without OCO ids means OCO failed and try_enter should have flattened
                            print(f"OCO warn {ex_name} {sym}: LIVE entry without oco_ids — skipping DB open")
                            continue
                        rec=Trade(symbol=sym, side=pos["side"], entry=pos["entry"], qty=pos["qty"], sl=pos["sl"], tp=pos["tp"], leverage=pos.get("leverage",5), entry_ts=pos.get("time",""), status="open", created_at=datetime.now(timezone.utc).isoformat())
                        sess.add(rec); await sess.flush()
                        # (3) persist oco_ids to DB ProtectiveOrder before pop so cancel can use ownership ids
                        try:
                            oco_ids = pos.get("oco_ids") or {}
                            sl_id = oco_ids.get("sl"); tp_id = oco_ids.get("tp")
                            # need trade_id after flush
                            tid = rec.id
                            for side_key, cid in (("sl", sl_id), ("tp", tp_id)):
                                if cid:
                                    from app.db import ProtectiveOrder
                                    po = ProtectiveOrder(trade_id=tid, symbol=sym, client_order_id=cid, exchange_order_id=None, side=side_key, qty=pos.get("qty"), price=pos.get("sl") if side_key=="sl" else pos.get("tp"), status="open", created_at=datetime.now(timezone.utc).isoformat())
                                    sess.add(po)
                        except Exception as e:
                            print(f"persist oco_ids {sym}: {e}")
                        # also snapshot to state for file-based cancel
                        try:
                            if pos.get("oco_ids"):
                                state.setdefault("_last_oco", {})[sym] = dict(pos["oco_ids"])
                        except: pass
                        await sess.commit()
                        strat = (botmod.CONFIG.get("enabled_strategies") or ["ict"])[0]
                        await send_telegram(format_entry(sym, pos["side"], pos["entry"], pos["sl"], pos["tp"], pos.get("leverage",5), analyses[sym]["total"] if sym in analyses else 0, float(pos.get("notional",20))/max(1,int(pos.get("leverage",5))), botmod.CONFIG.get("timeframe","4h"), strat))
                    # Snapshot oco_ids before pops: persist to DB/state so cancel can use ownership ids; replace unfinished pass and prefix-broad cancel with id-only
                    # Build snapshot of oco ids for symbols that closed this cycle (before - after)
                    _oco_snapshot = {}
                    for sym in (before - after):
                        # prefer state._last_oco (written by bot.py try_enter), fallback to state._oco_ids or state positions backup
                        snap = None
                        try:
                            snap = (state.get("_last_oco") or {}).get(sym)
                        except: pass
                        if not snap:
                            try:
                                snap = (state.get("_oco_ids") or {}).get(sym)
                            except: pass
                        if snap:
                            _oco_snapshot[sym] = snap
                        # persist to DB ProtectiveOrder or state snapshot for future cancel
                        if snap:
                            try:
                                # also write to session later if needed; keep in state for now
                                state.setdefault("_closed_oco", {})[sym] = dict(snap)
                            except: pass
                    # Closed: mark (P0-04: cancel only owned OCO via id-only, never broad raqm-* prefix)
                    for sym in (before - after):
                        if not cycle_paper:
                            snap = _oco_snapshot.get(sym) or (state.get("_closed_oco") or {}).get(sym)
                            if snap:
                                try:
                                    # id-only cancel: use stored oco_ids (sl/tp/pos_id)
                                    pos_id = snap.get("pos_id")
                                    sl_id = snap.get("sl")
                                    tp_id = snap.get("tp")
                                    if pos_id:
                                        cancel_oco_orders(ex, sym, pos_id=pos_id)
                                    elif sl_id or tp_id:
                                        cancel_oco_orders(ex, sym, sl_id=sl_id, tp_id=tp_id)
                                    else:
                                        # no ids stored — do NOT broad-cancel; log and skip
                                        print(f"cancel skip {sym}: no oco ids stored, refusing broad cancel")
                                except Exception as e:
                                    print(f"cancel_oco {sym}: {e}")
                            else:
                                print(f"cancel skip {sym}: no snapshot, refusing broad cancel")
                            # consume snapshot after attempt
                            try: state.get("_closed_oco", {}).pop(sym, None)
                            except: pass
                            try: state.get("_last_oco", {}).pop(sym, None)
                            except: pass
                        hist=[h for h in state.get("history",[]) if h.get("symbol")==sym]
                        last=hist[-1] if hist else {}
                        res=await sess.execute(select(Trade).where(Trade.symbol==sym, Trade.status=="open"))
                        row=res.scalars().first()
                        if row:
                            row.exit=float(last.get("exit", prices.get(sym, row.entry)))
                            row.pnl=float(last.get("pnl",0)); row.exit_ts=str(last.get("time","")); row.status="closed"
                            await sess.commit()
                            await send_telegram(format_exit(sym, row.side, float(row.entry or last.get("entry",0)), float(row.exit or last.get("exit",0)), float(row.qty or last.get("qty",0)), float(row.pnl or last.get("pnl",0)), float((float(row.pnl or 0)/float(row.entry or 1)*100) if row.entry else 0), last.get("reason",""), int(row.leverage or 5)))
            except Exception as e: print(f"DB save {e}")
            # Dashboard file
            try:
                (BOT_DIR / "dashboard-data.json").write_text(json.dumps({"analyses":analyses,"state":state,"time":datetime.now(timezone.utc).isoformat()}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            except: pass
        except asyncio.CancelledError:
            for strategy in admin_control.STRATEGIES:
                try: admin_control.mark_runtime(BOT_DIR, strategy, status="paused" if admin_control.controls(BOT_DIR, strategy)["paused"] else "stopped", task_id=task_id)
                except Exception: pass
            print("bot loop stopped"); break
        except Exception as e:
            for strategy in admin_control.STRATEGIES:
                try: admin_control.mark_runtime(BOT_DIR, strategy, status="error", error=str(e)[:300], task_id=task_id)
                except Exception: pass
            print(f"loop err {e}")
        await _sleep_until_wakeup(int(botmod.CONFIG.get("poll_seconds",60)))


class SettingsReq(BaseModel):
    capital: float = Field(..., ge=10, le=10_000_000)
    strategy: str

    @field_validator("strategy")
    @classmethod
    def _strategy(cls, v):
        if v not in STRATEGY_ORDER: raise ValueError("unknown strategy")
        return v


@app.get("/api/user/settings")
async def get_settings(user: dict = Depends(require_user)):
    """The caller's own capital and followed bot (personal paper portfolio on the dashboard)."""
    async with async_session() as sess:
        row = await sess.get(UserSetting, user["id"])
        if not row: return {}
        res = await sess.execute(select(UserClose).where(UserClose.user_id == user["id"]))
        closes = [{"key": c.trade_key, "bot_pnl": c.bot_pnl, "exit_price": c.exit_price, "closed_at": c.closed_at} for c in res.scalars().all()]
        return {"capital": row.capital, "strategy": row.strategy, "started_at": row.started_at, "closes": closes}


@app.post("/api/user/settings")
async def save_settings(req: SettingsReq, user: dict = Depends(require_user)):
    rate_limit(user["id"], "settings", 20, 60)
    tier = await get_tier(user)
    if req.strategy not in STRATEGY_ORDER[:TIER_STRATEGY_COUNT[tier]]:
        raise HTTPException(403, f"{req.strategy} is not in your {tier} plan — upgrade to unlock")
    now = datetime.now(timezone.utc).isoformat()
    async with async_session() as sess:
        row = await sess.get(UserSetting, user["id"])
        if row is None:
            row = UserSetting(user_id=user["id"], started_at=now); sess.add(row)
        elif row.capital != req.capital or row.strategy != req.strategy:
            row.started_at = now                                   # a new setup starts a new personal record
            from sqlalchemy import delete as _delete
            await sess.execute(_delete(UserClose).where(UserClose.user_id == user["id"]))   # and its own closes go with it
        row.capital, row.strategy, row.updated_at = req.capital, req.strategy, now
        await sess.commit()
        return {"capital": row.capital, "strategy": row.strategy, "started_at": row.started_at}


# ── manual closes: users in their own paper portfolio, the admin in the paper bots ──
BOT_PUBLIC_DIR = Path(os.getenv("BOT_PUBLIC_DIR", "/var/www/bot.da3m.io"))      # the bots' public JSON (read only)
PAPER_IPC = Path(os.getenv("RAQM_PAPER_IPC", "/opt/raqm-ipc-paper"))             # close requests to the paper bots
PAPER_BOTS = ("status", "momentum", "listing", "ratio", "breakout", "rsi2", "tbreak")
STRATEGY_FILE = {"trend_daily": "status", "momentum_ls": "momentum", "listing_short": "listing", "ratio_trend": "ratio"}
COIN_RE = re.compile(r"^[A-Z0-9]{1,20}/USDT(:USDT)?$")
PAIR_RE = re.compile(r"^[A-Z0-9]{1,20}/USDT:USDT\|[A-Z0-9]{1,20}/USDT:USDT$")

def _bot_json(name: str) -> dict:
    try: return json.loads((BOT_PUBLIC_DIR / f"{name}.json").read_text(encoding="utf-8"))
    except Exception: raise HTTPException(503, "bot data unavailable")

def _label(name: str, p: dict) -> str:
    """The trade's label as the site shows it: the coin, or 'LONG / SHORT' for a ratio pair."""
    if name == "ratio": return f"{p['long']['symbol'].split('/')[0]} / {p['short']['symbol'].split('/')[0]}"
    return p["symbol"].split("/")[0]

@app.get("/api/user/me")
async def user_me(user: dict = Depends(require_user)):
    return {"admin": is_admin(user)}

class PortfolioCloseReq(BaseModel):
    label: str = Field(max_length=60)
    opened: str = Field(max_length=40)

@app.post("/api/user/portfolio/close")
async def portfolio_close(req: PortfolioCloseReq, user: dict = Depends(require_user)):
    """Close one trade in the caller's own paper portfolio at the bot's current price. Server-side: the trade must be
    open in the bot the user follows and opened after their start — the price comes from the bot, never from the user."""
    rate_limit(user["id"], "portfolio_close", 30, 60)
    async with async_session() as sess:
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

def _drop_request(d: Path, root: Path, rid: str, cmd: dict, mode: int = 0o660):
    """A close request file in `d`: the folder must really be inside `root` (no link swapped in for it — a paper
    bot's commands/ pointing at the real-money bot's folder would turn a paper close into a real one), and the file
    is created new (O_EXCL, O_NOFOLLOW) then renamed in, so nothing planted there is written through.
    `mode` 0644 for a user's bot: it isn't in the API's group, and the folder lets in only the two of them."""
    real, base = os.path.realpath(d), os.path.realpath(root)
    if os.path.islink(d) or os.path.commonpath([real, base]) != base or real != os.path.normpath(os.path.join(base, os.path.relpath(d, root))):
        raise HTTPException(500, "request folder is not where it should be — refused")
    tmp = os.path.join(real, f".close-{rid}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), mode)
    if hasattr(os, "fchmod"): os.fchmod(fd, mode)     # the umask must not take the bot's read bit away
    with os.fdopen(fd, "w", encoding="utf-8") as fh: fh.write(json.dumps(cmd))
    os.replace(tmp, os.path.join(real, f"close-{rid}.json"))   # the bot only picks up close-*.json

@app.post("/api/paper/close")
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
    _drop_request(PAPER_IPC / req.bot / "commands", PAPER_IPC, rid, {"id": rid, "symbol": req.symbol, "at_epoch": _time.time(), "by": user.get("email")})
    return {"ok": True, "id": rid}

@app.get("/api/paper/close/{bot}/{rid}")
async def paper_close_result(bot: str, rid: str, user: dict = Depends(require_admin)):
    if bot not in PAPER_BOTS or not re.fullmatch(r"[0-9a-f]{32}", rid): raise HTTPException(400, "bad request")
    f = PAPER_IPC / bot / "results" / f"{rid}.json"
    if not f.exists(): return {"done": False, "pending": (PAPER_IPC / bot / "commands" / f"close-{rid}.json").exists()}
    return {"done": True, **json.loads(f.read_text(encoding="utf-8"))}


@app.get("/api/user/tier")
async def user_tier(user: dict = Depends(require_user)):
    """The caller's plan (paid or gift, the higher) — server-side verification; gift = an active gift's plan and end."""
    gift = None
    try: gift = None if is_admin(user) else await _gift_of(user["id"])
    except Exception: pass
    return {"tier": await get_tier(user), "gift": gift}


@app.post("/api/optimizer/run")
async def optimizer_run(symbol: str = "BTC/USDT", timeframe: str = "4h", limit: int = 200, user: dict = Depends(require_admin)):
    """يشغل Auto-Optimizer ويرجع البطل — يحدث ai_weights.json"""
    rate_limit(user["id"], "optimizer", 2, 300)
    import json as js
    if not SYMBOL_RE.match(symbol) or timeframe not in TIMEFRAMES: raise HTTPException(400, "bad symbol/timeframe")
    limit = max(50, min(int(limit), 1000))
    if not (BOT_DIR / "auto_optimizer.py").exists():
        return {"ok": False, "error": "auto_optimizer.py is missing from the repo"}
    args = [sys.executable, str(BOT_DIR / "auto_optimizer.py"), "--symbol", symbol, "--timeframe", timeframe, "--limit", str(limit)]
    try:
        proc = await asyncio.create_subprocess_exec(*args, cwd=str(BOT_DIR), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
        out = stdout.decode(errors="ignore"); err = stderr.decode(errors="ignore")
        # Read weights if created
        weights = None
        try:
            wp = BOT_DIR / "ai_weights.json"
            if wp.exists(): weights = js.loads(wp.read_text(encoding="utf-8"))
        except: pass
        return {"ok": proc.returncode==0, "stdout": out[-4000:], "stderr": err[-1500:], "weights": weights}
    except asyncio.TimeoutError:
        return {"ok": False, "error": "optimizer timeout — جرب limit أصغر"}

@app.post("/api/telegram/test")
async def telegram_test(user: dict = Depends(require_admin)):
    from app.telegram_bot import test_telegram
    ok = await test_telegram()
    return {"ok": bool(ok), "msg": "تم الإرسال" if ok else "فشل — تأكد من TELEGRAM_BOT_TOKEN و CHAT_ID في backend/.env"}

@app.get("/api/telegram/status")
async def telegram_status(user: dict = Depends(require_admin)):
    import os
    has_token = bool(os.getenv("TELEGRAM_BOT_TOKEN","").strip())
    has_chat = bool(os.getenv("TELEGRAM_CHAT_ID","").strip())
    return {"configured": has_token and has_chat, "has_token": has_token, "has_chat": has_chat}


@app.post("/api/evolve")
async def evolve(user: dict = Depends(require_admin_or_cron)):
    """Self-evolution: يعيد تقييم الـ 15 استراتيجية ويطفي الخسرانة + يحدث الأوزان"""
    rate_limit(user["id"], "evolve", 1, 300)
    import json as js
    if not (BOT_DIR / "auto_optimizer.py").exists():
        return {"ok": False, "error": "auto_optimizer.py is missing from the repo"}
    # Run optimizer on BTC 4h (light)
    args = [sys.executable, str(BOT_DIR / "auto_optimizer.py"), "--symbol", "BTC/USDT", "--timeframe", "4h", "--limit", "200"]
    try:
        proc = await asyncio.create_subprocess_exec(*args, cwd=str(BOT_DIR), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
        out = stdout.decode(errors="ignore")
        # Read weights
        weights = None
        try:
            wp = BOT_DIR / "ai_weights.json"
            if wp.exists():
                weights = js.loads(wp.read_text(encoding="utf-8"))
        except: pass
        # Self-pruning: if any strategy PF < 0.8 for 2 weeks, suggest disabling
        pruning = []
        try:
            cmp_path = BOT_DIR / "optimizer_BTCUSDT_4h.json"
            if cmp_path.exists():
                data = js.loads(cmp_path.read_text(encoding="utf-8"))
                for p in data.get("perfs", []):
                    if p.get("pf", 99) < 0.8 and p.get("pnl", 0) < -5:
                        pruning.append({"strategy": p["name"], "pf": p["pf"], "pnl": p["pnl"], "action": "disable_suggested"})
        except: pass
        # Telegram report
        try:
            from app.telegram_bot import send_telegram
            top = ", ".join(list((weights or {}).keys())[:3]) if weights else "?"
            msg = f"\U0001f916 *Self-Evolution*\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\nBTC 4h updated\nTop weights: `{str(weights)[:120] if weights else '?'}`\nPruning: `{pruning if pruning else 'none'}`"
            await send_telegram(msg)
        except: pass
        return {"ok": proc.returncode==0, "weights": weights, "pruning": pruning, "stdout": _scrub(out[-3000:]), "stderr": _scrub(stderr.decode(errors="ignore")[-800:])}
    except asyncio.TimeoutError:
        return {"ok": False, "error": "evolve timeout"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


@app.post("/api/llm/generate")
async def llm_generate(prompt: str = "RSI + volume divergence on 4h", symbol: str = "BTC/USDT", timeframe: str = "4h", user: dict = Depends(require_admin)):
    """LLM يخترع استراتيجية + باك تست فوري (الكود بيتشغل في sandbox — شوف llm_sandbox.py)"""
    _require_llm_lab()
    rate_limit(user["id"], "llm_generate", 3, 300)
    if not SYMBOL_RE.match(symbol) or timeframe not in TIMEFRAMES: raise HTTPException(400, "bad symbol/timeframe")
    prompt = prompt[:500]
    from app.llm_generator import generate_strategy, save_strategy, backtest_llm
    gen = await generate_strategy(prompt)
    if not gen.get("ok"):
        return gen
    code = gen["code"]
    from app.llm_sandbox import validate_code, UnsafeCode
    try: validate_code(code)
    except UnsafeCode as e: return {"ok": False, "error": f"unsafe code refused: {e}", "code": code}
    # Save
    try:
        fp = save_strategy(code)
        name = fp.stem
    except Exception as e:
        return {"ok": False, "error": f"save failed: {e}", "code": code}
    # Backtest
    try:
        bt_result = await backtest_llm(code, symbol, timeframe, limit=300)
    except Exception as e:
        return {"ok": True, "code": code, "name": name, "backtest": {"ok": False, "error": str(e)[:300]}, "usage": gen.get("usage")}
    return {"ok": True, "code": code, "name": name, "backtest": bt_result, "usage": gen.get("usage")}

@app.get("/api/llm/list")
async def llm_list(user: dict = Depends(require_admin)):
    from pathlib import Path as _P
    d = _P(__file__).parent.parent / "strategies_llm"
    if not d.exists():
        return []
    out = []
    for f in sorted(d.glob("llm_*.py")):
        out.append({"name": f.stem, "code": f.read_text(encoding="utf-8")[:2000], "size": f.stat().st_size})
    return out


@app.post("/api/llm/evolve")
async def llm_evolve(prompt: str = "innovative crypto futures strategy combining momentum and mean reversion", n: int = 3, user: dict = Depends(require_admin)):
    """يولد n استراتيجيات، يباك تست كل واحدة، ويضيف الفائزة (WR>=60%) تلقائياً — admin only: the cron secret must not
    choose what code gets generated and run"""
    _require_llm_lab()
    rate_limit(user["id"], "llm_evolve", 1, 600)
    prompt = prompt[:500]
    from app.llm_generator import generate_strategy, save_strategy, backtest_llm, auto_promote_if_winner
    results = []
    for i in range(min(n, 5)):
        gen = await generate_strategy(f"{prompt} — variation {i+1}")
        if not gen.get("ok"):
            results.append({"i": i+1, "ok": False, "error": gen.get("error")})
            continue
        code = gen["code"]
        from app.llm_sandbox import validate_code, UnsafeCode
        try: validate_code(code)
        except UnsafeCode as e:
            results.append({"i": i+1, "ok": False, "error": f"unsafe code refused: {e}"}); continue
        # Save
        try:
            fp = save_strategy(code)
            name = fp.stem
        except Exception as e:
            results.append({"i": i+1, "ok": False, "error": str(e)})
            continue
        # Backtest
        try:
            bt = await backtest_llm(code)
            if not bt.get("ok"):
                results.append({"i": i+1, "ok": True, "name": name, "backtest": bt, "promoted": False})
                continue
            stats = bt.get("stats", {})
            promo = await auto_promote_if_winner(code, name, stats)
            results.append({"i": i+1, "ok": True, "name": name, "code": code[:400], "stats": stats, "promoted": promo.get("promoted"), "reason": promo.get("reason","")})
        except Exception as e:
            results.append({"i": i+1, "ok": True, "name": name, "error": str(e)[:200]})
    promoted = [r for r in results if r.get("promoted")]
    # Telegram summary
    try:
        from app.telegram_bot import send_telegram
        await send_telegram(f"\U0001f916 LLM Evolve: {len(results)} generated, {len(promoted)} promoted (WR>=60%)")
    except: pass
    return {"results": results, "promoted": len(promoted), "total": len(results)}

# ── Real-orders bots (bot.py --live, one service per strategy on the admin's account: raqm-live@<strategy>): the
# admin turns each strategy on or off, sees its positions and can close one by hand. Each bot runs as another OS user
# and shares only its own folder RAQM_IPC_DIR/<strategy>: live_status.json out, commands/ in, results/ back.
# A request can only close — the bot ignores anything else, and drops requests older than 10 minutes.
IPC_DIR = Path(os.getenv("RAQM_IPC_DIR", "/opt/raqm-ipc"))
LIVE_SYMBOL_RE = re.compile(r"^[A-Z0-9]{1,20}/USDT(:USDT)?$")
# Keep in sync with bot.LIVE_READY_STRATEGIES (test_admin_live_strategies.py checks it)
LIVE_STRATEGIES = ("trend_daily", "vol_breakout", "rsi2_pullback", "trend_breakout", "listing_short", "momentum_ls", "ratio_trend")

class LiveCloseReq(BaseModel):
    strategy: str = Field(pattern=r"^[a-z0-9_]{1,30}$")
    symbol: str

class CapitalReq(BaseModel):
    env: str = Field(default="live", pattern=r"^(live|demo)$")
    capital_usdt: Optional[float] = Field(None, ge=0, le=100_000_000)     # 0 / None = no plan
    capital_reserve_pct: Optional[float] = Field(None, ge=0, le=90)
    capital_margin_pct: Optional[float] = Field(None, gt=0, le=50)
    capital_min_margin_usdt: Optional[float] = Field(None, ge=5, le=1_000_000)
    capital_margin_override_usdt: Optional[float] = Field(None, ge=0, le=10_000_000)   # 0 = back to the rule

def _ledger(env: str) -> Path:
    return (Path(os.getenv("RAQM_RISK_DIR_DEMO", "/opt/raqm-risk-demo")) / "risk_state.json") if env == "demo" else _risk_path()

class LiveStrategiesReq(BaseModel):
    env: str = Field(default="live", pattern=r"^(live|demo)$")
    account: str = Field(default="", max_length=120)
    strategies: List[str] = Field(max_length=len(LIVE_STRATEGIES))

# Demo (play money) bots keep their own risk ledger and Demo yes/no here; never a real-money bot's folder
DEMO_ACTIVATION_PATH = Path(os.getenv("RAQM_RISK_DIR_DEMO", "/opt/raqm-risk-demo")) / "live_activation.sqlite3"

def _live_strategy(name: str) -> str:
    if name not in LIVE_STRATEGIES: raise HTTPException(400, "unknown live strategy")
    return name

def _live_status_of(strategy: str) -> dict:
    f = IPC_DIR / strategy / "live_status.json"
    if not f.exists():
        return {"running": False}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        data["running"] = (datetime.now(timezone.utc) - datetime.fromisoformat(data["updated"])).total_seconds() < 300
        return data
    except Exception:
        return {"running": False, "error": "status unreadable"}


class LiveActivationReq(BaseModel):
    environment: str
    account: str = Field(min_length=1, max_length=120)
    strategies: List[str] = Field(min_length=1, max_length=20)
    # No readiness / risk_allocation here: readiness is derived from the server's trusted evidence document and the
    # allocation is split server-side. Accepting them from the request made both self-declared.

@app.get("/api/live/status")
async def live_status(user: dict = Depends(require_admin)):
    """Every live strategy's bot: running or not, its positions, history, entry block and review marks."""
    out = {s: _live_status_of(s) for s in LIVE_STRATEGIES}
    return {"running": any(v.get("running") for v in out.values()), "strategies": out}

from app import demo_measure

@app.get("/api/live/measurement")
async def live_measurement(user: dict = Depends(require_admin)):
    """The Demo measurement: each strategy's own closed Demo trades (RAQM_IPC_DIR/<strategy>/closed.json, written by
    the bot) against the backtest baseline (lib/demo-baseline.json), with its sample and status (app/demo_measure.py)."""
    closed = {}
    for s in LIVE_STRATEGIES:
        try:
            doc = json.loads((IPC_DIR / s / "closed.json").read_text(encoding="utf-8"))
            if doc.get("env") == "demo": closed[s] = doc.get("closed") or []
        except Exception:
            pass
    try:
        baseline = json.loads((BOT_DIR / "lib" / "demo-baseline.json").read_text(encoding="utf-8"))
    except Exception:
        baseline = None
    return {**demo_measure.measure(closed, baseline), "baseline_available": baseline is not None}


@app.get("/api/live/strategies")
async def live_strategies(env: str = "live", user: dict = Depends(require_admin)):
    """Which strategies may enter on the admin's account — real money (the active activation record) or Demo (the Demo
    yes/no) — and how each bot is."""
    if env not in ("live", "demo"): raise HTTPException(400, "env must be live or demo")
    if env == "demo":
        chosen = live_activation.demo_strategies(DEMO_ACTIVATION_PATH)
        record, on = None, set(LIVE_STRATEGIES if chosen is None else chosen)
    else:
        record = live_activation.active_record(LIVE_ACTIVATION_PATH)
        on = set((record or {}).get("strategies") or [])
    rows = []
    for s in LIVE_STRATEGIES:
        st = _live_status_of(s)
        rows.append({"id": s, "on": s in on, "running": st.get("running", False), "env": st.get("env"),
                     "positions": len(st.get("positions") or []), "entry_block": st.get("entry_block") or "",
                     "review": list((st.get("review") or {}).keys())})
    try:
        ledger = risk_manager.load_risk_state(_ledger(env))
        lim = ledger["limits"]
        plan = risk_manager.capital_plan(lim, ledger.get("equity_last"))
        capital = {"plan": plan, "limits_check": risk_manager.plan_vs_limits(lim, plan), "equity_last": ledger.get("equity_last"),
                   "open_trades": len(ledger.get("open_risk") or {}),
                   **{k: lim.get(k) for k in ("capital_usdt", "capital_reserve_pct", "capital_margin_pct", "capital_min_margin_usdt",
                                              "capital_margin_override_usdt", "risk_per_trade_pct", "max_aggregate_risk_pct")}}
    except Exception as e:
        capital = {"error": str(e)}
    return {"env": env, "enabled": live_trading_allowed() if env == "live" else True, "capital": capital,
            "account": (record or {}).get("account"), "record": record, "strategies": rows}


@app.post("/api/live/capital")
async def live_capital(req: CapitalReq, user: dict = Depends(require_admin)):
    """The owner's capital for an account: it sets the margin per trade and the most trades open at once, every strategy
    together (risk_manager.capital_plan). 0 = no plan. The bots and the risk gate read it before every entry."""
    patch = {k: v for k, v in req.model_dump().items() if k != "env" and v is not None}
    for k in ("capital_usdt", "capital_margin_override_usdt"):
        if patch.get(k) == 0: patch[k] = None
    limits = risk_manager.update_limits(_ledger(req.env), patch)
    admin_control.audit(BOT_DIR, str(user.get("email") or user.get("id")), "capital_plan", "ok", {"env": req.env, **patch})
    plan = risk_manager.capital_plan(limits, risk_manager.load_risk_state(_ledger(req.env)).get("equity_last"))
    return {"ok": True, "plan": plan, "limits_check": risk_manager.plan_vs_limits(limits, plan)}


@app.post("/api/live/strategies")
async def live_strategies_set(req: LiveStrategiesReq, user: dict = Depends(require_admin)):
    """Yes/no per strategy for the admin's live account: a new activation record with exactly these strategies (none =
    revoke). A strategy turned off stops entering; its open positions still exit on their own rules and stops."""
    for s in req.strategies: _live_strategy(s)
    actor = str(user.get("email") or user.get("id"))
    if req.env == "demo":   # play money: no approval workflow, no server switch
        live_activation.set_demo_strategies(DEMO_ACTIVATION_PATH, strategies=req.strategies, set_by=actor)
        admin_control.audit(BOT_DIR, actor, "demo_strategies", "ok", {"strategies": sorted(set(req.strategies))})
        return {"ok": True, "env": "demo", "strategies": sorted(set(req.strategies))}
    if not req.account.strip():
        raise HTTPException(422, "the live account name is required")
    if not req.strategies:
        live_activation.revoke(LIVE_ACTIVATION_PATH, reason=f"all live strategies turned off by {actor}")
        admin_control.audit(BOT_DIR, actor, "live_strategies", "ok", {"strategies": []})
        return {"ok": True, "strategies": []}
    chosen = sorted(set(req.strategies))
    try:
        aid = live_activation.activate(LIVE_ACTIVATION_PATH, environment="live", account=req.account, approved_by=actor,
                                       strategies=chosen,
                                       readiness_evidence=_safe_json_file(BOT_DIR / "readiness_evidence.json") or {},
                                       expected_reviewed_commit_sha=_trusted_readiness_commit())
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    admin_control.audit(BOT_DIR, actor, "live_strategies", "ok", {"account": req.account, "strategies": chosen})
    return {"ok": True, "activation_id": aid, "strategies": chosen}


@app.get("/api/live/activation")
async def live_activation_status(user: dict = Depends(require_admin)):
    record = live_activation.active_record(LIVE_ACTIVATION_PATH)
    return {"enabled": live_trading_allowed(), "active": bool(record), "record": record}


@app.post("/api/live/activation")
async def live_activation_create(req: LiveActivationReq, user: dict = Depends(require_admin)):
    if req.environment != "live":
        raise HTTPException(400, "activation requires the explicit live environment")
    if not all(re.fullmatch(r"[a-z0-9_]{1,30}", s) for s in req.strategies):
        raise HTTPException(400, "bad strategy name")
    try:
        aid = live_activation.activate(LIVE_ACTIVATION_PATH, environment=req.environment, account=req.account,
            approved_by=str(user.get("email") or user.get("id")), strategies=req.strategies,
            readiness_evidence=_safe_json_file(BOT_DIR / "readiness_evidence.json") or {},
            expected_reviewed_commit_sha=_trusted_readiness_commit())
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {"ok": True, "activation_id": aid, "approved_by": user.get("email") or user.get("id")}


@app.post("/api/live/activation/revoke")
async def live_activation_revoke(user: dict = Depends(require_admin)):
    live_activation.revoke(LIVE_ACTIVATION_PATH, reason=f"revoked by {user.get('email') or user.get('id')}")
    return {"ok": True}

@app.post("/api/live/close")
async def live_close(req: LiveCloseReq, user: dict = Depends(require_admin)):
    rate_limit(user["id"], "live_close", 10, 60)
    strategy = _live_strategy(req.strategy)
    sym = req.symbol.strip().upper()
    if not LIVE_SYMBOL_RE.match(sym):
        raise HTTPException(400, "bad symbol")
    st = _live_status_of(strategy)
    if not st.get("running"):
        raise HTTPException(409, "this strategy's real-orders bot isn't running — close it in Binance")
    if sym.split(":")[0] not in {p["symbol"] for p in st.get("positions", [])}:
        raise HTTPException(404, "no open position on that coin")
    rid = uuid.uuid4().hex
    cmd = {"id": rid, "symbol": sym, "at_epoch": _time.time(), "by": user.get("email")}
    _drop_request(IPC_DIR / strategy / "commands", IPC_DIR, rid, cmd)
    try:
        from app.telegram_bot import send_telegram
        await send_telegram(f"🖐️ manual close requested from the site: {strategy} {sym} ({user.get('email')})")
    except Exception: pass
    return {"ok": True, "id": rid}

@app.get("/api/live/close/{strategy}/{rid}")
async def live_close_result(strategy: str, rid: str, user: dict = Depends(require_admin)):
    d = IPC_DIR / _live_strategy(strategy)
    if not re.fullmatch(r"[0-9a-f]{32}", rid):
        raise HTTPException(400, "bad id")
    f = d / "results" / f"{rid}.json"
    if not f.exists():
        pending = (d / "commands" / f"close-{rid}.json").exists()
        return {"done": False, "pending": pending}
    return {"done": True, **json.loads(f.read_text(encoding="utf-8"))}

@app.get("/api/llm/promoted")
async def llm_promoted(user: dict = Depends(require_admin)):
    from pathlib import Path as _P
    import json as _js
    reg = _P(__file__).parent.parent / "strategies_llm" / "registry.json"
    if not reg.exists():
        return []
    try: return _js.loads(reg.read_text(encoding="utf-8"))
    except: return []


# ── Admin Control Center: authenticated, persistent, paper-only controls
class AdminModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

class StrategyPatch(AdminModel):
    enabled: Optional[bool] = None
    timeframe: Optional[str] = Field(None, pattern=r"^(1m|5m|15m|30m|1h|2h|4h|1d)$")
    symbols: Optional[List[str]] = Field(None, max_length=30)

class LifecycleReq(AdminModel):
    action: str = Field(pattern=r"^(start|stop|pause|resume)$")
    confirm: bool = False

class PauseReq(AdminModel):
    paused: bool
    reason: Optional[str] = Field(None, max_length=240)
    confirm: bool = False

class RiskLimitsReq(AdminModel):
    risk_per_trade_pct: Optional[float] = Field(None, ge=0, le=100)
    max_aggregate_risk_pct: Optional[float] = Field(None, ge=0, le=100)
    max_correlated_risk_pct: Optional[float] = Field(None, ge=0, le=100)
    max_daily_loss_pct: Optional[float] = Field(None, ge=0, le=100)
    max_drawdown_pct: Optional[float] = Field(None, ge=0, le=100)
    leverage: Optional[int] = Field(None, ge=1, le=20)
    margin_mode: Optional[str] = Field(None, pattern=r"^(isolated|cross)$")

class KillSwitchReq(AdminModel):
    action: str = Field(pattern=r"^(trip|reset)$")
    reason: Optional[str] = Field(None, min_length=3, max_length=240)
    confirm: bool = False

async def _admin_actor(user): return str(user.get("email") or user.get("id") or "admin")
def _risk_path(): return risk_manager.ledger_dir(BOT_DIR) / "risk_state.json"   # shared with the live bot (RAQM_RISK_DIR)
def _safe_json_file(path):
    try: return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except Exception: return None

def _trusted_readiness_commit():
    """Deployment-provided exact commit binding; missing or malformed means readiness fails closed."""
    value = os.getenv("READINESS_EXPECTED_COMMIT_SHA", "").strip().lower()
    return value if re.fullmatch(r"[0-9a-f]{40}", value) else None

def _health_snapshot():
    cfg=_safe_json_file(BOT_DIR / "api_bot_config.json") or {}
    return {"api":"healthy", "paper_bot":"healthy" if bot_task and not bot_task.done() else "stopped", "live_trading":"locked" if not live_trading_allowed() else "requires_activation", "config":"available" if cfg else "unavailable"}

@app.get("/api/admin/overview")
async def admin_overview(user: dict = Depends(require_admin)):
    rate_limit(user["id"], "admin_overview", 30, 60)
    st=admin_control.read_state(BOT_DIR); risk=risk_manager.load_risk_state(_risk_path())
    async with async_session() as sess:
        trades=(await sess.execute(select(Trade))).scalars().all()
    live_feed = await live_bots_feed.fetch_all()
    live_summary = live_bots_feed.aggregate_summary(live_feed)
    return {"ok":True,"mode":"paper","strategies":len(admin_control.STRATEGIES),"running":bool(bot_task and not bot_task.done()),"entry_paused":st["entry_paused"],"kill_switch":risk["kill_switch"],
            "paper":{"open":sum(t.status=="open" for t in trades),"trades":len(trades),"pnl":round(sum(t.pnl or 0 for t in trades),2)},
            "health":_health_snapshot(),"live_enabled":live_trading_allowed(),
            # Real VPS paper bots (7 standalone systemd services) — separate from the dashboard-managed "paper" block above.
            "live_bots":{"label":"VPS live paper bots","base_url":live_bots_feed.base_url(),"lifecycle_control_available":False,
                         "lifecycle_note":live_bots_feed.LIFECYCLE_CONTROL_NOTE,"summary":live_summary}}

@app.get("/api/admin/strategies")
async def admin_strategies(user: dict = Depends(require_admin)):
    st=admin_control.read_state(BOT_DIR)
    live_feed = await live_bots_feed.fetch_all()
    out=[]
    for s in admin_control.STRATEGIES:
        live = live_feed.get(s) or live_bots_feed.no_service_entry(s)
        out.append({"id":s,"name":s,"status":"enabled" if st["strategies"][s]["enabled"] else "disabled","mode":"paper",
                    "config":st["strategies"][s],"runtime":admin_control.get_runtime(BOT_DIR,s),"lifecycle":admin_control.get_runtime(BOT_DIR,s)["status"],
                    # Real VPS bot status for this strategy id (read-only; no start/stop control here — see live.lifecycle_control_available).
                    "live":{"status":live["status"],"updated":live["updated"],"age_seconds":live["age_seconds"],"mode":live["mode"],
                             "stats":live["stats"],"open_positions":len(live["positions"]),"lifecycle_control_available":False}})
    return out

@app.patch("/api/admin/strategies/{strategy}")
async def admin_strategy(strategy: str, req: StrategyPatch, user: dict = Depends(require_admin)):
    rate_limit(user["id"], "admin_mutation", 30, 60)
    patch={k:v for k,v in req.model_dump().items() if v is not None}
    if req.symbols is not None and not all(SYMBOL_RE.match(s.upper()) for s in req.symbols): raise HTTPException(422,"bad symbol")
    try: result=admin_control.update_strategy(BOT_DIR,strategy,patch,await _admin_actor(user))
    except KeyError: raise HTTPException(404,"unknown strategy")
    return {"ok":True,"strategy":strategy,"config":result}

@app.post("/api/admin/strategies/{strategy}/lifecycle")
async def admin_strategy_lifecycle(strategy: str, req: LifecycleReq, user: dict = Depends(require_admin)):
    rate_limit(user["id"], "admin_mutation", 30, 60)
    if strategy not in admin_control.STRATEGIES: raise HTTPException(404,"unknown strategy")
    if req.action in ("start","stop") and not req.confirm: raise HTTPException(400,"confirmation required")
    action_at = admin_control.now()
    admin_control.invalidate_runtime(BOT_DIR, strategy)
    result=admin_control.set_strategy_lifecycle(BOT_DIR,strategy,req.action,await _admin_actor(user))
    active = req.action in ("start", "resume")
    _wake_managed_loop()
    if active:
        _ensure_managed_loop()
    elif bot_task is None or bot_task.done():
        admin_control.mark_runtime(BOT_DIR, strategy, status="paused" if req.action == "pause" else "stopped")
    runtime = await _wait_strategy_runtime(strategy, active=active, expected_task_id=_bot_task_id, action_at=action_at)
    running = active and runtime["status"] == "running" and runtime.get("task_id") == _bot_task_id and bool(runtime.get("heartbeat"))
    return {"ok":True,"strategy":strategy,"action":req.action,"config":result,"runtime":runtime,"running":running}

@app.get("/api/admin/paper/portfolio")
async def admin_paper_portfolio(user: dict = Depends(require_admin)):
    async with async_session() as sess:
        rows=(await sess.execute(select(Trade).order_by(desc(Trade.id)).limit(200))).scalars().all()
    dashboard_positions=[{"id":t.id,"symbol":t.symbol,"side":t.side,"entry":t.entry,"qty":t.qty,"sl":t.sl,"tp":t.tp,"pnl":t.pnl,"status":t.status} for t in rows if t.status=="open"]
    dashboard_history=[{"id":t.id,"symbol":t.symbol,"side":t.side,"entry":t.entry,"exit":t.exit,"pnl":t.pnl,"status":t.status,"entry_ts":t.entry_ts,"exit_ts":t.exit_ts} for t in rows]
    live_feed = await live_bots_feed.fetch_all()
    live_strategies = {sid: {"status":e["status"],"updated":e["updated"],"age_seconds":e["age_seconds"],"mode":e["mode"],
                              "stats":e["stats"],"positions":e["positions"],"history":e["history"],"extra":e["extra"],"error":e["error"]}
                       for sid, e in live_feed.items()}
    # Back-compat: top-level "positions"/"history" keep meaning the dashboard-managed bot, unchanged for existing callers.
    return {"mode":"paper","positions":dashboard_positions,"history":dashboard_history,
            "dashboard_bot":{"label":"Dashboard-managed paper bot (SQL Trade table / bot_loop) — distinct from the VPS live bots below",
                              "positions":dashboard_positions,"history":dashboard_history},
            "live_bots":{"label":"VPS live paper bots (7 standalone systemd services, read-only public status files)",
                         "base_url":live_bots_feed.base_url(),"lifecycle_control_available":False,
                         "lifecycle_note":live_bots_feed.LIFECYCLE_CONTROL_NOTE,
                         "aggregate":live_bots_feed.aggregate_summary(live_feed),"strategies":live_strategies}}

@app.get("/api/admin/risk")
async def admin_risk(user: dict = Depends(require_admin)):
    st=risk_manager.load_risk_state(_risk_path()); return {"available":True,"state":st}

@app.patch("/api/admin/risk/limits")
async def admin_risk_limits(req: RiskLimitsReq, user: dict = Depends(require_admin)):
    rate_limit(user["id"], "admin_mutation", 30, 60)
    patch={k:v for k,v in req.model_dump().items() if v is not None}; limits=risk_manager.update_limits(_risk_path(),patch); admin_control.audit(BOT_DIR,await _admin_actor(user),"risk_limits_update","ok",patch); return {"ok":True,"limits":limits}

@app.post("/api/admin/risk/kill-switch")
async def admin_kill_switch(req: KillSwitchReq, user: dict = Depends(require_admin)):
    rate_limit(user["id"], "admin_mutation", 30, 60)
    if not req.confirm: raise HTTPException(400,"confirmation required")
    actor=await _admin_actor(user)
    if req.action=="trip": risk_manager.trip_kill_switch(_risk_path(),req.reason or "manual operator trip",by=actor)
    else: risk_manager.reset_kill_switch(_risk_path(),operator=actor)
    admin_control.audit_kill(BOT_DIR,actor,"kill_switch_"+req.action,"ok",{"reason":req.reason})
    return {"ok":True,"state":risk_manager.load_risk_state(_risk_path())["kill_switch"]}

@app.post("/api/admin/controls/entry-pause")
async def admin_entry_pause(req: PauseReq, user: dict = Depends(require_admin)):
    rate_limit(user["id"], "admin_mutation", 30, 60)
    if not req.confirm: raise HTTPException(400,"confirmation required")
    return {"ok":True,"entry_pause":admin_control.set_entry_pause(BOT_DIR,req.paused,await _admin_actor(user),req.reason)}

@app.get("/api/admin/recovery")
async def admin_recovery(user: dict = Depends(require_admin)):
    st=risk_manager.load_risk_state(_risk_path()); dash=_safe_json_file(BOT_DIR/"dashboard-data.json") or {}; state=dash.get("state") or {}
    return {"available":True,"recovery_required":state.get("recovery_required",{}),"reconciliation":state.get("_reconcile",{}),"risk_reservations":st.get("open_risk",{})}

@app.get("/api/admin/health")
async def admin_health(user: dict = Depends(require_admin)):
    return {"available":True,"at":datetime.now(timezone.utc).isoformat(),"components":_health_snapshot()}

class UserBanReq(AdminModel):
    banned: bool
    confirm: bool = False

class UserSettingsPatch(AdminModel):
    """Admin-only edit of a user's LOCAL per-user bot allocation (user_settings table).

    This never touches the 7 shared VPS paper bots (systemd services, unrelated to any
    single user) — it only edits the row this dashboard already reads/writes for that user.
    """
    capital: Optional[float] = Field(None, ge=0, le=10_000_000)
    strategy: Optional[str] = None
    confirm: bool = False

@app.get("/api/admin/users")
async def admin_users_list(user: dict = Depends(require_admin)):
    """Users & Plans tab: Supabase account identity + plan tier + local per-user bot settings,
    merged read-only. Supabase being unreachable degrades to available=False — never fabricated."""
    rate_limit(user["id"], "admin_users", 20, 60)
    gotrue = await admin_users.fetch_gotrue_users()
    tiers = await admin_users.fetch_profile_tiers()
    async with async_session() as sess:
        rows = (await sess.execute(select(UserSetting))).scalars().all()
    local = {r.user_id: {"capital": r.capital, "strategy": r.strategy, "started_at": r.started_at, "updated_at": r.updated_at} for r in rows}
    merged = admin_users.merge_users(gotrue, tiers, local)
    grants, at = await _grants(), pi.now()
    for u in merged["users"]:
        g = grants.get(u["id"])
        u["gift_tier"] = pi.active_grant_tier(g, at)
        u["gift_expires_at"] = g["expires_at"] if u["gift_tier"] else None
    return merged

@app.post("/api/admin/users/{target_user_id}/ban")
async def admin_user_ban(target_user_id: str, req: UserBanReq, user: dict = Depends(require_admin)):
    """Ban/unban a Supabase account (GoTrue admin ban_duration). Local per-user settings/tier are untouched."""
    rate_limit(user["id"], "admin_mutation", 30, 60)
    if not req.confirm: raise HTTPException(400, "confirmation required")
    actor = await _admin_actor(user)
    result = await admin_users.set_user_ban(target_user_id, req.banned)
    admin_control.audit(BOT_DIR, actor, "user_ban" if req.banned else "user_unban",
                         "ok" if result.get("ok") else "failed", {"target_user_id": target_user_id})
    if not result.get("ok"):
        raise HTTPException(502, result.get("error") or "ban update failed")
    return {"ok": True, "user_id": target_user_id, "banned": req.banned}


@app.patch("/api/admin/users/{target_user_id}/settings")
async def admin_user_settings_patch(target_user_id: str, req: UserSettingsPatch, user: dict = Depends(require_admin)):
    """Admin edit of ONE user's allocated capital and/or active strategy in the local
    user_settings table (per-user bot allocation). This is NOT the 7 shared VPS paper
    bots (systemd services unrelated to individual users) — no real bot is started,
    stopped, or reconfigured by this endpoint."""
    rate_limit(user["id"], "admin_mutation", 30, 60)
    if not req.confirm: raise HTTPException(400, "confirmation required")
    if req.capital is None and req.strategy is None:
        raise HTTPException(400, "nothing to update — provide capital and/or strategy")
    if req.strategy is not None and req.strategy not in STRATEGY_ORDER:
        raise HTTPException(400, f"unknown strategy — must be one of {STRATEGY_ORDER}")
    actor = await _admin_actor(user)
    now_iso = datetime.now(timezone.utc).isoformat()
    async with async_session() as sess:
        row = (await sess.execute(select(UserSetting).where(UserSetting.user_id == target_user_id))).scalar_one_or_none()
        if row is None:
            row = UserSetting(user_id=target_user_id, started_at=now_iso)
            sess.add(row)
        if req.capital is not None: row.capital = req.capital
        if req.strategy is not None: row.strategy = req.strategy
        row.updated_at = now_iso
        await sess.commit()
        result = {"capital": row.capital, "strategy": row.strategy, "updated_at": row.updated_at}
    admin_control.audit(BOT_DIR, actor, "user_settings_update", "ok",
                         {"target_user_id": target_user_id, "capital": req.capital, "strategy": req.strategy})
    return {"ok": True, "user_id": target_user_id, **result}


@app.get("/api/admin/finance")
async def admin_finance(user: dict = Depends(require_admin)):
    """المالية (Finance) tab: MRR + per-tier revenue computed purely from plan_counts x
    admin_users.TIER_PRICES_USD (mirrors lib/strategies.ts TIERS.price). No Stripe/network
    calls — degrades to available=False (never a fabricated number) if Supabase/GoTrue is
    unreachable, same as /api/admin/users."""
    rate_limit(user["id"], "admin_users", 20, 60)
    gotrue = await admin_users.fetch_gotrue_users()
    tiers = await admin_users.fetch_profile_tiers()
    async with async_session() as sess:
        rows = (await sess.execute(select(UserSetting))).scalars().all()
    local = {r.user_id: {"capital": r.capital, "strategy": r.strategy, "started_at": r.started_at, "updated_at": r.updated_at} for r in rows}
    merged = admin_users.merge_users(gotrue, tiers, local)
    prices = pi.effective_prices(await _saved_prices())
    finance = admin_users.compute_finance_summary(merged["plan_counts"], prices)
    return {"available": merged["available"], "error": merged["error"], "plan_counts": merged["plan_counts"], "finance": finance, "prices": prices}



# ── Plan prices and invitations (app/plans_invites.py has the rules)
async def _saved_prices() -> dict[str, int]:
    async with async_session() as sess:
        rows = (await sess.execute(select(PlanPrice))).scalars().all()
    return {r.tier: r.price_usd for r in rows}

async def _grants() -> dict[str, dict]:
    async with async_session() as sess:
        rows = (await sess.execute(select(PlanGrant))).scalars().all()
    return {r.user_id: {"tier": r.tier, "expires_at": r.expires_at, "email": r.email, "invite_id": r.invite_id,
                        "granted_at": r.granted_at} for r in rows}

@app.get("/api/plans")
async def plans_public():
    """Every plan's current monthly price (USD) — the pricing page and the Stripe checkout read this."""
    return {"currency": "usd", "prices": pi.effective_prices(await _saved_prices())}

@app.get("/api/admin/plans")
async def admin_plans(user: dict = Depends(require_admin)):
    async with async_session() as sess:
        rows = (await sess.execute(select(PlanPrice))).scalars().all()
    saved = {r.tier: r.price_usd for r in rows}
    return {"prices": pi.effective_prices(saved), "defaults": dict(admin_users.TIER_PRICES_USD),
            "changed": {r.tier: {"price_usd": r.price_usd, "updated_at": r.updated_at, "updated_by": r.updated_by} for r in rows}}

class PlanPricesReq(AdminModel):
    prices: dict
    confirm: bool = False

@app.post("/api/admin/plans")
async def admin_plans_set(req: PlanPricesReq, user: dict = Depends(require_admin)):
    """Change paid plans' monthly prices. New checkouts charge them; existing Stripe subscribers keep their price."""
    rate_limit(user["id"], "admin_mutation", 30, 60)
    if not req.confirm: raise HTTPException(400, "confirmation required")
    try: patch = pi.validate_prices(req.prices)
    except ValueError as e: raise HTTPException(400, str(e))
    actor, at = await _admin_actor(user), pi.iso(pi.now())
    async with async_session() as sess:
        for tier, price in patch.items():
            row = await sess.get(PlanPrice, tier)
            if row is None: sess.add(PlanPrice(tier=tier, price_usd=price, updated_at=at, updated_by=actor))
            else: row.price_usd, row.updated_at, row.updated_by = price, at, actor
        await sess.commit()
    admin_control.audit(BOT_DIR, actor, "plan_prices", "ok", patch)
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

@app.get("/api/admin/invites")
async def admin_invites(user: dict = Depends(require_admin)):
    rate_limit(user["id"], "admin_users", 20, 60)
    prices = pi.effective_prices(await _saved_prices())
    gotrue = await admin_users.fetch_gotrue_users()
    tiers = await admin_users.fetch_profile_tiers()
    by_email = {pi.normalize_email(u.get("email")): tiers.get("tiers", {}).get(u.get("id")) or "free"
                for u in gotrue.get("users", []) if u.get("email")}
    async with async_session() as sess:
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

@app.post("/api/admin/invites")
async def admin_invite_create(req: InviteReq, user: dict = Depends(require_admin)):
    rate_limit(user["id"], "admin_mutation", 30, 60)
    if not req.confirm: raise HTTPException(400, "confirmation required")
    email = pi.normalize_email(req.email)
    if not pi.valid_email(email): raise HTTPException(400, "invalid email")
    if req.tier not in pi.PAID_TIERS: raise HTTPException(400, f"tier must be one of {pi.PAID_TIERS}")
    if req.kind not in pi.KINDS: raise HTTPException(400, f"kind must be one of {pi.KINDS}")
    if req.kind in ("gift", "trial") and not req.days: raise HTTPException(400, "days required for a gift or a trial")
    at = pi.now()
    async with async_session() as sess:
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
        async with async_session() as sess:
            row = await sess.get(Invitation, inv.id)
            if sent["ok"]: row.emailed_at = pi.iso(pi.now())
            row.email_error = sent["error"]
            await sess.commit()
            inv = row
    admin_control.audit(BOT_DIR, inv.created_by, "invite_create", "ok",
                         {"invite": inv.id[:6], "email": email, "tier": req.tier, "kind": req.kind, "days": inv.days, "emailed": sent["ok"]})
    return {"ok": True, "invite": _invite_out(inv, prices), "emailed": sent["ok"], "email_error": sent["error"]}

class InviteActionReq(AdminModel):
    confirm: bool = False

@app.post("/api/admin/invites/{invite_id}/revoke")
async def admin_invite_revoke(invite_id: str, req: InviteActionReq, user: dict = Depends(require_admin)):
    rate_limit(user["id"], "admin_mutation", 30, 60)
    if not req.confirm: raise HTTPException(400, "confirmation required")
    async with async_session() as sess:
        inv = await sess.get(Invitation, invite_id)
        if inv is None: raise HTTPException(404, "invitation not found")
        if inv.status != "pending": raise HTTPException(409, f"invitation is {inv.status}")
        inv.status = "revoked"
        await sess.commit()
    admin_control.audit(BOT_DIR, await _admin_actor(user), "invite_revoke", "ok", {"invite": invite_id[:6], "email": inv.email})
    return {"ok": True}

@app.post("/api/admin/invites/{invite_id}/resend")
async def admin_invite_resend(invite_id: str, req: InviteActionReq, user: dict = Depends(require_admin)):
    """Email the invitation again; the link gets a fresh LINK_DAYS."""
    rate_limit(user["id"], "admin_mutation", 30, 60)
    if not req.confirm: raise HTTPException(400, "confirmation required")
    async with async_session() as sess:
        inv = await sess.get(Invitation, invite_id)
        if inv is None: raise HTTPException(404, "invitation not found")
        if inv.status != "pending": raise HTTPException(409, f"invitation is {inv.status}")
        inv.link_expires_at = pi.iso(pi.now() + pi.timedelta(days=pi.LINK_DAYS))
        await sess.commit()
    prices = pi.effective_prices(await _saved_prices())
    sent = await _email_invite(inv, prices)
    async with async_session() as sess:
        row = await sess.get(Invitation, invite_id)
        if sent["ok"]: row.emailed_at = pi.iso(pi.now())
        row.email_error = sent["error"]
        await sess.commit()
    admin_control.audit(BOT_DIR, await _admin_actor(user), "invite_resend", "ok" if sent["ok"] else "failed", {"invite": invite_id[:6], "email": inv.email})
    return {"ok": True, "emailed": sent["ok"], "email_error": sent["error"]}

@app.post("/api/admin/grants/{target_user_id}/end")
async def admin_grant_end(target_user_id: str, req: InviteActionReq, user: dict = Depends(require_admin)):
    """End a gift now: the user is back on their paid plan (or free)."""
    rate_limit(user["id"], "admin_mutation", 30, 60)
    if not req.confirm: raise HTTPException(400, "confirmation required")
    async with async_session() as sess:
        g = await sess.get(PlanGrant, target_user_id)
        if g is None: raise HTTPException(404, "no gift for this user")
        g.expires_at = pi.iso(pi.now())
        await sess.commit()
    _tier_cache.pop(target_user_id, None)
    admin_control.audit(BOT_DIR, await _admin_actor(user), "gift_end", "ok", {"target_user_id": target_user_id})
    return {"ok": True}

async def _load_invite(invite_id: str) -> Invitation:
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", invite_id or ""): raise HTTPException(404, "invitation not found")
    async with async_session() as sess:
        inv = await sess.get(Invitation, invite_id)
    if inv is None: raise HTTPException(404, "invitation not found")
    return inv

@app.get("/api/invites/{invite_id}")
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

@app.post("/api/invites/{invite_id}/accept")
async def invite_accept(invite_id: str, user: dict = Depends(require_user)):
    """Take a gift invitation: the plan for its days, on top of the paid plan (the higher one counts)."""
    rate_limit(user["id"], "invite_accept", 10, 60)
    inv = await _load_invite(invite_id)
    _check_invitee(inv, user)
    if inv.kind != "gift": raise HTTPException(400, "this invitation is taken through checkout")
    at = pi.now()
    async with async_session() as sess:
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
    _tier_cache.pop(user["id"], None)
    admin_control.audit(BOT_DIR, inv.email, "invite_accept", "ok", {"invite": inv.id[:6], "tier": tier, "until": pi.iso(end)})
    return {"ok": True, "kind": "gift", "tier": tier, "expires_at": pi.iso(end)}

@app.post("/api/invites/{invite_id}/checkout")
async def invite_checkout_terms(invite_id: str, user: dict = Depends(require_user)):
    """For the Stripe checkout route: the plan, price and free days of a trial/paid invitation, for its invitee only."""
    rate_limit(user["id"], "invite_accept", 10, 60)
    inv = await _load_invite(invite_id)
    _check_invitee(inv, user)
    if inv.kind not in ("trial", "paid"): raise HTTPException(400, "a gift needs no checkout")
    if pi.TIER_RANK.get(await _paid_tier(user), 0) >= pi.TIER_RANK.get(inv.tier, 0):
        async with async_session() as sess:
            row = await sess.get(Invitation, invite_id)
            row.status, row.accepted_at, row.accepted_user_id = "accepted", pi.iso(pi.now()), user["id"]
            await sess.commit()
        raise HTTPException(409, "you already have this plan or a higher one")
    async with async_session() as sess:
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
                async with async_session() as sess:
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

@app.get("/api/admin/readiness")
async def admin_readiness(user: dict = Depends(require_admin)):
    from app.testnet_readiness import build_admin_readiness
    risk_readable = True
    try:
        risk = risk_manager.load_risk_state(_risk_path())
        kill_clear = not bool((risk.get("kill_switch") or {}).get("tripped"))
    except Exception:
        risk_readable = False
        kill_clear = False
    evidence = _safe_json_file(BOT_DIR / "readiness_evidence.json") or {}
    result = build_admin_readiness(strategies=list(admin_control.STRATEGIES), evidence=evidence,
                                   live_locked=not live_trading_allowed(), environment=os.getenv("BINANCE_ENV", ""),
                                   expected_reviewed_commit_sha=_trusted_readiness_commit())
    result.update({"environment":"testnet" if os.getenv("BINANCE_ENV")=="testnet" else "unavailable", "checks":{"server_live_flag_locked":not live_trading_allowed(), "risk_ledger_readable":risk_readable, "kill_switch_clear":kill_clear}})
    result["testnet_ready"] = result["testnet_ready"] and risk_readable and kill_clear
    result["live_ready"] = result["live_ready"] and risk_readable and kill_clear
    if not risk_readable or not kill_clear:
        for row in result["strategies"].values():
            row["testnet_ready"] = False
            row["live_ready"] = False
            row["reasons"].append("risk ledger unavailable or kill switch is tripped")
            row["status"] = "paper-ready" if row["paper_ready"] else "not-ready"
    result["ready"] = result["paper_ready"]
    return result

@app.get("/api/admin/activation")
async def admin_activation(user: dict = Depends(require_admin)):
    return {"enabled":live_trading_allowed(),"active":bool(live_activation.active_record(LIVE_ACTIVATION_PATH)),"creation_from_ui":False,"record":live_activation.active_record(LIVE_ACTIVATION_PATH)}

@app.get("/api/admin/audit")
async def admin_audit(limit: int=100, user: dict = Depends(require_admin)):
    return {"items":admin_control.list_audit(BOT_DIR,max(1,min(limit,200)))}

# ── Keys Vault — Multi-Exchange (encrypted, never expose secrets)
from pydantic import BaseModel as _BM2

class SaveKeyReq(_BM2):
    exchange: str
    apiKey: str
    secret: str
    passphrase: str = ""

@app.get("/api/keys/status")
async def keys_status(user: dict = Depends(require_admin)):
    from app.keys_vault import load_all_status
    return load_all_status()

@app.post("/api/keys/save")
async def keys_save(req: SaveKeyReq, user: dict = Depends(require_admin)):
    from app.keys_vault import save_keys
    try:
        save_keys(req.exchange.lower().strip(), req.apiKey.strip(), req.secret.strip(), req.passphrase.strip())
        return {"ok": True}
    except Exception as e:
        raise HTTPException(400, str(e))

@app.post("/api/keys/delete")
async def keys_delete(exchange: str = "", body: dict = None, user: dict = Depends(require_admin)):
    from app.keys_vault import delete_keys
    ex = (body or {}).get("exchange") or exchange
    ex = str(ex).lower().strip()
    if not ex: raise HTTPException(400, "exchange required")
    ok = delete_keys(ex)
    return {"ok": bool(ok)}

@app.post("/api/keys/paper")
async def keys_paper(body: dict, user: dict = Depends(require_admin)):
    from app.keys_vault import set_paper
    ex = str(body.get("exchange","")).lower().strip()
    paper = body.get("paper", True) is not False  # only an explicit false switches to LIVE
    if not ex: raise HTTPException(400, "exchange required")
    if not paper and not live_trading_allowed():
        raise HTTPException(400, "LIVE disabled — set ALLOW_LIVE_TRADING=true on the backend first")
    ok = set_paper(ex, paper)
    return {"ok": bool(ok), "paper": paper}

@app.get("/api/keys/live")
async def keys_live(user: dict = Depends(require_admin)):
    """Which exchanges are LIVE (for bot)"""
    from app.keys_vault import get_exchanges_for_trading
    return {"live": get_exchanges_for_trading()}

# ── Per-user Keys Vault + Live Enable — any registered user, own account only.
# Separate from the admin-only /api/keys/* and /api/admin/* paths above, which are
# untouched. Every endpoint here is scoped by the authenticated user's own id
# (Depends(require_user)) — never by an id supplied in the request body — so a user
# can only ever read/write their own key and their own live-enable record.
USER_LIVE_ACTIVATION_PATH = BOT_DIR / "user_live_activation.sqlite3"

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
    environment: str = "live"      # "demo": Binance Demo (play money), allowed while the server's real-money switch is off

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

class UserBotCloseReq(_BM2):
    strategy: str = Field(pattern=r"^[a-z0-9_]{1,30}$")
    symbol: str

@app.get("/api/user/keys/status")
async def user_keys_status(user: dict = Depends(require_user)):
    from app.user_keys_vault import user_key_status
    return user_key_status(user["id"])

@app.post("/api/user/keys/save")
async def user_keys_save(req: UserSaveKeyReq, user: dict = Depends(require_user)):
    _require_confirmed(user)
    from app.user_keys_vault import save_user_keys
    try:
        save_user_keys(user["id"], req.exchange.lower().strip(), req.apiKey.strip(), req.secret.strip(), req.passphrase.strip())
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))

@app.post("/api/user/keys/delete")
async def user_keys_delete(body: dict, user: dict = Depends(require_user)):
    from app.user_keys_vault import delete_user_keys
    ex = str((body or {}).get("exchange", "")).lower().strip()
    if not ex:
        raise HTTPException(400, "exchange required")
    ok = delete_user_keys(user["id"], ex)
    return {"ok": bool(ok)}

@app.get("/api/user/live/status")
async def user_live_status(user: dict = Depends(require_user)):
    from app.user_live_activation import get_user_live_record
    rec = get_user_live_record(USER_LIVE_ACTIVATION_PATH, user_id=user["id"])
    if not rec:
        return {"enabled": False}
    return {"enabled": bool(rec["enabled"]), "exchange": rec["exchange"], "leverage": rec["leverage"],
            "risk_per_trade_pct": rec["risk_per_trade_pct"], "max_aggregate_risk_pct": rec["max_aggregate_risk_pct"],
            "consented_at": rec["consented_at"], "environment": rec.get("environment") or "live"}

@app.post("/api/user/live/enable")
async def user_live_enable(req: UserLiveEnableReq, request: Request, user: dict = Depends(require_user)):
    _require_confirmed(user)
    if req.environment not in ("demo", "live"):
        raise HTTPException(400, "environment must be demo or live")
    # real money obeys the server's switch like everything else; a Demo consent trades play money only
    if req.environment == "live" and not live_trading_allowed():
        raise HTTPException(403, "live trading is off on this server")
    from app.user_keys_vault import has_live_configured_keys
    from app.user_live_activation import enable_user_live
    ex = req.exchange.lower().strip()
    if not has_live_configured_keys(user["id"], ex):
        raise HTTPException(400, f"save your {ex} API key first — live cannot be enabled without your own keys")
    try:
        enable_user_live(USER_LIVE_ACTIVATION_PATH, user_id=user["id"], exchange=ex, confirm=req.confirm,
                          actor=str(user.get("email") or user["id"]), ip=(request.client.host if request.client else None),
                          leverage=req.leverage, risk_per_trade_pct=req.risk_per_trade_pct,
                          max_aggregate_risk_pct=req.max_aggregate_risk_pct, environment=req.environment)
    except (PermissionError, ValueError) as e:
        raise HTTPException(400, str(e))
    if req.environment == "live":          # a Demo consent leaves the keys marked as they were
        from app.user_keys_vault import set_user_paper
        set_user_paper(user["id"], ex, False)  # the per-user vault entry itself switches to LIVE too
    return {"ok": True}

@app.post("/api/user/live/disable")
async def user_live_disable(user: dict = Depends(require_user)):
    from app.user_live_activation import disable_user_live
    disable_user_live(USER_LIVE_ACTIVATION_PATH, user_id=user["id"], reason="user disabled")
    return {"ok": True}

# ── A user's own bots (Phase 2, docs/phase2-design.md): the API writes what the user asks for and reads their bots'
# status; the root provisioner decides and runs them (the owner's approval, consent, keys, cap — Demo only). The user
# id is always the session's: a user reaches only their own desired state and their own bots' folders.
from app import user_bots

@app.get("/api/user/bots")
async def user_bots_get(user: dict = Depends(require_user)):
    return {"desired": user_bots.read_desired(user["id"]), **user_bots.status(user["id"]),
            "rules": {"envs": list(user_bots.ENVS_ALLOWED), "max_strategies": user_bots.MAX_STRATEGIES,
                      "strategies": list(user_bots.STRATEGIES), "bounds": user_bots.BOUNDS}}

@app.post("/api/user/bots")
async def user_bots_set(req: UserBotsReq, user: dict = Depends(require_user)):
    _require_confirmed(user)
    rate_limit(user["id"], "user_bots", 10, 60)
    try:
        return {"ok": True, "desired": user_bots.write_desired(user["id"], req.model_dump())}
    except ValueError as e:
        raise HTTPException(400, str(e))

@app.post("/api/user/bots/close")
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
    base = user_bots.ipc_instance(user["id"], req.strategy)
    legacy_base = user_bots.IPC_ROOT / user["id"] / req.strategy
    if not (base / "commands").is_dir() and (legacy_base / "commands").is_dir():
        base = legacy_base
    _drop_request(base / "commands", base, rid,
                  {"id": rid, "symbol": sym, "at_epoch": _time.time(), "by": user.get("email")}, mode=0o644)
    return {"ok": True, "id": rid}

@app.get("/api/user/bots/close/{strategy}/{rid}")
async def user_bots_close_result(strategy: str, rid: str, user: dict = Depends(require_user)):
    if strategy not in user_bots.STRATEGIES or not re.fullmatch(r"[0-9a-f]{32}", rid):
        raise HTTPException(400, "bad request")
    d = user_bots.ipc_instance(user["id"], strategy)
    res = user_bots.read_json(d / "results" / f"{rid}.json")      # the user's bot wrote it: no link followed
    if res is None:
        return {"done": False, "pending": (d / "commands" / f"close-{rid}.json").exists()}
    return {"done": True, **(res if isinstance(res, dict) else {})}

@app.get("/api/admin/user-bots")
async def admin_user_bots(user: dict = Depends(require_admin)):
    """Every user who asked for bots: what they asked, the provisioner's answer, their bots' positions and problems."""
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
        out.append({"user_id": uid, "desired": user_bots.read_desired(uid), "provision": st["provision"], "bots": bots})
    return {"users": out, "max_users": user_bots.MAX_USERS}

@app.get("/api/trades")
async def api_trades(limit: int = 50, user: dict = Depends(require_admin)):
    limit = max(1, min(limit, 500))
    async with async_session() as sess:
        res = await sess.execute(select(Trade).order_by(desc(Trade.id)).limit(limit))
        rows=res.scalars().all()
        return [{"id":r.id,"symbol":r.symbol,"side":r.side,"entry":r.entry,"exit":r.exit,"qty":r.qty,"pnl":r.pnl,"status":r.status,"sl":r.sl,"tp":r.tp,"at":r.created_at} for r in rows]
