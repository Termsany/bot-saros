"""Backtests: run one (the plan's limits checked here), the user's history, the chart files.

Moved out of app/main.py (development-plan 3.2); the paths and behaviour are unchanged. Names the tests replace on
app.main, and state that lives there, are read as M.<name> at call time.
"""
from fastapi import APIRouter

from app import main as M
from app.main import (  # noqa: F401
    uuid,
    BacktestReq,
    BacktestRun,
    Depends,
    FileResponse,
    HTTPException,
    PER_COIN,
    _backtest_slots,
    _cleanup_backtest_files,
    _scrub,
    asyncio,
    backtest_span_days,
    datetime,
    desc,
    json,
    os,
    rate_limit,
    re,
    require_user,
    select,
    sys,
    timezone,
)

router = APIRouter()

@router.post("/api/backtest")
async def api_backtest(req: BacktestReq, user: dict = Depends(require_user)):
    rate_limit(user["id"], "backtest", int(os.getenv("BACKTEST_PER_MIN", "5")), 60)
    tier = await M.get_tier(user)
    max_days = M.TIER_BACKTEST_DAYS[tier]
    if max_days is not None:
        span = backtest_span_days(req)
        if span > max_days:
            raise HTTPException(403, f"backtest range is {span:g} days — your {tier} plan allows up to {max_days} days. Upgrade for longer backtests")
    allowed = M.STRATEGY_ORDER[:M.TIER_STRATEGY_COUNT[tier]]
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
    json_path = M.BOT_DIR / f"{run_name}.json"
    args = ["--out-json", str(json_path), "--out", str(M.BOT_DIR / f"{run_name}.png"), "--symbol", req.symbol, "--timeframe", req.timeframe, "--amount", str(req.amount), "--leverage", str(req.leverage), "--fee", str(req.fee)]
    if req.from_date: args += ["--from", req.from_date]
    if req.to_date: args += ["--to", req.to_date]
    if not req.from_date and not req.to_date: args += ["--limit", str(req.limit)]
    if req.strategies: args += ["--strategies", ",".join(req.strategies)]

    async with _backtest_slots:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(M.BOT_DIR / "backtest.py"), *args,
            cwd=str(M.BOT_DIR), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
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
        async with M.async_session() as sess:
            rec = BacktestRun(user_id=user["id"], symbol=req.symbol, timeframe=req.timeframe, from_date=req.from_date, to_date=req.to_date, strategies=js.dumps(req.strategies or []), stats=js.dumps(data.get("stats",{}) if data else {}), created_at=datetime.now(timezone.utc).isoformat(), chart_file=f"{run_name}.png", run_name=run_name)
            sess.add(rec); await sess.commit()
    except: pass

    return {"ok": proc.returncode==0, "code": proc.returncode, "stdout": _scrub(out[-8000:]), "stderr": _scrub(err[-2000:]), "data": data, "chart": f"{run_name}.png"}

@router.get("/api/backtest/history")
async def backtest_history(limit: int = 20, user: dict = Depends(require_user)):
    limit = max(1, min(limit, 100))
    async with M.async_session() as sess:
        # only the caller's own runs (this used to list every user's backtests)
        res = await sess.execute(select(BacktestRun).where(BacktestRun.user_id == user["id"]).order_by(desc(BacktestRun.id)).limit(limit))
        rows = res.scalars().all()
        return [{"id":r.id,"symbol":r.symbol,"timeframe":r.timeframe,"from":r.from_date,"to":r.to_date,"strategies":r.strategies,"stats":r.stats,"at":r.created_at} for r in rows]

@router.get("/api/chart")
async def api_chart(file: str, user: dict = Depends(require_user)):
    # Stage C: strict file->run binding - any owned run no longer unlocks every file
    if not re.fullmatch(r"backtest_[A-Za-z0-9_]+\.(png|json)", file):
        raise HTTPException(400, "bad file")
    stem = file.rsplit(".", 1)[0]
    async with M.async_session() as sess:
        res = await sess.execute(select(BacktestRun).where((BacktestRun.user_id==user["id"]) & ((BacktestRun.run_name==stem) | (BacktestRun.chart_file==file))).limit(1))
        row = res.scalars().first()
        if row is None:
            raise HTTPException(403, "not your chart")
    p = M.BOT_DIR / file
    if not p.exists(): raise HTTPException(404, "not found")
    ct = "image/png" if file.endswith(".png") else "application/json"
    return FileResponse(str(p), media_type=ct)
