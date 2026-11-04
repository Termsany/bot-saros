"""Research tools, admin only: the optimizer, the Telegram test, the strategy evolver and the LLM lab. None of
them places an order.

Moved out of app/main.py (development-plan 3.2); the paths and behaviour are unchanged. Names the tests replace on
app.main, and state that lives there, are read as M.<name> at call time.
"""
from fastapi import APIRouter

from app import main as M
from app.main import (  # noqa: F401
    Depends,
    HTTPException,
    Path,
    SYMBOL_RE,
    __file__,
    _require_llm_lab,
    _scrub,
    asyncio,
    json,
    os,
    rate_limit,
    require_admin,
    require_admin_or_cron,
    sys,
)

router = APIRouter()

@router.post("/api/optimizer/run")
async def optimizer_run(symbol: str = "BTC/USDT", timeframe: str = "4h", limit: int = 200, user: dict = Depends(require_admin)):
    """يشغل Auto-Optimizer ويرجع البطل — يحدث ai_weights.json"""
    rate_limit(user["id"], "optimizer", 2, 300)
    import json as js
    if not SYMBOL_RE.match(symbol) or timeframe not in M.TIMEFRAMES: raise HTTPException(400, "bad symbol/timeframe")
    limit = max(50, min(int(limit), 1000))
    if not (M.BOT_DIR / "auto_optimizer.py").exists():
        return {"ok": False, "error": "auto_optimizer.py is missing from the repo"}
    args = [sys.executable, str(M.BOT_DIR / "auto_optimizer.py"), "--symbol", symbol, "--timeframe", timeframe, "--limit", str(limit)]
    try:
        proc = await asyncio.create_subprocess_exec(*args, cwd=str(M.BOT_DIR), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
        out = stdout.decode(errors="ignore"); err = stderr.decode(errors="ignore")
        # Read weights if created
        weights = None
        try:
            wp = M.BOT_DIR / "ai_weights.json"
            if wp.exists(): weights = js.loads(wp.read_text(encoding="utf-8"))
        except: pass
        return {"ok": proc.returncode==0, "stdout": out[-4000:], "stderr": err[-1500:], "weights": weights}
    except asyncio.TimeoutError:
        return {"ok": False, "error": "optimizer timeout — جرب limit أصغر"}

@router.post("/api/telegram/test")
async def telegram_test(user: dict = Depends(require_admin)):
    from app.telegram_bot import test_telegram
    ok = await test_telegram()
    return {"ok": bool(ok), "msg": "تم الإرسال" if ok else "فشل — تأكد من TELEGRAM_BOT_TOKEN و CHAT_ID في backend/.env"}

@router.get("/api/telegram/status")
async def telegram_status(user: dict = Depends(require_admin)):
    import os
    has_token = bool(os.getenv("TELEGRAM_BOT_TOKEN","").strip())
    has_chat = bool(os.getenv("TELEGRAM_CHAT_ID","").strip())
    return {"configured": has_token and has_chat, "has_token": has_token, "has_chat": has_chat}


@router.post("/api/evolve")
async def evolve(user: dict = Depends(require_admin_or_cron)):
    """Self-evolution: يعيد تقييم الـ 15 استراتيجية ويطفي الخسرانة + يحدث الأوزان"""
    rate_limit(user["id"], "evolve", 1, 300)
    import json as js
    if not (M.BOT_DIR / "auto_optimizer.py").exists():
        return {"ok": False, "error": "auto_optimizer.py is missing from the repo"}
    # Run optimizer on BTC 4h (light)
    args = [sys.executable, str(M.BOT_DIR / "auto_optimizer.py"), "--symbol", "BTC/USDT", "--timeframe", "4h", "--limit", "200"]
    try:
        proc = await asyncio.create_subprocess_exec(*args, cwd=str(M.BOT_DIR), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
        out = stdout.decode(errors="ignore")
        # Read weights
        weights = None
        try:
            wp = M.BOT_DIR / "ai_weights.json"
            if wp.exists():
                weights = js.loads(wp.read_text(encoding="utf-8"))
        except: pass
        # Self-pruning: if any strategy PF < 0.8 for 2 weeks, suggest disabling
        pruning = []
        try:
            cmp_path = M.BOT_DIR / "optimizer_BTCUSDT_4h.json"
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


@router.post("/api/llm/generate")
async def llm_generate(prompt: str = "RSI + volume divergence on 4h", symbol: str = "BTC/USDT", timeframe: str = "4h", user: dict = Depends(require_admin)):
    """LLM يخترع استراتيجية + باك تست فوري (الكود بيتشغل في sandbox — شوف llm_sandbox.py)"""
    _require_llm_lab()
    rate_limit(user["id"], "llm_generate", 3, 300)
    if not SYMBOL_RE.match(symbol) or timeframe not in M.TIMEFRAMES: raise HTTPException(400, "bad symbol/timeframe")
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

@router.get("/api/llm/list")
async def llm_list(user: dict = Depends(require_admin)):
    from pathlib import Path as _P
    d = _P(__file__).parent.parent / "strategies_llm"
    if not d.exists():
        return []
    out = []
    for f in sorted(d.glob("llm_*.py")):
        out.append({"name": f.stem, "code": f.read_text(encoding="utf-8")[:2000], "size": f.stat().st_size})
    return out


@router.post("/api/llm/evolve")
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
