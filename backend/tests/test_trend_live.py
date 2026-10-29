"""Daily trend with real orders (Binance USDT-M, one-way): market buy + stop on the exchange, exit on the signal,
reconciliation with the exchange every cycle. Mock exchange — Binance Demo Trading is the next check."""
import os, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
import bot as botmod
from backend.app import oco as oco_mod
from backend.app import risk_manager as riskmgr_mod


class FakeBinance:
    """Enough of ccxt.binanceusdm for the trend's live path."""
    id = "binance"

    def __init__(self, fail_stop=False, fail_close=False, balance=1000.0, min_cost=5.0, hedged=False):
        self.options = {}
        self.orders, self.cancelled, self.positions = [], [], {}
        self.fail_stop, self.fail_close, self.balance, self.min_cost, self.hedged = fail_stop, fail_close, balance, min_cost, hedged
        self.set_leverage = mock.Mock(); self.set_margin_mode = mock.Mock(); self.set_position_mode = mock.Mock()

    def fetch_position_mode(self, symbol=None):
        # Real ccxt's unified key is 'hedged' (confirmed live against Binance Demo Trading:
        # {'info': {'dualSidePosition': False}, 'hedged': False}) — not 'hedgeMode'.
        return {"info": {"dualSidePosition": self.hedged}, "hedged": self.hedged}

    def market(self, sym): return {"contract": True, "linear": True, "inverse": False, "contractSize": 1.0, "limits": {"cost": {"min": self.min_cost}}}
    def amount_to_precision(self, sym, q): return str(round(float(q), 6))
    def price_to_precision(self, sym, p): return str(round(float(p), 6))
    def fetch_balance(self): return {"USDT": {"free": self.balance}}

    def create_order(self, sym, typ, side, qty, price, params):
        params = dict(params or {}); self.orders.append({"symbol": sym, "side": side, "qty": float(qty), "params": params})
        base = sym.split(":")[0]
        if "stopLossPrice" in params:
            if self.fail_stop: raise Exception("binance stop rejected")
            return {"id": "stop-" + params["clientOrderId"], "clientOrderId": params["clientOrderId"], "status": "open"}
        if params.get("reduceOnly"):
            if self.fail_close: raise Exception("network down")
            self.positions[base] = max(0.0, self.positions.get(base, 0.0) - float(qty))
            return {"id": "c", "filled": float(qty), "average": 110.0, "fee": {"cost": abs(float(qty)) * 110.0 * 0.0004}}
        self.positions[base] = self.positions.get(base, 0.0) + float(qty)
        return {"id": "e", "clientOrderId": params.get("clientOrderId"), "filled": float(qty), "average": 100.0, "fee": {"cost": abs(float(qty)) * 100.0 * 0.0004}}

    def fetch_order(self, oid, sym, params=None):
        o = next((o for o in self.orders if "stopLossPrice" in o["params"] and "stop-" + o["params"]["clientOrderId"] == oid), None)
        if o and oid not in self.cancelled: return {"id": oid, "status": "open"}
        raise Exception('binanceusdm {"code":-2013,"msg":"Order does not exist."}')   # what Binance answers

    def fetch_open_orders(self, sym, *a):
        return [{"id": "stop-" + o["params"]["clientOrderId"], "clientOrderId": o["params"]["clientOrderId"]}
                for o in self.orders if "stopLossPrice" in o["params"] and "stop-" + o["params"]["clientOrderId"] not in self.cancelled]

    def cancel_order(self, oid, sym, *a): self.cancelled.append(oid)
    def fetch_positions(self, syms=None):
        return [{"symbol": f"{b}:USDT", "contracts": q} for b, q in self.positions.items() if not syms or b in [s.split(":")[0] for s in syms]]
    def fetch_my_trades(self, sym, since=None, limit=20): return [{"side": "sell", "price": 82.0, "amount": 5.0, "fee": {"cost": 5.0 * 82.0 * 0.0004}}]
    def fetch_funding_history(self, sym, since=None): return []


SIG_ON = {"price": 100.0, "trend": {"on": True, "ts": 1, "size": 1.0}, "in_universe": True, "rank": 1, "total": 0}
SIG_OFF = {"price": 110.0, "trend": {"on": False, "ts": 2, "size": 1.0}, "in_universe": True, "rank": 1, "total": 0}


class TrendLiveTests(unittest.TestCase):
    def setUp(self):
        self._cfg = dict(botmod.CONFIG)
        self._env = os.environ.get("BINANCE_ENV")
        os.environ["BINANCE_ENV"] = "demo"
        self.td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)   # Windows can still hold a file open
        self._paths = (botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH)
        botmod.STATE_PATH = Path(self.td.name) / "state.json"; botmod.LOG_PATH = Path(self.td.name) / "t.log"
        botmod.RISK_PATH = Path(self.td.name) / "risk_state.json"
        # These tests exercise OCO/stop placement and close mechanics, not risk sizing — seed a
        # permissive risk ledger so the Central Risk Manager gate doesn't reject the fixture's
        # (deliberately simple, not risk-tuned) position sizes.
        riskmgr_mod.save_risk_state(botmod.RISK_PATH, riskmgr_mod._default_state({
            "risk_per_trade_pct": 100.0, "max_aggregate_risk_pct": 100.0,
            "max_correlated_risk_pct": 100.0, "max_daily_loss_pct": 100.0, "max_drawdown_pct": 100.0,
        }))
        botmod.CONFIG.update({"paper_trading": False, "market": "future", "leverage": 5, "trade_amount_usdt": 100,
                              "enabled_strategies": ["trend_daily"], "max_open_positions": 10, "use_percent_risk": False})
        botmod._ENTRY_BLOCK["reason"] = ""
        self.state = botmod.load_state()
    def tearDown(self):
        botmod.CONFIG.clear(); botmod.CONFIG.update(self._cfg)
        if self._env is None: os.environ.pop("BINANCE_ENV", None)
        else: os.environ["BINANCE_ENV"] = self._env
        botmod.STATE_PATH, botmod.LOG_PATH, botmod.RISK_PATH = self._paths
        self.td.cleanup()

    def test_entry_buys_then_puts_the_stop_on_the_exchange(self):
        ex = FakeBinance()
        botmod.try_enter("SOL/USDT:USDT", SIG_ON, self.state, ex)
        buy, stop = ex.orders
        self.assertEqual((buy["side"], buy["qty"]), ("buy", 5.0))                       # $100 x5 / $100
        self.assertNotIn("positionSide", buy["params"]); self.assertNotIn("reduceOnly", buy["params"])
        self.assertEqual(stop["side"], "sell"); self.assertTrue(stop["params"]["reduceOnly"])
        self.assertAlmostEqual(stop["params"]["stopLossPrice"], 100 * (1 - 0.8 / 5))    # 84 — before liquidation
        self.assertEqual(len([o for o in ex.orders if "takeProfitPrice" in o["params"]]), 0)   # no target
        pos = self.state["positions"]["SOL/USDT:USDT"]
        self.assertTrue(pos["oco_ids"]["sl"]); self.assertFalse(self.state.get("recovery_required"))
        ex.set_leverage.assert_called_with(5, "SOL/USDT:USDT")

    def test_rejected_stop_closes_at_once(self):
        ex = FakeBinance(fail_stop=True)
        botmod.try_enter("SOL/USDT:USDT", SIG_ON, self.state, ex)
        self.assertNotIn("SOL/USDT:USDT", self.state["positions"])
        self.assertEqual(ex.positions["SOL/USDT"], 0.0)
        self.assertEqual(self.state["history"][-1]["reason"], "الوقف اترفض — قفل فوري")

    def test_rejected_stop_and_failed_close_is_tracked_and_blocks_entries(self):
        ex = FakeBinance(fail_stop=True, fail_close=True)
        botmod.try_enter("SOL/USDT:USDT", SIG_ON, self.state, ex)
        self.assertTrue(self.state["positions"]["SOL/USDT:USDT"]["unprotected"])
        self.assertIn("SOL/USDT:USDT", self.state["recovery_required"])
        n = len(ex.orders)
        botmod.try_enter("ETH/USDT:USDT", {**SIG_ON, "trend": {"on": True, "ts": 9, "size": 1.0}}, self.state, ex)
        self.assertEqual(len(ex.orders), n)                                              # nothing new anywhere

    def test_too_small_for_the_exchange_minimum_sends_nothing(self):
        ex = FakeBinance(min_cost=1000)
        botmod.try_enter("BTC/USDT:USDT", SIG_ON, self.state, ex)
        self.assertEqual(ex.orders, [])

    def test_not_enough_balance_sends_nothing(self):
        ex = FakeBinance(balance=50)
        botmod.try_enter("SOL/USDT:USDT", SIG_ON, self.state, ex)
        self.assertEqual(ex.orders, [])

    def test_trend_off_closes_exact_size_and_cancels_its_stop(self):
        ex = FakeBinance()
        botmod.try_enter("SOL/USDT:USDT", SIG_ON, self.state, ex)
        stop_id = "stop-" + ex.orders[1]["params"]["clientOrderId"]
        botmod.try_enter("SOL/USDT:USDT", SIG_OFF, self.state, ex)
        close = ex.orders[-1]
        self.assertEqual((close["side"], close["qty"]), ("sell", 5.0)); self.assertTrue(close["params"]["reduceOnly"])
        self.assertIn(stop_id, ex.cancelled)
        self.assertNotIn("SOL/USDT:USDT", self.state["positions"])
        h = self.state["history"][-1]; self.assertEqual(h["type"], "live"); self.assertAlmostEqual(h["pnl"], 49.58)

    def test_exit_still_runs_while_entries_are_blocked(self):
        ex = FakeBinance()
        botmod.try_enter("SOL/USDT:USDT", SIG_ON, self.state, ex)
        self.state["recovery_required"] = {"XRP/USDT:USDT": {"reason": "test"}}
        botmod.try_enter("SOL/USDT:USDT", SIG_OFF, self.state, ex)
        self.assertNotIn("SOL/USDT:USDT", self.state["positions"])

    def test_reconcile_records_a_stop_filled_on_the_exchange(self):
        ex = FakeBinance()
        botmod.try_enter("SOL/USDT:USDT", SIG_ON, self.state, ex)
        ex.positions["SOL/USDT"] = 0.0                                                  # the exchange stop filled
        botmod.reconcile_live(self.state, ex)
        self.assertIn("SOL/USDT:USDT", self.state["positions"])                        # one flat answer isn't enough
        botmod.reconcile_live(self.state, ex)
        self.assertNotIn("SOL/USDT:USDT", self.state["positions"])
        h = self.state["history"][-1]; self.assertEqual(h["reason"], "وقف المنصة"); self.assertAlmostEqual(h["exit"], 82.0)

    def test_clean_flat_account_does_not_block_entries(self):
        """A brand-new/clean account with zero open positions returns [] from fetch_positions() —
        that's a normal, valid flat state, not an incomplete read, and must not block the first trade."""
        ex = FakeBinance()   # ex.positions stays empty -> fetch_positions() returns []
        botmod.reconcile_live(self.state, ex)
        self.assertEqual(botmod._ENTRY_BLOCK["reason"], "")
        botmod.try_enter("SOL/USDT:USDT", SIG_ON, self.state, ex)
        self.assertIn("SOL/USDT:USDT", self.state["positions"])
        self.assertEqual(len(ex.orders), 2)   # entry + stop, not blocked

    def test_unknown_position_blocks_new_entries(self):
        ex = FakeBinance(); ex.positions["DOGE/USDT"] = 100.0                           # opened by hand on the same account
        botmod.reconcile_live(self.state, ex)
        botmod.try_enter("SOL/USDT:USDT", SIG_ON, self.state, ex)
        self.assertEqual(ex.orders, [])
        self.assertIn("DOGE", botmod._ENTRY_BLOCK["reason"])

    def test_risk_gate_blocks_an_oversized_live_entry(self):
        riskmgr_mod.save_risk_state(botmod.RISK_PATH, riskmgr_mod._default_state({
            "risk_per_trade_pct": 0.01, "max_aggregate_risk_pct": 100.0,
            "max_correlated_risk_pct": 100.0, "max_daily_loss_pct": 100.0, "max_drawdown_pct": 100.0,
        }))
        ex = FakeBinance()
        botmod.try_enter("SOL/USDT:USDT", SIG_ON, self.state, ex)
        self.assertEqual(ex.orders, [])
        self.assertNotIn("SOL/USDT:USDT", self.state["positions"])

    def test_successful_live_entry_registers_open_risk_ledger(self):
        ex = FakeBinance()
        botmod.try_enter("SOL/USDT:USDT", SIG_ON, self.state, ex)
        self.assertIn("SOL/USDT:USDT", self.state["positions"])
        ledger = riskmgr_mod.load_risk_state(botmod.RISK_PATH)
        self.assertIn("trend_daily:SOL/USDT:USDT", ledger["open_risk"])
        row = ledger["open_risk"]["trend_daily:SOL/USDT:USDT"]
        self.assertEqual(row["side"], "long"); self.assertGreater(row["risk_usdt"], 0)

    def test_closing_a_live_position_releases_the_risk_ledger(self):
        ex = FakeBinance()
        botmod.try_enter("SOL/USDT:USDT", SIG_ON, self.state, ex)
        self.assertIn("trend_daily:SOL/USDT:USDT", riskmgr_mod.load_risk_state(botmod.RISK_PATH)["open_risk"])
        ex.positions["SOL/USDT"] = 0.0
        botmod.reconcile_live(self.state, ex); botmod.reconcile_live(self.state, ex)
        self.assertNotIn("SOL/USDT:USDT", self.state["positions"])
        self.assertNotIn("trend_daily:SOL/USDT:USDT", riskmgr_mod.load_risk_state(botmod.RISK_PATH)["open_risk"])

    def test_tripped_kill_switch_blocks_new_entries_via_reconcile(self):
        ex = FakeBinance()
        riskmgr_mod.trip_kill_switch(botmod.RISK_PATH, "pre-tripped for this test")
        botmod.reconcile_live(self.state, ex)
        self.assertIn("kill switch", botmod._ENTRY_BLOCK["reason"])
        botmod.try_enter("SOL/USDT:USDT", SIG_ON, self.state, ex)
        self.assertEqual(ex.orders, [])

    def test_missing_equity_blocks_new_entries_via_reconcile(self):
        ex = FakeBinance()
        ex.fetch_balance = lambda: (_ for _ in ()).throw(Exception("network down"))
        botmod.reconcile_live(self.state, ex)
        self.assertIn("equity", botmod._ENTRY_BLOCK["reason"])

    def test_restart_after_a_fresh_entry_does_not_force_recovery(self):
        """A bare restart right after opening a live position must not trip recovery_required —
        funding_verified is only ever set at close (_refresh_funding_evidence), never at entry, so
        requiring it at load time would flag every healthy freshly-opened position on every restart."""
        ex = FakeBinance()
        botmod.try_enter("SOL/USDT:USDT", SIG_ON, self.state, ex)
        botmod.save_state(self.state)
        reloaded = botmod.load_state()
        self.assertEqual(reloaded["recovery_required"], {})
        self.assertIn("SOL/USDT:USDT", reloaded["positions"])


class LiveSymbolResolutionTests(unittest.TestCase):
    """CONFIG['symbols'] (trend_daily/wave_flats/ict's fixed list) is bare 'BTC/USDT'; Binance USDT-M
    futures' real ccxt market key is 'BTC/USDT:USDT'. Discovered live against Binance Demo Trading:
    ex.market('BTC/USDT') raised 'does not have market symbol', tripping recovery_required on the very
    first live entry attempt for any fixed-list strategy."""

    class _MarketsOnly:
        def __init__(self, markets): self.markets = markets

    def test_bare_symbol_resolves_to_the_colon_suffixed_perpetual_key(self):
        ex = self._MarketsOnly({"BTC/USDT:USDT": {}, "ETH/USDT:USDT": {}})
        self.assertEqual(botmod._resolve_live_symbol(ex, "BTC/USDT"), "BTC/USDT:USDT")

    def test_already_correct_symbol_is_left_unchanged(self):
        ex = self._MarketsOnly({"SOL/USDT:USDT": {}})
        self.assertEqual(botmod._resolve_live_symbol(ex, "SOL/USDT:USDT"), "SOL/USDT:USDT")

    def test_unresolvable_symbol_is_returned_as_is_not_dropped(self):
        ex = self._MarketsOnly({"BTC/USDT:USDT": {}})
        self.assertEqual(botmod._resolve_live_symbol(ex, "NOPE/USDT"), "NOPE/USDT")

    def test_resolves_the_whole_symbols_and_allowed_list(self):
        ex = self._MarketsOnly({"BTC/USDT:USDT": {}, "ETH/USDT:USDT": {}})
        symbols, allowed = botmod._resolve_live_symbols(ex, ["BTC/USDT", "ETH/USDT"], {"BTC/USDT"})
        self.assertEqual(symbols, ["BTC/USDT:USDT", "ETH/USDT:USDT"])
        self.assertEqual(allowed, {"BTC/USDT:USDT"})

    def test_allowed_none_stays_none(self):
        ex = self._MarketsOnly({"BTC/USDT:USDT": {}})
        _, allowed = botmod._resolve_live_symbols(ex, ["BTC/USDT"], None)
        self.assertIsNone(allowed)


class HedgeModeVerificationTests(unittest.TestCase):
    """ensure_futures_setup's read-back verification of ex.fetch_position_mode() — previously
    untested by any FakeBinance double, so a key-name bug (checking 'hedgeMode' instead of ccxt's
    real 'hedged' key) went unnoticed: it always fell back to the whole non-empty dict, so
    bool(mode) was always True, meaning EVERY live entry attempt on a real account — hedged or
    not — raised 'still in Hedge Mode', discovered live against Binance Demo Trading."""

    def setUp(self):
        self._cfg = dict(botmod.CONFIG)
        botmod.CONFIG.update({"market": "future", "leverage": 5, "margin_type": "ISOLATED"})

    def tearDown(self):
        botmod.CONFIG.clear(); botmod.CONFIG.update(self._cfg)

    def test_one_way_account_does_not_raise(self):
        ex = FakeBinance(hedged=False)
        botmod.ensure_futures_setup(ex, "BTC/USDT:USDT")   # must not raise

    def test_genuinely_hedged_account_still_raises(self):
        ex = FakeBinance(hedged=True)
        with self.assertRaises(RuntimeError) as ctx:
            botmod.ensure_futures_setup(ex, "BTC/USDT:USDT")
        self.assertIn("Hedge Mode", str(ctx.exception))

    def test_set_position_mode_is_skipped_once_already_one_way(self):
        """set_position_mode is account-wide, not per-symbol. Binance rejects a redundant call with
        -4067 'Position side cannot be changed if there exists open orders' as soon as ANY symbol has
        an open position/order — discovered live right after a real first entry succeeded. Once
        fetch_position_mode confirms one-way, the call must be skipped entirely, not retried."""
        ex = FakeBinance(hedged=False)
        ex.set_position_mode = mock.Mock(side_effect=Exception(
            'binanceusdm {"code":-4067,"msg":"Position side cannot be changed if there exists open orders."}'))
        botmod.ensure_futures_setup(ex, "ADA/USDT:USDT")   # must not raise: never calls set_position_mode
        ex.set_position_mode.assert_not_called()


class StartupGateTests(unittest.TestCase):
    def _run(self, *args, env=None):
        e = {k: v for k, v in os.environ.items() if k not in ("ALLOW_LIVE_TRADING", "BINANCE_ENV")}
        e.update(env or {}); e["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run([sys.executable, str(ROOT / "bot.py"), *args], capture_output=True, text=True, env=e,
                              cwd=tempfile.gettempdir(), timeout=60, encoding="utf-8")

    def test_live_requires_a_known_live_ready_strategy(self):
        r = self._run("--live", "--strategy", "no_such_strategy", "--once", env={"BINANCE_ENV": "demo"})
        self.assertNotEqual(r.returncode, 0); self.assertIn("no_such_strategy", r.stderr)

    def test_live_now_works_for_every_strategy_argparse_gate(self):
        # Use the default (unset) BINANCE_ENV so each run fails fast on the ALLOW_LIVE_TRADING
        # check (like test_real_money_needs_the_server_switch) instead of reaching the network —
        # this only proves the strategy-name gate itself no longer refuses these names.
        for strat in ("trend_daily", "vol_breakout", "rsi2_pullback",
                      "trend_breakout", "listing_short", "momentum_ls", "ratio_trend"):
            r = self._run("--live", "--strategy", strat, "--once")
            self.assertNotIn("--live مش متاح", r.stderr, msg=f"{strat}: {r.stderr}")
            self.assertIn("ALLOW_LIVE_TRADING", r.stderr, msg=f"{strat}: {r.stderr}")

    def test_retired_strategies_are_refused(self):
        for strat in ("ict", "wave_flats"):
            for mode in ("--live", "--paper"):
                r = self._run(mode, "--strategy", strat, "--once", env={"BINANCE_ENV": "demo"})
                self.assertNotEqual(r.returncode, 0, msg=f"{strat} {mode}"); self.assertIn(strat, r.stderr)

    def test_live_without_a_strategy_is_refused(self):
        # no --strategy falls back to the "ict" ensemble, which is not a live strategy any more
        r = self._run("--live", "--once", env={"BINANCE_ENV": "demo"})
        self.assertNotEqual(r.returncode, 0); self.assertIn("--live", r.stderr)

    def test_real_money_needs_the_server_switch(self):
        r = self._run("--live", "--strategy", "trend_daily", "--once")
        self.assertNotEqual(r.returncode, 0); self.assertIn("ALLOW_LIVE_TRADING", r.stderr)


if __name__ == "__main__":
    unittest.main()


class ManualCloseTests(TrendLiveTests):
    RID = "0123456789abcdef0123456789abcdef"

    def _request(self, ipc, symbol, age=0, rid=None, at=None):
        import json, time
        (ipc / "commands").mkdir(parents=True, exist_ok=True)
        (ipc / "commands" / "close-x.json").write_text(json.dumps({"id": rid or self.RID, "symbol": symbol,
                                                                   "at_epoch": time.time() - age if at is None else at, "by": "admin"}))

    def test_site_close_closes_records_and_holds_the_coin(self):
        ex = FakeBinance(); ipc = Path(self.td.name) / "ipc"
        botmod.try_enter("SOL/USDT:USDT", SIG_ON, self.state, ex)
        self._request(ipc, "SOL/USDT")
        with mock.patch.dict(os.environ, {"RAQM_IPC_DIR": str(ipc)}):
            botmod.process_manual_closes(self.state, ex, {"SOL/USDT:USDT": 105.0})
        import json
        res = json.loads((ipc / "results" / f"{self.RID}.json").read_text(encoding="utf-8"))
        self.assertTrue(res["ok"]); self.assertNotIn("SOL/USDT:USDT", self.state["positions"])
        self.assertEqual(self.state["history"][-1]["reason"], "قفل يدوي من الموقع")
        self.assertFalse(list((ipc / "commands").glob("*.json")))
        n = len(ex.orders)                                   # trend still on, next day: no re-buy while held
        botmod.try_enter("SOL/USDT:USDT", {**SIG_ON, "trend": {"on": True, "ts": 5, "size": 1.0}}, self.state, ex)
        self.assertEqual(len(ex.orders), n)
        botmod.try_enter("SOL/USDT:USDT", {**SIG_OFF, "trend": {"on": False, "ts": 6, "size": 1.0}}, self.state, ex)
        botmod.try_enter("SOL/USDT:USDT", {**SIG_ON, "trend": {"on": True, "ts": 7, "size": 1.0}}, self.state, ex)
        self.assertGreater(len(ex.orders), n)                # off then on again: a new signal may buy

    def test_old_request_is_dropped_not_executed(self):
        ex = FakeBinance(); ipc = Path(self.td.name) / "ipc"
        botmod.try_enter("SOL/USDT:USDT", SIG_ON, self.state, ex)
        self._request(ipc, "SOL/USDT", age=3600)
        with mock.patch.dict(os.environ, {"RAQM_IPC_DIR": str(ipc)}):
            botmod.process_manual_closes(self.state, ex, {})
        self.assertIn("SOL/USDT:USDT", self.state["positions"])


class ManualCloseHardeningTests(ManualCloseTests):
    def test_request_id_cannot_name_a_file_outside_results(self):
        ex = FakeBinance(); ipc = Path(self.td.name) / "ipc"
        botmod.try_enter("SOL/USDT:USDT", SIG_ON, self.state, ex)
        target = Path(self.td.name) / "state_victim"
        self._request(ipc, "SOL/USDT", rid=str(target))                                 # an absolute path as the id
        with mock.patch.dict(os.environ, {"RAQM_IPC_DIR": str(ipc)}):
            botmod.process_manual_closes(self.state, ex, {})
        self.assertFalse(target.with_suffix(".json").exists())
        self.assertIn("SOL/USDT:USDT", self.state["positions"])                          # refused, nothing closed
        self.assertFalse(list((ipc / "commands").glob("*.json")))

    def test_future_timestamp_does_not_dodge_the_expiry(self):
        import time
        ex = FakeBinance(); ipc = Path(self.td.name) / "ipc"
        botmod.try_enter("SOL/USDT:USDT", SIG_ON, self.state, ex)
        self._request(ipc, "SOL/USDT", at=time.time() + 10 * 86400)
        with mock.patch.dict(os.environ, {"RAQM_IPC_DIR": str(ipc)}):
            botmod.process_manual_closes(self.state, ex, {})
        self.assertIn("SOL/USDT:USDT", self.state["positions"])

    def test_status_write_replaces_a_planted_link_instead_of_writing_through_it(self):
        ipc = Path(self.td.name) / "ipc"; ipc.mkdir()
        victim = Path(self.td.name) / "victim.txt"; victim.write_text("keep me")
        try: (ipc / "live_status.json").symlink_to(victim)
        except (OSError, NotImplementedError): self.skipTest("no symlinks here (Windows without privilege)")
        botmod._write_json_atomic(ipc / "live_status.json", {"x": 1})
        self.assertEqual(victim.read_text(), "keep me")


class ExitLevelTests(unittest.TestCase):
    def test_exit_level_is_the_trend_boundary(self):
        import random, strategies_trend as st
        random.seed(3); c = [100.0]
        for _ in range(300): c.append(c[-1] * (1 + random.gauss(0.001, 0.03)))
        lvl = st.exit_level(c)
        self.assertTrue(st.trend_on(c + [lvl * 1.001], len(c)))
        self.assertFalse(st.trend_on(c + [lvl * 0.999], len(c)))


class UniverseFilterTests(unittest.TestCase):
    """The paper bot ranks Bybit's market, the live bot Binance's: the coin filter must keep coins on both."""
    def _ex(self, ex_id, info):
        ex = mock.Mock(); ex.id = ex_id
        ex.markets = {"SOL/USDT:USDT": {"swap": True, "linear": True, "quote": "USDT", "settle": "USDT", "base": "SOL", "active": True, "info": info}}
        ex.fetch_tickers.return_value = {"SOL/USDT:USDT": {"quoteVolume": 1e9}}
        ex.fetch_ohlcv.return_value = [[0, 1, 1, 1, 100.0, 1000.0]] * 200
        return ex

    def test_bybit_linear_perpetual_is_kept(self):
        botmod._universe.update(key=None, symbols=[])
        self.assertEqual(botmod.volume_universe(self._ex("bybit", {"contractType": "LinearPerpetual", "symbolType": ""}), 10), ["SOL/USDT:USDT"])

    def test_binance_coin_perpetual_kept_index_dropped(self):
        botmod._universe.update(key=None, symbols=[])
        self.assertEqual(botmod.volume_universe(self._ex("binanceusdm", {"contractType": "PERPETUAL", "underlyingType": "COIN"}), 10), ["SOL/USDT:USDT"])
        botmod._universe.update(key=None, symbols=[])
        self.assertEqual(botmod.volume_universe(self._ex("binanceusdm", {"contractType": "PERPETUAL", "underlyingType": "INDEX"}), 10), [])
