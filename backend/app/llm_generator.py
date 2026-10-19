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
                return {"ok": False, "error": f"LLM {r.status_code}: {r.text[:300]}"}
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

async def backtest_llm(code: str, symbol="BTC/USDT", timeframe="4h", limit=300):
    """Run backtest on LLM code — returns stats like backtest.py"""
    import sys, tempfile, subprocess, json as js
    from pathlib import Path as _P
    # Save temp strategy
    tmp = _P(__file__).parent.parent / "_llm_tmp.py"
    tmp.write_text(code, encoding="utf-8")
    # Run backtest via subprocess with --strategies pointing to llm
    # Instead, directly score via python to avoid needing to register strategy
    # Inject as dynamic module
    import importlib.util
    spec = importlib.util.spec_from_file_location("_llm_tmp", str(tmp))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Now run a mini backtest using our existing logic but with llm_signal
    saros_root = _P(__file__).parent.parent
    sys.path.insert(0, str(saros_root))
    sys.path.insert(0, str(saros_root.parent))
    import backtest as bt
    import pandas as pd
    # Fetch data
    df = bt.fetch_ohlcv(symbol, timeframe, limit)
    # Monkey-patch: add llm to score_at via enabled
    # Instead run manual loop with llm_signal
    # Quick validation: call once
    try:
        score, reasons = mod.llm_signal(df)
        assert -1.1 <= score <= 1.1, f"score {score} out of range"
    except Exception as e:
        return {"ok": False, "error": f"llm_signal failed: {e}"}
    # Full backtest: we add llm as extra strategy by monkey patching backtest's CONFIG
    orig_weights = dict(bt.CONFIG["weights"])
    bt.CONFIG["weights"]["llm_tmp"] = 1.0
    # Patch score_at to include llm
    orig_score_at = bt.score_at
    def patched(df2, enabled=None):
        # Call original
        total, base = orig_score_at(df2, enabled)
        # If llm is relevant (enabled is None or contains llm_tmp)
        if enabled is None or "llm_tmp" in enabled:
            try:
                s, _ = mod.llm_signal(df2)
                base["llm_tmp"] = float(s)
            except: base["llm_tmp"] = 0
        return total, base
    bt.score_at = patched
    try:
        res = bt.run_backtest(df, amount_usdt=20, leverage=5, enabled=["llm_tmp"])
        return {"ok": True, "stats": res["stats"], "trades": res["trades"][-5:], "total": res["stats"]["total"]}
    finally:
        bt.score_at = orig_score_at
        bt.CONFIG["weights"] = orig_weights
