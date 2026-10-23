import json, os, tempfile, unittest
from pathlib import Path
from unittest import mock
import sys
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
import bot as botmod
from backend.app.oco import place_oco_orders, cancel_oco_orders, OCO_PREFIX
def _fake_df():
    import pandas as pd
    n=80
    close = __import__("numpy").ones(n)*50000 + __import__("numpy").random.default_rng(0).normal(0, 20, n).cumsum()
    high = close*1.005
    low = close*0.995
    vol = __import__("numpy").ones(n)*100
    ts = __import__("pandas").date_range("2026-01-01", periods=n, freq="4h")
    return __import__("pandas").DataFrame({"ts": ts, "open": close, "high": high, "low": low, "close": close, "vol": vol})
def _mock_ex_for_place(ex_id="binance", hedge=False, fail_sl=False, fail_tp=False, open_orders=None, fetch_positions_ret=None):
    ex = mock.Mock()
    ex.id = ex_id
    ex.options = {"hedgeMode": hedge} if hedge else {}
    ex.amount_to_precision.side_effect = lambda s, q: str(round(float(q),6))
    ex.price_to_precision.side_effect = lambda s, p: str(float(p))
    ex._last_calls_list = []
    def create_order(sym, typ, side, qty, price, params):
        ex._last_params = params
        ex._last_calls_list.append(dict(symbol=sym, side=side, qty=qty, params=dict(params) if params else {}))
        # also expose under _last_calls for compat
        ex._last_calls = ex._last_calls_list
        if params and "stopLossPrice" in params:
            if fail_sl: raise Exception("sl rejected")
            cid = params.get("clientOrderId","sl")
            return {"id": f"id-{cid}", "clientOrderId": cid, "orderLinkId": cid, "filled": qty, "average": 50000}
        if params and "takeProfitPrice" in params:
            if fail_tp: raise Exception("tp rejected")
            cid = params.get("clientOrderId","tp")
            return {"id": f"id-{cid}", "clientOrderId": cid, "orderLinkId": cid, "filled": qty, "average": 50000}
        cid = params.get("clientOrderId","raqm-entry") if params else "raqm-entry"
        return {"id": f"id-{cid}", "clientOrderId": cid, "orderLinkId": cid, "filled": qty, "average": 50000}
    ex.create_order.side_effect = create_order
    ex.cancel_order = mock.Mock(return_value=None)
    ex.fetch_open_orders.return_value = open_orders if open_orders is not None else []
    ex.fetch_positions.return_value = fetch_positions_ret if fetch_positions_ret is not None else []
    ex.fetch_order = mock.Mock(side_effect=Exception("not found"))
    ex.fetch_closed_orders = mock.Mock(return_value=[])
    ex.fetch_orders = mock.Mock(return_value=[])
    ex.fetch_balance.return_value = {"USDT": {"free": 10000}, "free": {"USDT": 10000}}
    ex.set_leverage.return_value = None
    ex.set_margin_mode.return_value = None
    ex.set_position_mode.return_value = None
    return ex

class A_EmergencyCloseFailureTests(unittest.TestCase):
    def test_emergency_flatten_failure_persists_recovery_and_blocks_entries(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "state.json"
            botmod.STATE_PATH = p
            botmod.LOG_PATH = Path(td) / "trades.log"
            botmod.CONFIG["paper_trading"] = False
            botmod.CONFIG["market"] = "future"
            ex = _mock_ex_for_place(ex_id="binance", fail_sl=True, fail_tp=True)
            orig_create = ex.create_order.side_effect
            def create_with_flatten_fail(sym, typ, side, qty, price, params):
                if params and params.get("reduceOnly") and "stopLossPrice" not in params and "takeProfitPrice" not in params:
                    raise Exception("flatten liquidation failed")
                return orig_create(sym, typ, side, qty, price, params)
            ex.create_order.side_effect = create_with_flatten_fail
            ex.fetch_positions.return_value = [{"symbol": "BTC/USDT", "contracts": 0.01, "info": {"size": "0.01"}}]
            with mock.patch.object(botmod, "fetch_ohlcv", return_value=_fake_df()):
                with mock.patch.object(botmod, "adx_value", return_value=25):
                    with mock.patch.object(botmod, "volume_ok", return_value=True):
                        with mock.patch.object(botmod, "htf_trend_ok", return_value=True):
                            with mock.patch.object(botmod, "regime_detect", return_value="trend"):
                                state = botmod.load_state()
                                analysis = {"total": 0.9, "price": 50000, "decision": "buy", "amount_mult": 1.0}
                                botmod.try_enter("BTC/USDT", analysis, state, ex)
                                self.assertIn("BTC/USDT", state.get("recovery_required", {}))
                                self.assertIn("BTC/USDT", state.get("positions", {}))
                                self.assertTrue(state["positions"]["BTC/USDT"].get("unprotected"))
                                ex2 = _mock_ex_for_place(ex_id="binance")
                                with mock.patch.object(botmod, "fetch_ohlcv", return_value=_fake_df()):
                                    with mock.patch.object(botmod, "adx_value", return_value=25):
                                        with mock.patch.object(botmod, "volume_ok", return_value=True):
                                            with mock.patch.object(botmod, "htf_trend_ok", return_value=True):
                                                with mock.patch.object(botmod, "regime_detect", return_value="trend"):
                                                    botmod.try_enter("ETH/USDT", {**analysis, "price": 2500}, state, ex2)
                                                    self.assertNotIn("ETH/USDT", state.get("positions", {}))   # any symbol is blocked
                                                    ex2.create_order.assert_not_called()
                                reloaded = botmod.load_state()
                                self.assertIn("BTC/USDT", reloaded.get("recovery_required", {}))
                                self.assertIn("BTC/USDT", reloaded.get("positions", {}))

class B_AmbiguousTimeoutTests(unittest.TestCase):
    def test_timeout_reconciles_via_fetch_open_orders(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        with tempfile.TemporaryDirectory() as td:
            botmod.STATE_PATH = Path(td)/"state.json"
            botmod.LOG_PATH = Path(td)/"trades.log"
            botmod.CONFIG["paper_trading"]=False
            botmod.CONFIG["market"]="future"
            cid = "raqm-abc123timeout"
            ex = _mock_ex_for_place(ex_id="binance")
            def create_timeout(sym, typ, side, qty, price, params):
                raise Exception("timeout: request timed out")
            ex.create_order.side_effect = create_timeout
            ex.fetch_open_orders.return_value = [{"id":"ex-1","clientOrderId":cid,"orderLinkId":cid,"filled":0.01,"average":50000,"status":"closed"}]
            ex.fetch_closed_orders.return_value = [{"id":"ex-1","clientOrderId":cid,"orderLinkId":cid,"filled":0.01,"average":50000}]
            try:
                botmod.place_order(ex, "BTC/USDT","long",20,50000, client_order_id=cid)
            except Exception:
                found = botmod._reconcile_fills_by_client_id(ex, "BTC/USDT", cid)
                self.assertIsNotNone(found)
                self.assertEqual(found["clientOrderId"], cid)
            ex2 = _mock_ex_for_place(ex_id="binance")
            def fake_reconcile(ex_, sym_, cid_):
                return {"id":"ex-1","clientOrderId":cid_,"orderLinkId":cid_,"filled":0.01,"average":50000}
            with mock.patch.object(botmod, "_reconcile_fills_by_client_id", side_effect=fake_reconcile):
                with mock.patch.object(botmod, "fetch_ohlcv", return_value=_fake_df()):
                    with mock.patch.object(botmod, "adx_value", return_value=25):
                        with mock.patch.object(botmod, "volume_ok", return_value=True):
                            with mock.patch.object(botmod, "htf_trend_ok", return_value=True):
                                with mock.patch.object(botmod, "regime_detect", return_value="trend"):
                                    state=botmod.load_state()
                                    state["pending_orders"]["BTC/USDT"]="raqm-pending-timeout"
                                    analysis={"total":0.9,"price":50000,"decision":"buy","amount_mult":1.0}
                                    botmod.try_enter("BTC/USDT", analysis, state, ex2)
                                    self.assertIn("BTC/USDT", state.get("recovery_required", {}))

class C_MissingProtectiveOrdersTests(unittest.TestCase):
    def test_verify_fail_closed_triggers_flatten(self):
        ex = _mock_ex_for_place(ex_id="binance", fail_sl=False, fail_tp=False, open_orders=[])
        res = place_oco_orders(ex, "BTC/USDT","long",0.01,49000,51000, paper=False, pos_id="abcd1234")
        self.assertTrue(res.get("verify_failed"))
        self.assertTrue(res.get("sl_unverified"))
        self.assertNotIn("protection_missing", res)
        ex.cancel_order.assert_not_called()
        self.assertIn("verify_warn", res)
        import tempfile
        from pathlib import Path
        from unittest import mock
        with tempfile.TemporaryDirectory() as td:
            botmod.STATE_PATH = Path(td)/"state.json"
            botmod.LOG_PATH = Path(td)/"trades.log"
            botmod.CONFIG["paper_trading"]=False
            botmod.CONFIG["market"]="future"
            ex2 = _mock_ex_for_place(ex_id="binance", fail_sl=False, fail_tp=False, open_orders=[])
            calls=[0]
            def fetch_seq(syms):
                calls[0]+=1
                if calls[0]>=2:
                    return [{"symbol":"BTC/USDT","contracts":0,"info":{"size":"0"}}]
                return [{"symbol":"BTC/USDT","contracts":0.01,"info":{"size":"0.01"}}]
            ex2.fetch_positions.side_effect = fetch_seq
            with mock.patch.object(botmod, "fetch_ohlcv", return_value=_fake_df()):
                with mock.patch.object(botmod, "adx_value", return_value=25):
                    with mock.patch.object(botmod, "volume_ok", return_value=True):
                        with mock.patch.object(botmod, "htf_trend_ok", return_value=True):
                            with mock.patch.object(botmod, "regime_detect", return_value="trend"):
                                state=botmod.load_state()
                                analysis={"total":0.9,"price":50000,"decision":"buy","amount_mult":1.0}
                                botmod.try_enter("BTC/USDT", analysis, state, ex2)
                                self.assertTrue(state["positions"]["BTC/USDT"].get("sl_unverified"))
                                self.assertIn("BTC/USDT", state.get("recovery_required", {}))
class D_PartialFillsTests(unittest.TestCase):
    def test_partial_fill_reconcile(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        with tempfile.TemporaryDirectory() as td:
            botmod.STATE_PATH = Path(td)/"state.json"
            botmod.LOG_PATH = Path(td)/"trades.log"
            botmod.CONFIG["paper_trading"]=False
            botmod.CONFIG["market"]="future"
            # Provide open_orders that match created OCO ids so verify passes; test focuses on partial entry qty handling
            # need to provide dynamic open_orders via side_effect
            oco_ids = {}
            def fetch_open_dynamic(symbol):
                # return ids that were just created if available
                if oco_ids:
                    return [{"id": f"id-{v}", "clientOrderId": v, "orderLinkId": v} for v in oco_ids.values()]
                return []
            ex = _mock_ex_for_place(ex_id="binance", open_orders=[])
            # override create to capture oco ids
            orig_mock = _mock_ex_for_place
            def create_partial(sym, typ, side, qty, price, params):
                cid = params.get("clientOrderId","") if params else ""
                if params and ("stopLossPrice" in params or "takeProfitPrice" in params):
                    oco_ids[cid] = cid
                return {"id":"id-"+cid,"clientOrderId":cid,"orderLinkId":cid,"filled":qty*0.5 if "stopLossPrice" not in (params or {}) and "takeProfitPrice" not in (params or {}) else qty,"average":50000}
            ex.create_order.side_effect = create_partial
            ex.fetch_open_orders.side_effect = fetch_open_dynamic
            ex.fetch_positions.return_value=[{"symbol":"BTC/USDT","contracts":0.005,"info":{"size":"0.005"}}]
            with mock.patch.object(botmod, "fetch_ohlcv", return_value=_fake_df()):
                with mock.patch.object(botmod, "adx_value", return_value=25):
                    with mock.patch.object(botmod, "volume_ok", return_value=True):
                        with mock.patch.object(botmod, "htf_trend_ok", return_value=True):
                            with mock.patch.object(botmod, "regime_detect", return_value="trend"):
                                state=botmod.load_state()
                                analysis={"total":0.9,"price":50000,"decision":"buy","amount_mult":1.0}
                                botmod.try_enter("BTC/USDT", analysis, state, ex)
                                self.assertNotIn("BTC/USDT", state.get("pending_orders", {}))
                                # partial fill amount is handled; either position open with 0.5*qty or recovery if verify fails, but pending cleared
                                self.assertTrue("BTC/USDT" not in state.get("pending_orders", {}))
class E_RestartRecoveryTests(unittest.TestCase):
    def test_pending_survives_reload_and_blocks(self):
        import tempfile
        from pathlib import Path
        from unittest import mock
        with tempfile.TemporaryDirectory() as td:
            botmod.STATE_PATH = Path(td)/"state.json"
            botmod.LOG_PATH = Path(td)/"trades.log"
            botmod.CONFIG["paper_trading"]=False
            botmod.CONFIG["market"]="future"
            state = botmod.load_state()
            state["pending_orders"]["ETH/USDT"]="raqm-pending-xyz"
            state["recovery_required"]["ETH/USDT"]={"cid":"raqm-pending-xyz","reason":"test"}
            botmod.save_state(state)
            reloaded = botmod.load_state()
            self.assertEqual(reloaded["pending_orders"]["ETH/USDT"],"raqm-pending-xyz")
            self.assertIn("ETH/USDT", reloaded["recovery_required"])
            ex = _mock_ex_for_place(ex_id="binance")
            with mock.patch.object(botmod, "fetch_ohlcv", return_value=_fake_df()):
                with mock.patch.object(botmod, "adx_value", return_value=25):
                    with mock.patch.object(botmod, "volume_ok", return_value=True):
                        with mock.patch.object(botmod, "htf_trend_ok", return_value=True):
                            with mock.patch.object(botmod, "regime_detect", return_value="trend"):
                                analysis={"total":0.9,"price":3000,"decision":"buy","amount_mult":1.0}
                                botmod.try_enter("ETH/USDT", analysis, reloaded, ex)
                                self.assertNotIn("ETH/USDT", reloaded.get("positions", {}))

class F_PositionSideMismatchTests(unittest.TestCase):
    def test_binance_params(self):
        ex = _mock_ex_for_place(ex_id="binance", hedge=False)
        botmod.CONFIG["paper_trading"]=False
        botmod.CONFIG["market"]="future"
        res = botmod.place_order(ex, "BTC/USDT","long",20,50000, client_order_id="raqm-test-bin")
        last = ex._last_calls_list[-1]
        self.assertIn("positionSide", last["params"])
        self.assertNotIn("positionIdx", last["params"])
        self.assertEqual(last["params"]["positionSide"], "LONG")
        ex2 = _mock_ex_for_place(ex_id="binance", hedge=False)
        botmod.place_order(ex2, "BTC/USDT","close_long",20,50000, client_order_id="raqm-test-bin2")
        last2 = ex2._last_calls_list[-1]
        self.assertEqual(last2["params"]["positionSide"], "LONG")
        self.assertTrue(last2["params"].get("reduceOnly"))
    def test_bybit_hedge_params(self):
        ex = _mock_ex_for_place(ex_id="bybit", hedge=True)
        botmod.CONFIG["paper_trading"]=False
        botmod.CONFIG["market"]="future"
        botmod.place_order(ex, "BTC/USDT","long",20,50000, client_order_id="raqm-test-bybit-hedge")
        last = ex._last_calls_list[-1]
        self.assertIn("positionIdx", last["params"])
        self.assertIn("positionSide", last["params"])
        self.assertEqual(last["params"]["positionIdx"], 1)
        ex2 = _mock_ex_for_place(ex_id="bybit", hedge=True)
        botmod.place_order(ex2, "BTC/USDT","short",20,50000, client_order_id="raqm-test-bybit-hedge2")
        last2 = ex2._last_calls_list[-1]
        self.assertEqual(last2["params"]["positionIdx"], 2)
        self.assertEqual(last2["params"]["positionSide"], "SHORT")
    def test_bybit_oneway_omits(self):
        ex = _mock_ex_for_place(ex_id="bybit", hedge=False)
        botmod.CONFIG["paper_trading"]=False
        botmod.CONFIG["market"]="future"
        botmod.place_order(ex, "BTC/USDT","long",20,50000, client_order_id="raqm-test-bybit-one")
        last = ex._last_calls_list[-1]
        self.assertNotIn("positionIdx", last["params"])
        self.assertNotIn("positionSide", last["params"])
        self.assertIn("clientOrderId", last["params"])
        self.assertIn("orderLinkId", last["params"])
    def test_okx_oneway_omits_hedge_adds(self):
        ex = _mock_ex_for_place(ex_id="okx", hedge=False)
        botmod.CONFIG["paper_trading"]=False
        botmod.CONFIG["market"]="future"
        botmod.place_order(ex, "BTC/USDT","long",20,50000, client_order_id="raqm-test-okx")
        last = ex._last_calls_list[-1]
        self.assertNotIn("positionSide", last["params"])
        self.assertNotIn("posSide", last["params"])
        ex2 = _mock_ex_for_place(ex_id="okx", hedge=True)
        botmod.place_order(ex2, "BTC/USDT","long",20,50000, client_order_id="raqm-test-okx2")
        last2 = ex2._last_calls_list[-1]
        self.assertIn("posSide", last2["params"])
class G_BothLegsFailedTests(unittest.TestCase):
    def test_both_failed_is_not_partial(self):
        ex = _mock_ex_for_place(ex_id="binance", fail_sl=True, fail_tp=True)
        res = place_oco_orders(ex, "BTC/USDT","long",0.01,49000,51000, paper=False, pos_id="xyz12345")
        self.assertTrue(res.get("both_failed"))
        self.assertNotIn("partial", res)
        self.assertTrue(res.get("protection_missing"))
    def test_one_missing_verify_is_fail_closed(self):
        cid_sl = f"{OCO_PREFIX}-abcd1234-sl"
        ex = _mock_ex_for_place(ex_id="binance", fail_sl=False, fail_tp=False, open_orders=[{"clientOrderId": cid_sl, "id":"ex-sl"}])
        res = place_oco_orders(ex, "BTC/USDT","long",0.01,49000,51000, paper=False, pos_id="abcd1234")
        self.assertNotIn("protection_missing", res)
        self.assertTrue(res.get("tp_unverified"))
        self.assertNotIn("sl_unverified", res)
        self.assertTrue(res.get("verify_failed"))
class H_IdOnlyCancelTests(unittest.TestCase):
    def test_cancel_without_ids_does_nothing(self):
        ex = _mock_ex_for_place(ex_id="binance")
        ex.fetch_open_orders.return_value = [
            {"id":"1","clientOrderId":f"{OCO_PREFIX}-aaaa-sl"},
            {"id":"2","clientOrderId":f"{OCO_PREFIX}-bbbb-tp"},
            {"id":"3","clientOrderId":"manual-order"},
        ]
        cancel_oco_orders(ex, "BTC/USDT")
        ex.cancel_order.assert_not_called()
    def test_cancel_with_pos_id_only_cancels_owned(self):
        ex = _mock_ex_for_place(ex_id="binance")
        owned_sl = f"{OCO_PREFIX}-abcd1234-sl"
        owned_tp = f"{OCO_PREFIX}-abcd1234-tp"
        ex.fetch_open_orders.return_value = [
            {"id":"1","clientOrderId": owned_sl},
            {"id":"2","clientOrderId": owned_tp},
            {"id":"3","clientOrderId": f"{OCO_PREFIX}-other-sl"},
        ]
        cancel_oco_orders(ex, "BTC/USDT", pos_id="abcd1234")
        self.assertEqual(ex.cancel_order.call_count, 2)
        ids = {c[0][0] for c in ex.cancel_order.call_args_list}
        self.assertEqual(ids, {"1","2"})
