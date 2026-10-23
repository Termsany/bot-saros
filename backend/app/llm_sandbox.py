"""
Run LLM-generated strategy code without giving it access to the backend process.

Two layers:
1. validate_code(): AST allow-list — only `import pandas/numpy/math`, top-level defs/constants,
   no dunder access, no builtins that reach the filesystem/interpreter, no pandas/numpy file I/O.
2. run_backtest_sandboxed(): executes in a separate Python process with an empty environment
   (no API keys, no VAULT_MASTER_KEY), a temp cwd, a timeout and (on Linux) CPU/memory limits.
   The parent fetches the candles and hands them over as a CSV, so the child needs no network.

This is defense in depth, not a perfect sandbox. For a multi-tenant product, run the child in a
separate container with no network and no volume mounts.
"""
import ast, asyncio, json, os, secrets, sys, tempfile
from pathlib import Path

ALLOWED_IMPORTS = {"pandas", "numpy", "math"}

FORBIDDEN_NAMES = {
    "open", "exec", "eval", "compile", "__import__", "globals", "locals", "vars", "getattr", "setattr",
    "delattr", "input", "breakpoint", "help", "memoryview", "type", "super", "classmethod", "staticmethod",
    "property", "exit", "quit", "dir", "id", "object", "print",
}

# Attribute names that reach files, the interpreter, or arbitrary evaluation.
FORBIDDEN_ATTRS = {
    "eval", "query", "pipe", "apply_along_axis", "load", "loads", "save", "savez", "savez_compressed",
    "savetxt", "loadtxt", "genfromtxt", "fromfile", "tofile", "memmap", "fromregex", "DataSource",
    "io", "lib", "api", "core", "compat", "util", "testing", "plotting", "ctypeslib", "os", "sys",
    "builtins", "system", "popen", "subprocess", "f2py", "distutils", "show_config",
    # more file readers/writers: ndarray.dump(path), Excel/HDF5 readers-writers, Styler exports
    "dump", "dumps", "ExcelWriter", "ExcelFile", "HDFStore", "style", "Styler", "ctypes", "mmap",
}
# methods that look up and call another method by its *name* (df.agg("to_csv", path), df.apply("__class__"...)):
# a string argument would get past the attribute checks above
STRING_DISPATCH = {"agg", "aggregate", "transform", "apply", "applymap", "map", "pipe", "resample", "groupby", "rolling",
                   "expanding", "ewm", "eval", "query", "method", "methodcaller", "attrgetter", "itemgetter"}
WINDOW_METHODS = {"rolling", "expanding", "ewm", "resample"}
ALLOWED_PREFIXED_ATTRS = {"to_numpy", "to_list"}
FORBIDDEN_ATTR_PREFIXES = ("read_", "to_", "from_")

MAX_CODE_CHARS = 8000


class UnsafeCode(ValueError):
    pass


def validate_code(code: str) -> None:
    if len(code) > MAX_CODE_CHARS:
        raise UnsafeCode(f"code too long ({len(code)} chars)")
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise UnsafeCode(f"syntax error: {e}")

    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.Assign, ast.AnnAssign)):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue  # docstring
        raise UnsafeCode(f"top-level statement not allowed: {type(node).__name__} (line {node.lineno})")

    if not any(isinstance(n, ast.FunctionDef) and n.name == "llm_signal" for n in tree.body):
        raise UnsafeCode("llm_signal(df) not defined at top level")

    for node in ast.walk(tree):
        line = getattr(node, "lineno", "?")
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in ALLOWED_IMPORTS or "." in a.name:
                    raise UnsafeCode(f"import not allowed: {a.name} (line {line})")
        elif isinstance(node, ast.ImportFrom):
            if node.level or (node.module or "") not in ALLOWED_IMPORTS:
                raise UnsafeCode(f"import not allowed: from {node.module} (line {line})")
        elif isinstance(node, (ast.ClassDef, ast.AsyncFunctionDef, ast.Global, ast.Nonlocal, ast.Await,
                               ast.Yield, ast.YieldFrom, ast.With, ast.AsyncWith,
                               ast.Delete)):
            raise UnsafeCode(f"{type(node).__name__} not allowed (line {line})")
        elif isinstance(node, ast.Name):
            if node.id.startswith("_") or node.id in FORBIDDEN_NAMES:
                raise UnsafeCode(f"name not allowed: {node.id} (line {line})")
        elif isinstance(node, ast.Attribute):
            a = node.attr
            if a.startswith("_") or a in FORBIDDEN_ATTRS or (
                a.startswith(FORBIDDEN_ATTR_PREFIXES) and a not in ALLOWED_PREFIXED_ATTRS
            ):
                raise UnsafeCode(f"attribute not allowed: .{a} (line {line})")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and ("__" in node.value or node.value.startswith("_")):
            raise UnsafeCode(f"underscore string not allowed (line {line})")
        elif isinstance(node, (ast.JoinedStr, ast.FormattedValue)):
            raise UnsafeCode(f"f-strings not allowed (line {line})")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in STRING_DISPATCH:
            # these look a method up by name: only numbers (windows/spans) and inline lambdas are allowed as arguments,
            # plus plain variables for the window-style ones (rolling(n), ewm(span=n))
            windowed = node.func.attr in WINDOW_METHODS
            for arg in list(node.args) + [k.value for k in node.keywords]:
                ok = (isinstance(arg, ast.Constant) and isinstance(arg.value, (int, float, bool)) and not isinstance(arg.value, str))                      or isinstance(arg, ast.Lambda) or (windowed and isinstance(arg, (ast.Name, ast.BinOp, ast.Attribute)))
                if not ok:
                    raise UnsafeCode(f".{node.func.attr}() argument not allowed — numbers or a lambda only (line {line})")
        elif isinstance(node, ast.alias) and node.asname and node.asname.startswith("_"):
            raise UnsafeCode(f"alias not allowed: {node.asname} (line {line})")


def _child_env(repo_root: str) -> dict:
    env = {"PYTHONPATH": repo_root, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
    for k in ("PATH", "SYSTEMROOT", "LANG", "LC_ALL"):  # needed for the interpreter to start, nothing secret
        if os.getenv(k):
            env[k] = os.environ[k]
    return env


def _limit_resources():  # Linux only (Render)
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
        resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024, 1024 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    except Exception:
        pass


async def run_backtest_sandboxed(code: str, df, repo_root: Path, timeout_s: int = 90) -> dict:
    validate_code(code)
    runner = Path(__file__).parent / "llm_runner.py"
    with tempfile.TemporaryDirectory(prefix="llm_") as work:
        w = Path(work)
        (w / "strategy.py").write_text(code, encoding="utf-8")
        d = df.copy()
        d["ts"] = d["ts"].astype(str)
        d.to_csv(w / "data.csv", index=False)
        tag = secrets.token_hex(16)
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-I", str(runner), str(w), str(repo_root),
            cwd=str(w), env={**_child_env(str(repo_root)), "RAQM_RESULT_TAG": tag},
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            preexec_fn=_limit_resources if os.name == "posix" else None,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except asyncio.TimeoutError:
            proc.kill()
            return {"ok": False, "error": "sandbox timeout"}
    text = out.decode(errors="ignore")
    for line in reversed(text.splitlines()):
        if line.startswith(f"__RESULT_{tag}__"):
            return json.loads(line[len(f"__RESULT_{tag}__"):])
    return {"ok": False, "error": "sandbox crashed", "stderr": err.decode(errors="ignore")[-800:]}
