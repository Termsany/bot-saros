"""`python bot.py …` as the server starts it (development-plan 2.3): the module runs as __main__, which the unit tests
(they `import bot`) never do — a broken entry point, option, import or module alias would only show on the server.
Each strategy runs one paper cycle in a child process, on an exchange that returns no data, with the network blocked
(sitecustomize in the child): it must exit 0, write its state where --state says, and print no traceback."""
import json, os, subprocess, sys, tempfile, textwrap, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent.parent
STRATEGIES = ("trend_daily", "vol_breakout", "rsi2_pullback", "trend_breakout", "listing_short", "momentum_ls", "ratio_trend")

SITE = textwrap.dedent('''
    import socket
    def _no_network(*a, **k): raise OSError("network blocked in test_bot_entrypoint")
    socket.socket.connect = _no_network; socket.create_connection = _no_network
    import ccxt
    class _Empty:
        """An exchange with no markets, no candles and no positions; every write refuses."""
        id = "fake"; markets = {}; symbols = []; options = {}; apiKey = ""; secret = ""
        def __init__(self, *a, **k): pass
        def load_markets(self, *a, **k): return {}
        def fetch_markets(self, *a, **k): return []
        def fetch_tickers(self, *a, **k): return {}
        def fetch_ticker(self, symbol, *a, **k): return {"symbol": symbol, "last": None, "close": None}
        def fetch_ohlcv(self, *a, **k): return []
        def fetch_positions(self, *a, **k): return []
        def fetch_balance(self, *a, **k): return {"total": {}, "free": {}}
        def fetch_open_orders(self, *a, **k): return []
        def market(self, symbol): raise ccxt.BadSymbol(symbol)
        def milliseconds(self): return 0
        def __getattr__(self, name):
            if name.startswith(("create", "cancel", "edit", "set_", "private", "fapiPrivate")):
                raise AssertionError(f"write call {name} in a paper cycle")
            raise AttributeError(name)
    for _n in ("binanceusdm", "binance", "bybit", "okx"): setattr(ccxt, _n, _Empty)
    import sys; print("FAKE-EXCHANGE-LOADED", file=sys.stderr)
''')


class BotEntrypointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); cls.d = Path(cls.td.name)
        (cls.d / "site").mkdir(); (cls.d / "site" / "sitecustomize.py").write_text(SITE, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.td.cleanup()

    def run_bot(self, strategy):
        state = self.d / f"entry-{strategy}.json"
        env = {k: v for k, v in os.environ.items() if not k.startswith(("BINANCE_", "TELEGRAM_", "RAQM_", "ALLOW_LIVE"))}
        env.update(PYTHONPATH=str(self.d / "site"), PYTHONIOENCODING="utf-8", RAQM_RISK_DIR=str(self.d / f"risk-{strategy}"))
        # --state is relative to bot.py's folder, as on the server (state/demo-<s>.json): a path outside it via ../
        rel = os.path.relpath(state, ROOT)
        r = subprocess.run([sys.executable, str(ROOT / "bot.py"), "--once", "--paper", "--strategy", strategy, "--state", rel],
                           cwd=str(self.d), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        return r, state

    def test_every_strategy_starts_and_runs_one_cycle_as_main(self):
        for s in STRATEGIES:
            with self.subTest(strategy=s):
                r, state = self.run_bot(s)
                out = r.stdout + r.stderr
                self.assertIn("FAKE-EXCHANGE-LOADED", out)          # the child ran on the fake, not on Binance
                self.assertEqual(r.returncode, 0, out[-2000:])
                self.assertNotIn("Traceback", out, out[-2000:])
                self.assertNotIn("write call", out)
                if state.exists():
                    self.assertIsInstance(json.loads(state.read_text(encoding="utf-8")), dict)

    def test_a_retired_strategy_and_a_wrong_environment_are_refused_at_start(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("BINANCE_", "RAQM_", "ALLOW_LIVE"))}
        env.update(PYTHONPATH=str(self.d / "site"), PYTHONIOENCODING="utf-8")
        r = subprocess.run([sys.executable, str(ROOT / "bot.py"), "--once", "--paper", "--strategy", "ict"],
                           cwd=str(self.d), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        self.assertNotEqual(r.returncode, 0)
        env["BINANCE_ENV"] = "demo"
        r = subprocess.run([sys.executable, str(ROOT / "bot.py"), "--once", "--live", "--expect-env", "live", "--strategy", "trend_daily"],
                           cwd=str(self.d), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
