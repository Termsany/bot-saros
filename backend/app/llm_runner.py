"""
Child process for llm_sandbox.run_backtest_sandboxed — do not import from the API.
argv: <work_dir> <repo_root>. Prints one line: __RESULT__{json}
"""
import sys, json, importlib.util
from pathlib import Path


def emit(obj):
    print("__RESULT__" + json.dumps(obj, default=str, ensure_ascii=False))


def main():
    work, root = Path(sys.argv[1]), sys.argv[2]
    sys.path.insert(0, root)
    import pandas as pd
    import backtest as bt

    df = pd.read_csv(work / "data.csv")
    df["ts"] = pd.to_datetime(df["ts"])

    spec = importlib.util.spec_from_file_location("llm_strategy", str(work / "strategy.py"))
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        score, _ = mod.llm_signal(df)
        if not (-1.1 <= float(score) <= 1.1):
            raise ValueError(f"score {score} out of range")
    except Exception as e:
        return emit({"ok": False, "error": f"llm_signal failed: {str(e)[:300]}"})

    orig_score_at = bt.score_at
    bt.CONFIG["weights"]["llm_tmp"] = 1.0

    def llm_score(df2):
        try:
            s, _ = mod.llm_signal(df2)
            return max(-1.0, min(1.0, float(s)))
        except Exception:
            return 0.0

    def patched(df2, enabled=None):
        # LLM strategy alone: its score *is* the total (orig score_at would ignore llm_tmp and return 0)
        if enabled == ["llm_tmp"]:
            s = llm_score(df2)
            return s, {"llm_tmp": s}
        total, base = orig_score_at(df2, enabled)
        if enabled is None or "llm_tmp" in enabled:
            base["llm_tmp"] = llm_score(df2)
        return total, base

    bt.score_at = patched
    res = bt.run_backtest(df, amount_usdt=20, leverage=5, enabled=["llm_tmp"])
    emit({"ok": True, "stats": res["stats"], "trades": res["trades"][-5:], "total": res["stats"]["total"]})


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        emit({"ok": False, "error": str(e)[:300]})
