
import os, json, asyncio
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional
import sys

# Add parent to path for bot strategies
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import init_db, async_session, Trade, BacktestRun
from sqlalchemy import select, desc
import ccxt, pandas as pd, numpy as np
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv; load_dotenv()
except: pass

BOT_DIR = Path(__file__).parent.parent.parent

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    print("DB ready")
    yield

app = FastAPI(title="Bot Saros API", version="2.0.0", lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Health
@app.get("/api/health")
async def health():
    return {"ok": True, "name": "Bot Saros", "version": "2.0.0"}

# ── Backtest: proxy to backtest.py (same logic, now via API + DB)
class BacktestReq(BaseModel):
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    from_date: Optional[str] = None  # YYYY-MM-DD
    to_date: Optional[str] = None
    limit: int = 300
    strategies: Optional[List[str]] = None
    amount: float = 20
    leverage: int = 5
    fee: float = 0.0004

@app.post("/api/backtest")
async def api_backtest(req: BacktestReq):
    import subprocess, json as js
    args = ["--symbol", req.symbol, "--timeframe", req.timeframe, "--amount", str(req.amount), "--leverage", str(req.leverage), "--fee", str(req.fee)]
    if req.from_date: args += ["--from", req.from_date]
    if req.to_date: args += ["--to", req.to_date]
    if not req.from_date and not req.to_date: args += ["--limit", str(req.limit)]
    if req.strategies: args += ["--strategies", ",".join(req.strategies)]

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
    sym_file = req.symbol.replace("/","")
    json_path = BOT_DIR / f"backtest_{sym_file}_{req.timeframe}.json"
    data = None
    if json_path.exists():
        try: data = js.loads(json_path.read_text(encoding="utf-8"))
        except: pass

    # Save to DB
    try:
        async with async_session() as sess:
            rec = BacktestRun(symbol=req.symbol, timeframe=req.timeframe, from_date=req.from_date, to_date=req.to_date, strategies=js.dumps(req.strategies or []), stats=js.dumps(data.get("stats",{}) if data else {}), created_at=datetime.now(timezone.utc).isoformat())
            sess.add(rec); await sess.commit()
    except: pass

    return {"ok": proc.returncode==0, "code": proc.returncode, "stdout": out[-8000:], "stderr": err[-2000:], "data": data, "chart": f"backtest_{sym_file}_{req.timeframe}.png"}

@app.get("/api/backtest/history")
async def backtest_history(limit: int = 20):
    async with async_session() as sess:
        res = await sess.execute(select(BacktestRun).order_by(desc(BacktestRun.id)).limit(limit))
        rows = res.scalars().all()
        return [{"id":r.id,"symbol":r.symbol,"timeframe":r.timeframe,"from":r.from_date,"to":r.to_date,"strategies":r.strategies,"stats":r.stats,"at":r.created_at} for r in rows]

@app.get("/api/chart")
async def api_chart(file: str):
    if not file.startswith("backtest_") or not file.endswith((".png",".json")):
        raise HTTPException(400, "bad file")
    p = BOT_DIR / file
    if not p.exists(): raise HTTPException(404, "not found")
    ct = "image/png" if file.endswith(".png") else "application/json"
    return FileResponse(str(p), media_type=ct)

# ── Bot control: status, start/stop (paper), trades
bot_task = None

@app.get("/api/bot/status")
async def bot_status():
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

@app.post("/api/bot/start")
async def bot_start(req: BotStartReq, bg: BackgroundTasks):
    global bot_task
    if bot_task and not bot_task.done():
        return {"ok": False, "msg": "already running"}
    # Save config for bot loop
    cfg = {"symbols": req.symbols, "strategies": req.strategies, "timeframe": req.timeframe, "paper": req.paper}
    (BOT_DIR / "api_bot_config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    bot_task = asyncio.create_task(bot_loop(cfg))
    return {"ok": True, "msg": "started", "config": cfg}

@app.post("/api/bot/stop")
async def bot_stop():
    global bot_task
    if bot_task: bot_task.cancel()
    return {"ok": True}

async def bot_loop(cfg):
    """Paper loop: يحلل كل 60s ويحفظ في DB + يرسل تليجرام"""
    import strategies_advanced as adv
    import bot as botmod
    # Override enabled
    if cfg.get("strategies"): botmod.CONFIG["enabled_strategies"] = cfg["strategies"]
    if cfg.get("timeframe"): botmod.CONFIG["timeframe"] = cfg["timeframe"]
    if cfg.get("symbols"): botmod.CONFIG["symbols"] = cfg["symbols"]
    botmod.CONFIG["paper_trading"] = cfg.get("paper", True)
    from app.telegram_bot import send_telegram, format_entry, format_exit
    from app.oco import place_oco_orders
    print(f"Bot loop started {cfg}")
    while True:
        try:
            state = botmod.load_state()
            ex, err = botmod.get_exchange(auth=not botmod.CONFIG["paper_trading"])
            if err: ex = ccxt.binance({"enableRateLimit": True})
            prices={}; analyses={}
            for sym in botmod.CONFIG["symbols"]:
                try:
                    df=botmod.fetch_ohlcv(sym, botmod.CONFIG["timeframe"], limit=300, ex=ex)
                    a=botmod.analyze(sym, df); analyses[sym]=a; prices[sym]=a["price"]
                except Exception as e: print(f"{sym} {e}")
            # Save to DB + check OCO: for opens, place SL/TP if live
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
                        # OCO if live
                        if not botmod.CONFIG["paper_trading"]:
                            try: place_oco_orders(ex, sym, pos["side"], pos["qty"], pos["sl"], pos["tp"])
                            except: pass
                        rec=Trade(symbol=sym, side=pos["side"], entry=pos["entry"], qty=pos["qty"], sl=pos["sl"], tp=pos["tp"], leverage=pos.get("leverage",5), entry_ts=pos.get("time",""), status="open", created_at=datetime.now(timezone.utc).isoformat())
                        sess.add(rec); await sess.commit()
                        await send_telegram(format_entry(sym, pos["side"], pos["entry"], pos["sl"], pos["tp"], pos.get("leverage",5), a["total"] if sym in analyses else 0, float(pos.get("notional",20))/max(1,int(pos.get("leverage",5))), botmod.CONFIG.get("timeframe","4h"), (botmod.CONFIG.get("enabled_strategies") or ["ict"])[0] if (botmod.CONFIG.get("enabled_strategies") or ["ict"]) else "ict"))
                    # Closed: mark
                    for sym in (before - after):
                        # find history
                        hist=[h for h in state.get("history",[]) if h.get("symbol")==sym]
                        last=hist[-1] if hist else {}
                        # update DB
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
                (BOT_DIR / "dashboard-data.json").write_text(json.dumps({"analyses":analyses,"state":state,"time":datetime.now(timezone.utc).isoformat()}, ensure_ascii=False, indent=2), encoding="utf-8")
            except: pass
        except asyncio.CancelledError: print("bot loop stopped"); break
        except Exception as e: print(f"loop err {e}")
        await asyncio.sleep(int(botmod.CONFIG.get("poll_seconds",60)))


@app.get("/api/user/tier")
async def user_tier(user_id: str = ""):
    """يرجع باقة المستخدم من Supabase — server-side verification"""
    import os
    try:
        from supabase import create_client
        url = os.getenv("SUPABASE_URL","")
        key = os.getenv("SUPABASE_SERVICE_KEY","")
        if url and key and user_id:
            supa = create_client(url, key)
            row = supa.table("profiles").select("tier").eq("id", user_id).single().execute()
            if row.data: return {"tier": row.data.get("tier","free")}
    except Exception as e:
        return {"tier": "free", "note": str(e)[:100]}
    return {"tier": "free"}


@app.post("/api/optimizer/run")
async def optimizer_run(symbol: str = "BTC/USDT", timeframe: str = "4h", limit: int = 200):
    """يشغل Auto-Optimizer ويرجع البطل — يحدث ai_weights.json"""
    import subprocess, json as js
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
async def telegram_test():
    from app.telegram_bot import test_telegram
    ok = await test_telegram()
    return {"ok": bool(ok), "msg": "تم الإرسال" if ok else "فشل — تأكد من TELEGRAM_BOT_TOKEN و CHAT_ID في backend/.env"}

@app.get("/api/telegram/status")
async def telegram_status():
    import os
    has_token = bool(os.getenv("TELEGRAM_BOT_TOKEN","").strip())
    has_chat = bool(os.getenv("TELEGRAM_CHAT_ID","").strip())
    return {"configured": has_token and has_chat, "has_token": has_token, "has_chat": has_chat}


@app.post("/api/evolve")
async def evolve():
    """Self-evolution: يعيد تقييم الـ 15 استراتيجية ويطفي الخسرانة + يحدث الأوزان"""
    import subprocess, json as js, sys
    from pathlib import Path as _P
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

@app.get("/api/trades")
async def api_trades(limit: int = 50):
    async with async_session() as sess:
        res = await sess.execute(select(Trade).order_by(desc(Trade.id)).limit(limit))
        rows=res.scalars().all()
        return [{"id":r.id,"symbol":r.symbol,"side":r.side,"entry":r.entry,"exit":r.exit,"qty":r.qty,"pnl":r.pnl,"status":r.status,"sl":r.sl,"tp":r.tp,"at":r.created_at} for r in rows]
