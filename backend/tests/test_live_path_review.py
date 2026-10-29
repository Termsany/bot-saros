"""Fixes from the pre-production review of the single-leg live path (2026-10-29).

1. The portfolio strategies ran live on the keyless public client — no order, balance or position call could work.
2. vol_breakout / rsi2_pullback / trend_breakout passed notional as margin: leverage applied twice.
3. A fixed client order id per symbol: trade #2 looked up trade #1's filled order.
4. An entry with an unclear outcome that shows on the exchange was left with no stop and no alert."""
import os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).resolve().parent))
import bot as botmod
from backend.app import risk_manager as riskmgr_mod
from test_trend_live import FakeBinance, SIG_ON

SYM = "SOL/USDT:USDT"


class Base(unittest.TestCase):
    def setUp(self):
        self._cfg = dict(botmod.CONFIG); self._env = dict(os.environ); os.environ["BINANCE_ENV"] = "demo"
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._saved = (botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH, botmod.ENTRY_RECHECK_S, botmod.FILL_LOOKUP_WAITS)
        botmod.STATE_PATH = Path(self.td.name) / "state.json"; botmod.LOG_PATH = Path(self.td.name) / "t.log"
        botmod.RISK_PATH = Path(self.td.name) / "risk_state.json"; botmod.ENTRY_RECHECK_S = 0; botmod.FILL_LOOKUP_WAITS = (0.0,)
        self.fresh_risk()
        botmod.CONFIG.update({"paper_trading": False, "market": "future", "leverage": 2, "trade_amount_usdt": 100,
                              "enabled_strategies": ["trend_daily"], "max_open_positions": 10, "use_percent_risk": False})
        botmod._ENTRY_BLOCK["reason"] = ""
        self.notified = []
        for target, value in (("notify", self.notified.append), ("_live_activation_gate", lambda s: (True, ""))):
            p = mock.patch.object(botmod, target, value); p.start(); self.addCleanup(p.stop)
        self.state = botmod.load_state()

    def fresh_risk(self):
        riskmgr_mod.save_risk_state(botmod.RISK_PATH, riskmgr_mod._default_state({
            "risk_per_trade_pct": 100.0, "max_aggregate_risk_pct": 100.0, "max_correlated_risk_pct": 100.0,
            "max_daily_loss_pct": 100.0, "max_drawdown_pct": 100.0}))

    def tearDown(self):
        botmod.CONFIG.clear(); botmod.CONFIG.update(self._cfg)
        os.environ.clear(); os.environ.update(self._env)
        (botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH, botmod.ENTRY_RECHECK_S, botmod.FILL_LOOKUP_WAITS) = self._saved
        getattr(botmod, "_strategy_ex", {}).clear(); botmod._ENTRY_BLOCK["reason"] = ""
        self.td.cleanup()


class StrategyExchangeTests(Base):
    def test_paper_uses_the_public_market(self):
        botmod.CONFIG["paper_trading"] = True
        self.assertFalse(botmod.strategy_exchange().apiKey)

    def test_live_uses_the_keyed_account_with_public_market_data(self):
        os.environ.update(BINANCE_API_KEY="k", BINANCE_SECRET="s")
        ex = botmod.strategy_exchange()
        self.assertEqual(ex.apiKey, "k")
        self.assertIn("demo", str(ex.urls["api"]))                               # BINANCE_ENV=demo is honoured
        public = botmod._strategy_ex["public"]
        self.assertFalse(public.apiKey)
        for name in botmod.MARKET_DATA_METHODS:
            self.assertEqual(getattr(ex, name).__self__, public, name)          # candles and prices: the real market
        self.assertIs(botmod.strategy_exchange(), ex)

    def test_live_without_keys_stops_the_bot(self):
        os.environ.pop("BINANCE_API_KEY", None); os.environ.pop("BINANCE_SECRET", None)
        with self.assertRaises(SystemExit): botmod.strategy_exchange()

    def test_every_portfolio_strategy_runs_on_it(self):
        sentinel = object()
        for strat, fn in (("vol_breakout", "run_once_breakout"), ("rsi2_pullback", "run_once_rsi2"),
                          ("trend_breakout", "run_once_tbreak"), ("ratio_trend", "run_once_ratio"),
                          ("momentum_ls", "run_once_momentum"), ("listing_short", "run_once_listing")):
            botmod.CONFIG["enabled_strategies"] = [strat]
            with mock.patch.object(botmod, "strategy_exchange", return_value=sentinel), mock.patch.object(botmod, fn) as run:
                botmod.run_once()
            run.assert_called_once_with(sentinel)


class ReconcileEachCycleTests(Base):
    def test_live_cycle_reconciles_and_stops_when_blocked(self):
        for fn in ("run_once_breakout", "run_once_rsi2", "run_once_tbreak"):
            ex = mock.Mock()
            def block(state, ex): botmod._ENTRY_BLOCK["reason"] = "unknown position on the exchange"
            with mock.patch.object(botmod, "reconcile_live", side_effect=block) as rec:
                getattr(botmod, fn)(ex)
            rec.assert_called_once(); ex.fetch_ohlcv.assert_not_called(); ex.fetch_ticker.assert_not_called()
            botmod._ENTRY_BLOCK["reason"] = ""


class BreakoutMarket:
    """A steady uptrend: the last closed candle breaks the 20-day high in a stage-2 trend."""
    def fetch_ohlcv(self, sym, tf, limit=None):
        return [[i * 86_400_000, 100.0 + i, 100.0 + i, 99.0 + i, 100.0 + i, 1e6] for i in range(216)]
    def fetch_ticker(self, sym): return {"last": 400.0}


class LeverageAppliedOnceTests(Base):
    def test_trend_breakout_passes_margin_not_notional(self):
        seen = []
        with mock.patch.object(botmod, "reconcile_live"), mock.patch.object(botmod, "volume_universe", return_value=[SYM]), \
             mock.patch.object(botmod, "_single_leg_live_entry", side_effect=lambda ex, st, sym, side, margin, *a, **k: seen.append(margin)):
            botmod.run_once_tbreak(BreakoutMarket())
        self.assertEqual(seen, [100.0])                     # $100 margin; place_order makes it $200 at x2

    def test_live_and_paper_size_match(self):
        ex = FakeBinance()
        pos = botmod._single_leg_live_entry(ex, self.state, SYM, "long", botmod.position_size(100.0, ex), 100.0, 60.0, None, "vol_breakout")
        self.assertAlmostEqual(pos["qty"], 2.0)             # $100 x2 / $100 — what the paper bot opens


class FreshClientIdTests(Base):
    def test_single_leg_ids_differ_per_attempt(self):
        ids = []
        for _ in range(2):
            st = botmod.load_state(); st["positions"] = {}; self.fresh_risk()
            ids.append(botmod._single_leg_live_entry(FakeBinance(), st, SYM, "long", 100.0, 100.0, 60.0, None, "rsi2_pullback", {"x": 1})["clientOrderId"])
        self.assertNotEqual(*ids)

    def test_trend_ids_differ_per_attempt(self):
        ids = []
        for _ in range(2):
            self.fresh_risk(); st = botmod.load_state(); st.update(positions={}, last_trade={}, trend_seen={})
            botmod.try_enter(SYM, SIG_ON, st, FakeBinance())
            ids.append(st["positions"][SYM]["clientOrderId"])
        self.assertNotEqual(*ids)


class SilentFill(FakeBinance):
    """The entry fills on the exchange but its fill can't be confirmed (no filled qty, no trades yet)."""
    def create_order(self, sym, typ, side, qty, price, params):
        o = super().create_order(sym, typ, side, qty, price, params)
        if "stopLossPrice" not in params and not params.get("reduceOnly"):
            return {"id": "e9", "clientOrderId": params.get("clientOrderId"), "filled": None, "average": None, "status": "new"}
        return o
    def fetch_my_trades(self, sym, since=None, limit=20, params=None): return []
    def fetch_order(self, oid, sym, params=None):
        if params and params.get("origClientOrderId"): return {"status": "new", "filled": 0}
        return super().fetch_order(oid, sym)


class UnrecordedEntryProtectionTests(Base):
    def stops(self, ex): return [o for o in ex.orders if "stopLossPrice" in o["params"]]

    def test_single_leg_gets_an_emergency_stop_and_an_alert(self):
        ex = SilentFill()
        self.assertIsNone(botmod._single_leg_live_entry(ex, self.state, SYM, "long", 100.0, 100.0, 60.0, None, "rsi2_pullback"))
        stop, = self.stops(ex)
        self.assertEqual((stop["side"], stop["qty"], stop["params"]["stopLossPrice"]), ("sell", 2.0, 60.0))
        self.assertTrue(stop["params"]["reduceOnly"])
        rec = self.state["recovery_required"][SYM]
        self.assertTrue(rec["emergency_stop"]); self.assertEqual(rec["qty"], 2.0)
        self.assertTrue(botmod._ENTRY_BLOCK["reason"]); self.assertTrue(self.notified)

    def test_flat_failure_places_no_stop(self):
        ex = SilentFill(); ex.create_order = mock.Mock(side_effect=RuntimeError("margin is insufficient"))
        ex.fetch_order = mock.Mock(side_effect=Exception('{"code":-2013,"msg":"Order does not exist."}'))
        botmod._single_leg_live_entry(ex, self.state, SYM, "long", 100.0, 100.0, 60.0, None, "rsi2_pullback")
        self.assertEqual(self.stops(ex), []); self.assertNotIn(SYM, self.state.get("recovery_required", {}))

    def test_trend_gets_an_emergency_stop(self):
        botmod.CONFIG["leverage"] = 5
        ex = SilentFill()
        botmod.try_enter(SYM, SIG_ON, self.state, ex)
        stop, = self.stops(ex)
        self.assertEqual((stop["side"], stop["qty"]), ("sell", 5.0)); self.assertTrue(stop["params"]["reduceOnly"])
        self.assertTrue(self.state["recovery_required"][SYM]["emergency_stop"]); self.assertTrue(self.notified)


if __name__ == "__main__":
    unittest.main()
