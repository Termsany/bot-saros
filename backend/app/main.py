
import os, json, asyncio
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import List, Optional
import sys, re, uuid

# Add parent to path for bot strategies
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import init_db, async_session, Trade, BacktestRun
from app.auth import require_user, require_admin, require_admin_or_cron
from sqlalchemy import select, desc
import ccxt, pandas as pd, numpy as np
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv; load_dotenv()
except: pass

BOT_DIR = Path(__file__).parent.parent.parent

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

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    print("DB ready")
    asyncio.create_task(check_supabase_service_key())  # don't delay startup on a slow Supabase
    yield

# API docs list every endpoint — off in production unless ENABLE_API_DOCS=true
_docs = os.getenv("ENABLE_API_DOCS", "").lower() == "true"
app = FastAPI(title="Raqm API", version="2.0.0", lifespan=lifespan,
              docs_url="/docs" if _docs else None, redoc_url=None, openapi_url="/openapi.json" if _docs else None)

ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "https://bot-saros.vercel.app,http://localhost:3000").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])

def live_trading_allowed() -> bool:
    """Global kill switch: real orders only if ALLOW_LIVE_TRADING=true on the server."""
    return os.getenv("ALLOW_LIVE_TRADING", "").strip().lower() == "true"

TIMEFRAMES = {"1m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"}
SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,15}/[A-Z]{3,5}$")
_backtest_slots = asyncio.Semaphore(int(os.getenv("MAX_CONCURRENT_BACKTESTS", "2")))

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

# Plan limits — enforced here, not only in the UI (StrategyPicker unlocks the first N of this list).
# Keep in sync with lib/strategies.ts STRATEGIES order and TIERS counts.
STRATEGY_ORDER = ["rsi_macd", "classical", "ichimoku", "dow", "gann", "sr", "elliott", "smc", "vwap",
                  "supertrend", "bollinger", "harmonic", "ict", "heikin", "ai", "wave_flats", "trend_daily"]
TIER_STRATEGY_COUNT = {"free": 2, "starter": 6, "pro": 7, "elite": 17}
SOLO_STRATEGIES = ("wave_flats", "trend_daily")  # own entries/exits — always run alone
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

async def get_tier(user: dict) -> str:
    """Tier from Supabase profiles (service key). Fails closed to 'free'; admins get everything."""
    from app.auth import _admin_emails
    if user.get("email") in _admin_emails() and user.get("email_confirmed"):
        return "elite"
    hit = _tier_cache.get(user["id"])
    if hit and hit[0] > _time.monotonic():
        return hit[1]
    tier = "free"
    url, key = os.getenv("SUPABASE_URL", "").rstrip("/"), os.getenv("SUPABASE_SERVICE_KEY", "")
    if url and key:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=8) as client:
                r = await client.get(f"{url}/rest/v1/profiles", params={"id": f"eq.{user['id']}", "select": "tier"},
                                     headers={"apikey": key, "Authorization": f"Bearer {key}"})
            rows = r.json() if r.status_code == 200 else []
            if rows and rows[0].get("tier") in TIER_STRATEGY_COUNT:
                tier = rows[0]["tier"]
        except Exception as e:
            print(f"get_tier error: {e}")
            return "free"  # don't cache failures
    if len(_tier_cache) > 5000: _tier_cache.clear()
    _tier_cache[user["id"]] = (_time.monotonic() + 60, tier)
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
        req.strategies = allowed  # empty = "all", which must still mean all *allowed*
    solo = [s for s in req.strategies if s in SOLO_STRATEGIES]
    if solo and (len(req.strategies) > 1 or req.strategies == allowed):
        req.strategies = [x for x in req.strategies if x not in SOLO_STRATEGIES] or solo[:1]
    if req.strategies == ["trend_daily"]: req.timeframe = "1d"
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
            rec = BacktestRun(user_id=user["id"], symbol=req.symbol, timeframe=req.timeframe, from_date=req.from_date, to_date=req.to_date, strategies=js.dumps(req.strategies or []), stats=js.dumps(data.get("stats",{}) if data else {}), created_at=datetime.now(timezone.utc).isoformat())
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
async def api_chart(file: str):
    # strict name check — "backtest_/../backend/vault.json" used to pass startswith/endswith
    if not re.fullmatch(r"backtest_[A-Za-z0-9_]+\.(png|json)", file):
        raise HTTPException(400, "bad file")
    p = BOT_DIR / file
    if not p.exists(): raise HTTPException(404, "not found")
    ct = "image/png" if file.endswith(".png") else "application/json"
    return FileResponse(str(p), media_type=ct)

# ── Bot control: status, start/stop (paper), trades
bot_task = None

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
    if not req.paper and not live_trading_allowed():
        raise HTTPException(400, "LIVE disabled — set ALLOW_LIVE_TRADING=true on the backend to allow real orders")
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
    cfg = {"symbols": req.symbols, "strategies": req.strategies, "timeframe": req.timeframe, "paper": req.paper, "leverage": lev}
    (BOT_DIR / "api_bot_config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    bot_task = asyncio.create_task(bot_loop(cfg))
    return {"ok": True, "msg": "started", "config": cfg}

@app.post("/api/bot/stop")
async def bot_stop(user: dict = Depends(require_admin)):
    global bot_task
    if bot_task: bot_task.cancel()
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

async def bot_loop(cfg):
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
    is_paper = bool(cfg.get("paper", True))
    print(f"Bot loop started {cfg}")
    while True:
        try:
            picked = _get_exchange_for_cycle(is_paper)
            if picked is None:
                await asyncio.sleep(int(botmod.CONFIG.get("poll_seconds",60)))
                continue
            ex_name, ex, cycle_paper = picked
            botmod.CONFIG["paper_trading"] = cycle_paper
            state = botmod.load_state()
            prices={}; analyses={}
            for sym in botmod.CONFIG["symbols"]:
                try:
                    df=botmod.fetch_ohlcv(sym, botmod.CONFIG["timeframe"], limit=botmod.candles_needed(), ex=ex)
                    a=botmod.analyze(sym, df); analyses[sym]=a; prices[sym]=a["price"]
                except Exception as e: print(f"{sym} {e}")
            before = set(state.get("positions",{}).keys())
            if prices: botmod.check_sl_tp(state, prices, ex)
            for sym,a in analyses.items():
                try: botmod.try_enter(sym,a,state,ex)
                except Exception as e: print(f"enter {sym} {e}")
            after = set(state.get("positions",{}).keys())
            # Persist to DB
            try:
                async with async_session() as sess:
                    # New entries
                    for sym in (after - before):
                        pos=state["positions"][sym]
                        if not cycle_paper:
                            oco = place_oco_orders(ex, sym, pos["side"], pos["qty"], pos["sl"], pos["tp"], paper=False)
                            if oco.get("sl_error") or oco.get("tp_error"):
                                print(f"OCO {ex_name} {sym}: {oco}")
                                await send_telegram(f"⚠️ OCO failed on {ex_name} {sym}: SL={oco.get('sl_error','ok')} TP={oco.get('tp_error','ok')}")
                        rec=Trade(symbol=sym, side=pos["side"], entry=pos["entry"], qty=pos["qty"], sl=pos["sl"], tp=pos["tp"], leverage=pos.get("leverage",5), entry_ts=pos.get("time",""), status="open", created_at=datetime.now(timezone.utc).isoformat())
                        sess.add(rec); await sess.commit()
                        strat = (botmod.CONFIG.get("enabled_strategies") or ["ict"])[0]
                        await send_telegram(format_entry(sym, pos["side"], pos["entry"], pos["sl"], pos["tp"], pos.get("leverage",5), analyses[sym]["total"] if sym in analyses else 0, float(pos.get("notional",20))/max(1,int(pos.get("leverage",5))), botmod.CONFIG.get("timeframe","4h"), strat))
                    # Closed: mark
                    for sym in (before - after):
                        if not cycle_paper:
                            cancel_oco_orders(ex, sym)  # leftover reduceOnly SL/TP must not hit a future position
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
        except asyncio.CancelledError: print("bot loop stopped"); break
        except Exception as e: print(f"loop err {e}")
        await asyncio.sleep(int(botmod.CONFIG.get("poll_seconds",60)))


@app.get("/api/user/tier")
async def user_tier(user: dict = Depends(require_user)):
    """يرجع باقة المستخدم الحالي من Supabase — server-side verification"""
    return {"tier": await get_tier(user)}


@app.post("/api/optimizer/run")
async def optimizer_run(symbol: str = "BTC/USDT", timeframe: str = "4h", limit: int = 200, user: dict = Depends(require_admin)):
    """يشغل Auto-Optimizer ويرجع البطل — يحدث ai_weights.json"""
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
        return {"ok": proc.returncode==0, "weights": weights, "pruning": pruning, "stdout": out[-3000:], "stderr": stderr.decode(errors="ignore")[-800:]}
    except asyncio.TimeoutError:
        return {"ok": False, "error": "evolve timeout"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


@app.post("/api/llm/generate")
async def llm_generate(prompt: str = "RSI + volume divergence on 4h", symbol: str = "BTC/USDT", timeframe: str = "4h", user: dict = Depends(require_admin)):
    """LLM يخترع استراتيجية + باك تست فوري (الكود بيتشغل في sandbox — شوف llm_sandbox.py)"""
    if not SYMBOL_RE.match(symbol) or timeframe not in TIMEFRAMES: raise HTTPException(400, "bad symbol/timeframe")
    prompt = prompt[:500]
    from app.llm_generator import generate_strategy, save_strategy, backtest_llm
    gen = await generate_strategy(prompt)
    if not gen.get("ok"):
        return gen
    code = gen["code"]
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
async def llm_evolve(prompt: str = "innovative crypto futures strategy combining momentum and mean reversion", n: int = 3, user: dict = Depends(require_admin_or_cron)):
    """يولد n استراتيجيات، يباك تست كل واحدة، ويضيف الفائزة (WR>=60%) تلقائياً"""
    prompt = prompt[:500]
    from app.llm_generator import generate_strategy, save_strategy, backtest_llm, auto_promote_if_winner
    results = []
    for i in range(min(n, 5)):
        gen = await generate_strategy(f"{prompt} — variation {i+1}")
        if not gen.get("ok"):
            results.append({"i": i+1, "ok": False, "error": gen.get("error")})
            continue
        code = gen["code"]
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

@app.get("/api/llm/promoted")
async def llm_promoted(user: dict = Depends(require_admin)):
    from pathlib import Path as _P
    import json as _js
    reg = _P(__file__).parent.parent / "strategies_llm" / "registry.json"
    if not reg.exists():
        return []
    try: return _js.loads(reg.read_text(encoding="utf-8"))
    except: return []


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

@app.get("/api/trades")
async def api_trades(limit: int = 50, user: dict = Depends(require_admin)):
    limit = max(1, min(limit, 500))
    async with async_session() as sess:
        res = await sess.execute(select(Trade).order_by(desc(Trade.id)).limit(limit))
        rows=res.scalars().all()
        return [{"id":r.id,"symbol":r.symbol,"side":r.side,"entry":r.entry,"exit":r.exit,"qty":r.qty,"pnl":r.pnl,"status":r.status,"sl":r.sl,"tp":r.tp,"at":r.created_at} for r in rows]
