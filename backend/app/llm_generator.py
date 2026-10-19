import os, json, re, httpx
from pathlib import Path

CODECRAFT_KEY = os.getenv("CODECRAFT_API_KEY", "")
CODECRAFT_URL = "https://codecraftapi.com/v1/chat/completions"
MODEL = "claude-sonnet-5"  # Sonnet 4 equivalent on CodeCraft

SYSTEM = """You are a python quant. Generate ONE trading strategy scoring function.

CRITICAL: The strategy MUST generate signals. Use lenient thresholds (e.g. RSI<45 for long, not <30) so it triggers 5-15 trades per 200 candles. If too strict, it will have 0 trades and fail backtest.

RULES:
- Output ONLY python code, no markdown, no explanation
- Signature: def llm_signal(df): -> (score: float in [-1, +1], reasons: list[str])
- df is pandas DataFrame with columns ts, open, high, low, close, vol
- Use pandas/numpy only. Keep it under 30 lines.
- Return score in [-1, +1] clipped, and reasons list.
"""

async def generate_strategy(prompt: str) -> dict:
    if not CODECRAFT_KEY:
        return {"ok": False, "error": "CODECRAFT_API_KEY not set in backend/.env"}
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(CODECRAFT_URL,
                headers={"Authorization": f"Bearer {CODECRAFT_KEY}", "Content-Type": "application/json"},
                json={
                    "model": MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": f"Generate a strategy for: {prompt}\n\nOutput ONLY the python function llm_signal(df)."},
                    ],
                    "max_tokens": 3000,
                })
            if r.status_code != 200:
                body = r.text[:500]
                if "Just a moment" in body or "cloudflare" in body.lower():
                    return {"ok": False, "error": "CodeCraft blocked from Render (Cloudflare). \u0627\u0633\u062a\u062e\u062f\u0645 \u0627\u0644\u0645\u062e\u062a\u0628\u0631 \u0644\u0648\u0643\u0627\u0644 \u0623\u0648 \u0641\u0639\u0651\u0644 Cloudflare bypass في CodeCraft"}
                return {"ok": False, "error": f"LLM {r.status_code}: {body[:300]}"}
            j = r.json()
            content = j["choices"][0]["message"]["content"] or ""
            # Extract code
            code = content
            # Strip markdown fences if present
            if "```" in code:
                m = re.search(r"```(?:python)?\s*(.*?)```", code, re.S)
                if m: code = m.group(1)
            code = code.strip()
            if "def llm_signal" not in code:
                return {"ok": False, "error": "LLM did not return llm_signal", "raw": content[:500]}
            return {"ok": True, "code": code, "raw": content[:1000], "usage": j.get("usage")}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}

def save_strategy(code: str, name: str = None) -> Path:
    llm_dir = Path(__file__).parent.parent.parent / "strategies_llm"
    if not (llm_dir / "strategies_llm").exists():
        # We're in backend/app/ -> parent is backend, parent.parent is saros
        actual = Path(__file__).parent.parent / "strategies_llm"
        # fallback: saros root
        alt = Path(__file__).parent.parent.parent
        llm_dir = actual
    # Actually: backend/app/ -> backend/ -> saros/
    saros_root = Path(__file__).parent.parent.parent if (Path(__file__).parent.parent.parent / "package.json").exists() else Path(__file__).parent.parent
    llm_dir = saros_root / "strategies_llm"
    llm_dir.mkdir(exist_ok=True)
    if not name:
        existing = list(llm_dir.glob("llm_*.py"))
        name = f"llm_{len(existing)+1:03d}"
    fp = llm_dir / f"{name}.py"
    fp.write_text(code, encoding="utf-8")
    return fp


async def auto_promote_if_winner(code: str, name: str, stats: dict) -> dict:
    """لو WR >= 60% و PF >= 1.2 — يضيفها رسمي للـ elite تلقائياً"""
    wr = stats.get("win_rate", 0)
    pf = stats.get("profit_factor", 0)
    if wr < 60 or (pf != float("inf") and pf < 1.2):
        return {"promoted": False, "reason": f"WR {wr:.1f}% < 60% or PF {pf:.2f} < 1.2"}
    # Save to strategies_llm and register
    from pathlib import Path as _P
    import json as _js
    # Add to lib/strategies.ts ? No — just mark as promoted in a registry
    registry = _P(__file__).parent.parent / "strategies_llm" / "registry.json"
    registry.parent.mkdir(exist_ok=True)
    data = []
    if registry.exists():
        try: data = _js.loads(registry.read_text(encoding="utf-8"))
        except: data = []
    entry = {"name": name, "win_rate": wr, "pf": pf, "pnl": stats.get("pnl",0), "promoted_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()}
    # dedup
    data = [d for d in data if d.get("name") != name]
    data.append(entry)
    registry.write_text(_js.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    # Telegram notify
    try:
        from app.telegram_bot import send_telegram
        await send_telegram(f"\U0001f389 *استراتيجية جديدة ترقت تلقائياً!*\n{name} — WR `{wr:.1f}%` PF `{pf:.2f}` PnL `{stats.get('pnl',0):+.2f}`\nتمت إضافتها للـ Elite.")
    except: pass
    return {"promoted": True, "name": name, "wr": wr, "pf": pf}

async def backtest_llm(code: str, symbol="BTC/USDT", timeframe="4h", limit=300):
    """Backtest LLM code in an isolated subprocess (see llm_sandbox) — returns stats like backtest.py"""
    import asyncio, sys
    from app.llm_sandbox import run_backtest_sandboxed, validate_code, UnsafeCode
    try:
        validate_code(code)
    except UnsafeCode as e:
        return {"ok": False, "error": f"rejected by sandbox: {e}"}
    repo_root = Path(__file__).parent.parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    import backtest as bt
    df = await asyncio.to_thread(bt.fetch_ohlcv, symbol, timeframe, limit)
    return await run_backtest_sandboxed(code, df, repo_root)
