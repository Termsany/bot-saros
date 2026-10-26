"""P0: _amend_exchange_sl's replacement-first stop workflow must never lose track of either the new
replacement stop or the old stop it is trying to retire. Covers: durable persistence of the
replacement id before the old leg is touched, preservation of both ids across ambiguous/incomplete
cancellation, field verification of the replacement (trigger price / side / reduceOnly / quantity),
opportunistic cleanup during reconcile_live (including after a simulated restart), and that
subsequent position closure discovers and cleans up both orders. Long and short are both covered."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bot as botmod


class _AmendExchange:
    """Minimal fake exchange with no edit_order (forces _amend_exchange_sl into the
    place-then-cancel recreate path) and a durable in-memory order book for readback."""
    id = "binance"
    options = {}

    def __init__(self, *, cancel_removes=True, readback_incomplete=False):
        self.open_orders = []     # [{"id","clientOrderId","side","reduceOnly","amount","stopLossPrice"}]
        self.cancel_calls = []
        self._cancel_removes = cancel_removes
        self._readback_incomplete = readback_incomplete
        self.positions = []       # [{"symbol","contracts"}], set by tests that need _exchange_position_qty

    def fetch_positions(self, symbols=None):
        return self.positions

    def price_to_precision(self, symbol, price):
        return str(float(price))

    def create_order(self, symbol, kind, side, qty, price, params):
        cid = params.get("clientOrderId")
        order = {"id": "x-" + cid, "clientOrderId": cid, "side": side,
                 "reduceOnly": params.get("reduceOnly", True), "amount": qty,
                 "stopLossPrice": params.get("stopLossPrice")}
        self.open_orders.append(order)
        return order

    def fetch_order(self, oid, symbol):
        for o in self.open_orders:
            if o["id"] == oid:
                return dict(o, status="open")
        raise Exception("not found")

    def fetch_open_orders(self, symbol, *a):
        if self._readback_incomplete:
            raise Exception("exchange timeout")
        return [dict(o, status="open") for o in self.open_orders]

    def cancel_order(self, oid, symbol):
        self.cancel_calls.append(oid)
        if self._cancel_removes:
            self.open_orders = [o for o in self.open_orders if o["id"] != oid]
        # else: the cancel "succeeds" on the wire but the order is still visible on readback —
        # simulates an exchange-side ambiguous/incomplete cancellation.


def _seed_old_stop(ex, pos_id, side, qty, price):
    """Place the position's original stop directly on the fake exchange and wire pos['oco_ids']
    to it, the way a real entry would have."""
    from backend.app.oco import _oco_id, _protective_params
    close_side = "sell" if side == "long" else "buy"
    cid = _oco_id(pos_id, "sl")
    params = {**_protective_params(ex, side, cid), "stopLossPrice": price}
    order = ex.create_order("BTC/USDT", "market", close_side, qty, None, params)
    return order["clientOrderId"]


class ReplacementStopDualTrackingTests(unittest.TestCase):
    def setUp(self):
        botmod.CONFIG["paper_trading"] = False
        self._td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._old_state_path = botmod.STATE_PATH
        botmod.STATE_PATH = Path(self._td.name) / "state.json"

    def tearDown(self):
        botmod.STATE_PATH = self._old_state_path
        self._td.cleanup()
        botmod.CONFIG["paper_trading"] = True

    def _pos(self, side, qty=1.0, sl=49000.0, pos_id="pos-amend-1"):
        ex = _AmendExchange()
        old_sl_id = _seed_old_stop(ex, pos_id, side, qty, sl)
        pos = {"side": side, "qty": qty, "sl": sl, "oco_ids": {"sl": old_sl_id, "pos_id": pos_id}}
        return ex, pos, old_sl_id

    # --- 1/2: clean replacement, both long and short ---

    def test_long_amend_persists_replacement_and_clears_old(self):
        ex, pos, old_sl_id = self._pos("long")
        ok = botmod._amend_exchange_sl("BTC/USDT", pos, 49500.0, 49000.0, ex, {"positions": {"BTC/USDT": pos}, "recovery_required": {}})
        self.assertTrue(ok)
        self.assertNotIn("sl_pending_cancel", pos["oco_ids"])
        self.assertNotEqual(pos["oco_ids"]["sl"], old_sl_id)
        self.assertNotIn(old_sl_id, [o["id"] for o in ex.open_orders] + [o["clientOrderId"] for o in ex.open_orders])
        self.assertFalse(pos.get("sl_unverified"))

    def test_short_amend_persists_replacement_and_clears_old(self):
        ex, pos, old_sl_id = self._pos("short", sl=51000.0)
        ok = botmod._amend_exchange_sl("BTC/USDT", pos, 50500.0, 51000.0, ex, {"positions": {"BTC/USDT": pos}, "recovery_required": {}})
        self.assertTrue(ok)
        self.assertNotIn("sl_pending_cancel", pos["oco_ids"])
        self.assertNotEqual(pos["oco_ids"]["sl"], old_sl_id)

    # --- 3: ambiguous/failed cancellation of the old leg must preserve BOTH ids ---

    def test_ambiguous_cancel_preserves_both_ids_long(self):
        ex = _AmendExchange(cancel_removes=False)   # cancel "succeeds" but readback still sees it
        old_sl_id = _seed_old_stop(ex, "pos-amend-2", "long", 1.0, 49000.0)
        pos = {"side": "long", "qty": 1.0, "sl": 49000.0, "oco_ids": {"sl": old_sl_id, "pos_id": "pos-amend-2"}}
        ok = botmod._amend_exchange_sl("BTC/USDT", pos, 49500.0, 49000.0, ex, {"positions": {"BTC/USDT": pos}, "recovery_required": {}})
        self.assertFalse(ok)
        # The new replacement must already be the authoritative tracked stop ...
        new_sl_id = pos["oco_ids"]["sl"]
        self.assertNotEqual(new_sl_id, old_sl_id)
        # ... and the stale old id must still be durably tracked for a retry, not dropped.
        pending = pos["oco_ids"].get("sl_pending_cancel")
        self.assertIsNotNone(pending)
        self.assertEqual(pending["id"], old_sl_id)
        self.assertEqual(pending["pos_id"], "pos-amend-2")
        self.assertEqual(pending["status"], "pending_cancel")
        self.assertTrue(pos.get("sl_unverified"))
        # Both orders really are still open on the exchange — nothing was silently orphaned.
        open_ids = {o["clientOrderId"] for o in ex.open_orders}
        self.assertIn(old_sl_id, open_ids)
        self.assertIn(new_sl_id, open_ids)

    def test_ambiguous_cancel_preserves_both_ids_short(self):
        ex = _AmendExchange(cancel_removes=False)
        old_sl_id = _seed_old_stop(ex, "pos-amend-2s", "short", 1.0, 51000.0)
        pos = {"side": "short", "qty": 1.0, "sl": 51000.0, "oco_ids": {"sl": old_sl_id, "pos_id": "pos-amend-2s"}}
        ok = botmod._amend_exchange_sl("BTC/USDT", pos, 50500.0, 51000.0, ex, {"positions": {"BTC/USDT": pos}, "recovery_required": {}})
        self.assertFalse(ok)
        new_sl_id = pos["oco_ids"]["sl"]
        self.assertEqual(pos["oco_ids"]["sl_pending_cancel"]["id"], old_sl_id)
        open_ids = {o["clientOrderId"] for o in ex.open_orders}
        self.assertIn(old_sl_id, open_ids); self.assertIn(new_sl_id, open_ids)

    # --- incomplete exchange response during cancellation readback ---

    def test_incomplete_readback_during_cancel_preserves_both_ids(self):
        ex = _AmendExchange(readback_incomplete=True)
        old_sl_id = _seed_old_stop(ex, "pos-amend-3", "long", 1.0, 49000.0)
        pos = {"side": "long", "qty": 1.0, "sl": 49000.0, "oco_ids": {"sl": old_sl_id, "pos_id": "pos-amend-3"}}
        ex._readback_incomplete = True
        ok = botmod._amend_exchange_sl("BTC/USDT", pos, 49500.0, 49000.0, ex, {"positions": {"BTC/USDT": pos}, "recovery_required": {}})
        self.assertFalse(ok)
        self.assertEqual(pos["oco_ids"]["sl_pending_cancel"]["id"], old_sl_id)
        self.assertNotEqual(pos["oco_ids"]["sl"], old_sl_id)

    # --- field verification of the replacement stop ---

    def test_replacement_with_wrong_trigger_price_is_rejected_and_old_kept_authoritative(self):
        ex, pos, old_sl_id = self._pos("long")

        real_create = ex.create_order
        def bad_create(symbol, kind, side, qty, price, params):
            params = dict(params); params["stopLossPrice"] = 1.0   # exchange echoes back the wrong trigger
            return real_create(symbol, kind, side, qty, price, params)
        ex.create_order = bad_create

        ok = botmod._amend_exchange_sl("BTC/USDT", pos, 49500.0, 49000.0, ex, {"positions": {"BTC/USDT": pos}, "recovery_required": {}})
        self.assertFalse(ok)
        # The old stop remains the one and only tracked/authoritative id — no bad replacement adopted.
        self.assertEqual(pos["oco_ids"]["sl"], old_sl_id)
        self.assertNotIn("sl_pending_cancel", pos["oco_ids"])
        self.assertTrue(pos.get("sl_unverified"))

    def test_replacement_covering_less_than_full_quantity_is_rejected(self):
        ex, pos, old_sl_id = self._pos("long", qty=2.0)
        real_create = ex.create_order
        def short_create(symbol, kind, side, qty, price, params):
            return real_create(symbol, kind, side, 1.0, price, params)   # under-covers the 2.0 position
        ex.create_order = short_create
        ok = botmod._amend_exchange_sl("BTC/USDT", pos, 49500.0, 49000.0, ex, {"positions": {"BTC/USDT": pos}, "recovery_required": {}})
        self.assertFalse(ok)
        self.assertEqual(pos["oco_ids"]["sl"], old_sl_id)

    # --- reconcile_live must opportunistically clean up a pending replacement, including after "restart" ---

    def test_reconcile_live_cleans_up_pending_replacement_while_position_open(self):
        ex = _AmendExchange()
        new_sl_id = _seed_old_stop(ex, "pos-amend-4", "long", 1.0, 49500.0)
        stale_old_id = "raqm-poolsamend4-sl-stale"
        ex.open_orders.append({"id": "x-" + stale_old_id, "clientOrderId": stale_old_id, "side": "sell",
                                "reduceOnly": True, "amount": 1.0, "stopLossPrice": 49000.0})
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        old_paths = (botmod.STATE_PATH, botmod.LOG_PATH)
        botmod.STATE_PATH = Path(td.name) / "state.json"
        botmod.LOG_PATH = Path(td.name) / "t.log"
        try:
            # Simulates a bot restart: the position was loaded from disk with a pending replacement
            # that a previous process never managed to confirm-cancel.
            pos = {"side": "long", "qty": 1.0, "entry": 49000.0, "time": "2026-01-01T00:00:00+00:00",
                   "oco_ids": {"sl": new_sl_id, "pos_id": "pos-amend-4",
                               "sl_pending_cancel": {"id": stale_old_id, "pos_id": "pos-amend-4",
                                                      "role": "sl", "side": "long", "status": "pending_cancel"}}}
            state = {"positions": {"BTC/USDT": pos}, "last_trade": {}, "_flat_seen": {},
                     "stats": {"trades": 0, "wins": 0, "losses": 0, "pnl": 0}, "history": [],
                     "recovery_required": {}}
            ex.positions = [{"symbol": "BTC/USDT:USDT", "contracts": 1.0}]
            botmod.reconcile_live(state, ex)
            self.assertNotIn("sl_pending_cancel", state["positions"]["BTC/USDT"]["oco_ids"])
            self.assertNotIn(stale_old_id, [o["clientOrderId"] for o in ex.open_orders])
        finally:
            botmod.STATE_PATH, botmod.LOG_PATH = old_paths
            td.cleanup()

    # --- subsequent position closure must discover and clean up BOTH orders ---

    def test_close_live_position_cleans_up_both_sl_and_pending_replacement(self):
        ex = _AmendExchange()
        current_sl_id = _seed_old_stop(ex, "pos-amend-5", "long", 1.0, 49500.0)
        stale_old_id = "raqm-poolsamend5-sl-stale"
        ex.open_orders.append({"id": "x-" + stale_old_id, "clientOrderId": stale_old_id, "side": "sell",
                                "reduceOnly": True, "amount": 1.0, "stopLossPrice": 49000.0})
        pos = {"side": "long", "qty": 1.0, "entry": 49000.0,
               "oco_ids": {"sl": current_sl_id, "pos_id": "pos-amend-5",
                           "sl_pending_cancel": {"id": stale_old_id, "pos_id": "pos-amend-5",
                                                  "role": "sl", "side": "long", "status": "pending_cancel"}}}
        ex.positions = [{"symbol": "BTC/USDT:USDT", "contracts": 0}]   # already flat on the exchange
        res = botmod.close_live_position(ex, "BTC/USDT", pos, 49500.0)
        self.assertTrue(res["by_exchange"])
        self.assertFalse(res["recovery_required"], res)
        self.assertNotIn("sl_pending_cancel", pos["oco_ids"])
        remaining = [o["clientOrderId"] for o in ex.open_orders]
        self.assertNotIn(current_sl_id, remaining)
        self.assertNotIn(stale_old_id, remaining)

    def test_close_live_position_fails_closed_when_pending_replacement_cannot_be_cancelled(self):
        ex = _AmendExchange(cancel_removes=False)   # every cancel is ambiguous
        current_sl_id = _seed_old_stop(ex, "pos-amend-6", "long", 1.0, 49500.0)
        stale_old_id = "raqm-poolsamend6-sl-stale"
        ex.open_orders.append({"id": "x-" + stale_old_id, "clientOrderId": stale_old_id, "side": "sell",
                                "reduceOnly": True, "amount": 1.0, "stopLossPrice": 49000.0})
        pos = {"side": "long", "qty": 1.0, "entry": 49000.0,
               "oco_ids": {"sl": current_sl_id, "pos_id": "pos-amend-6",
                           "sl_pending_cancel": {"id": stale_old_id, "pos_id": "pos-amend-6",
                                                  "role": "sl", "side": "long", "status": "pending_cancel"}}}
        ex.positions = [{"symbol": "BTC/USDT:USDT", "contracts": 0}]
        res = botmod.close_live_position(ex, "BTC/USDT", pos, 49500.0)
        self.assertFalse(res["accounting_verified"])
        self.assertTrue(res["recovery_required"])
        # The pending replacement must stay tracked for the next attempt — not silently dropped.
        self.assertIn("sl_pending_cancel", pos["oco_ids"])

    def test_replacement_with_missing_authoritative_fields_is_rejected(self):
        for missing in ("side", "reduceOnly", "amount"):
            with self.subTest(missing=missing):
                ex, pos, old_sl_id = self._pos("long")
                original_fetch = ex.fetch_order
                def incomplete(oid, symbol, missing=missing, original_fetch=original_fetch):
                    row = original_fetch(oid, symbol)
                    row.pop(missing, None)
                    return row
                ex.fetch_order = incomplete
                state = {"positions": {"BTC/USDT": pos}, "recovery_required": {}}
                ok = botmod._amend_exchange_sl("BTC/USDT", pos, 49500.0, 49000.0, ex, state)
                self.assertFalse(ok)
                self.assertEqual(pos["oco_ids"]["sl"], old_sl_id)
                self.assertNotIn("sl_pending_cleanup", pos["oco_ids"])
                self.assertIn("BTC/USDT", state["recovery_required"])

    def test_authoritative_readback_error_retains_unverified_replacement(self):
        ex, pos, old_sl_id = self._pos("short", sl=51000.0)
        ex._cancel_removes = False
        ex.fetch_order = lambda oid, symbol: (_ for _ in ()).throw(TimeoutError("fetch timeout"))
        state = {"positions": {"BTC/USDT": pos}, "recovery_required": {}}
        ok = botmod._amend_exchange_sl("BTC/USDT", pos, 50500.0, 51000.0, ex, state)
        self.assertFalse(ok)
        self.assertNotEqual(pos["oco_ids"]["sl"], old_sl_id)
        self.assertIn("sl_pending_cancel", pos["oco_ids"])
        self.assertEqual(pos["oco_ids"]["sl_pending_cancel"]["id"], old_sl_id)
        self.assertIn("BTC/USDT", state["recovery_required"])

    def test_cleanup_ambiguity_retains_unverified_replacement_id(self):
        ex, pos, old_sl_id = self._pos("long")
        ex._readback_incomplete = True
        ex.fetch_order = lambda oid, symbol: (_ for _ in ()).throw(RuntimeError("readback unavailable"))
        ex._cancel_removes = False
        state = {"positions": {"BTC/USDT": pos}, "recovery_required": {}}
        ok = botmod._amend_exchange_sl("BTC/USDT", pos, 49500.0, 49000.0, ex, state)
        self.assertFalse(ok)
        pending = pos["oco_ids"].get("sl_pending_cleanup")
        self.assertIsNotNone(pending)
        self.assertIn(pending["id"], {o["clientOrderId"] for o in ex.open_orders})
        self.assertEqual(state["recovery_required"]["BTC/USDT"]["sl_sync"], "pending_cleanup")

    def test_persistence_failure_blocks_old_stop_cancellation_and_keeps_both_ids(self):
        ex, pos, old_sl_id = self._pos("short", sl=51000.0)
        state = {"positions": {"BTC/USDT": pos}, "recovery_required": {}}
        with patch.object(botmod, "save_state", side_effect=OSError("disk full")):
            ok = botmod._amend_exchange_sl("BTC/USDT", pos, 50500.0, 51000.0, ex, state)
        self.assertFalse(ok)
        self.assertEqual(ex.cancel_calls, [])
        self.assertNotEqual(pos["oco_ids"]["sl"], old_sl_id)
        self.assertEqual(pos["oco_ids"]["sl_pending_cancel"]["id"], old_sl_id)
        self.assertTrue(pos["sl_unverified"])
        self.assertIn("SL replacement", botmod._ENTRY_BLOCK["reason"])
    def test_active_status_is_required_and_terminal_statuses_fail_closed(self):
        base = {"id": "replacement-1", "side": "sell", "reduceOnly": True,
                "amount": 1.0, "stopLossPrice": 49500.0}
        for status in ("open", "new", "active", "pending"):
            ex = _AmendExchange()
            ex.fetch_order = lambda oid, symbol, status=status: dict(base, status=status)
            ok, reason = botmod._verify_protective_stop(ex, "BTC/USDT", base, 49500.0, "sell", 1.0)
            self.assertTrue(ok, (status, reason))
        for status in ("canceled", "closed", "expired", "rejected", "unknown", None):
            ex = _AmendExchange(readback_incomplete=True)
            ex.fetch_order = lambda oid, symbol, status=status: (dict(base, status=status) if status is not None else dict(base))
            ok, reason = botmod._verify_protective_stop(ex, "BTC/USDT", base, 49500.0, "sell", 1.0)
            self.assertFalse(ok, (status, reason))

    def test_missing_fetch_status_can_only_pass_with_active_endpoint(self):
        base = {"id": "replacement-2", "clientOrderId": "cid-2", "side": "sell",
                "reduceOnly": True, "amount": 1.0, "stopLossPrice": 49500.0}
        ex = _AmendExchange()
        ex.open_orders.append(dict(base, status="open"))
        ex.fetch_order = lambda oid, symbol: dict(base)
        ok, reason = botmod._verify_protective_stop(ex, "BTC/USDT", base, 49500.0, "sell", 1.0)
        self.assertTrue(ok, reason)
        ex._readback_incomplete = True
        ok, reason = botmod._verify_protective_stop(ex, "BTC/USDT", base, 49500.0, "sell", 1.0)
        self.assertFalse(ok, reason)


if __name__ == "__main__":
    unittest.main()
