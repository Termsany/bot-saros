"""OCO: عند الدخول نحط أمر وقف + أمر هدف على المنصة (reduceOnly) — ccxt unified params تشتغل على Binance/Bybit/OKX

Stage C fixes (P0-01, P0-04, P0-05):
- P0-01: place_oco_orders verifies both legs via fetch_open_orders; on partial failure cancels the succeeded leg.
  Emergency liquidation is handled by the caller (bot_loop) which must NOT persist Trade as open until OCO is verified.
- P0-04: All protective orders are tagged with clientOrderId prefix raqm_<pos_id>_<sl|tp>; cancel only owns.
- P0-05: Every create_order uses a stable clientOrderId (uuid) for idempotent retry; caller stores pending_oco.
"""

import uuid

OCO_PREFIX = "raqm"
MAX_RETRY_OCO = 2

def _oco_id(pos_id, leg):
    pid = str(pos_id or uuid.uuid4().hex[:8])
    return f"{OCO_PREFIX}-{pid[:8]}-{leg}"[:36]

def _position_idx_for_side(ex, side: str):
    try:
        if hasattr(ex, "options") and ex.options.get("hedgeMode"):
            return 1 if side == "long" else 2
    except: pass
    return None

def place_oco_orders(ex, symbol, side, qty, sl_price, tp_price, paper: bool = True, pos_id: str = None, position_idx=None):
    """Returns {sl, tp, sl_id, tp_id} or {sl_error, tp_error, partial: True} plus fail-closed flags."""
    if paper:
        return {"paper": True, "sl": sl_price, "tp": tp_price}
    if not pos_id:
        pos_id = uuid.uuid4().hex[:8]
    is_long = side == "long"
    close_side = "sell" if is_long else "buy"
    sl_id = _oco_id(pos_id, "sl")
    tp_id = _oco_id(pos_id, "tp")
    results: dict = {"pos_id": pos_id, "sl_id": sl_id, "tp_id": tp_id}
    idx = position_idx if position_idx is not None else _position_idx_for_side(ex, side)
    base_params: dict = {"reduceOnly": True}
    if idx:
        base_params["positionIdx"] = int(idx)
    try:
        sl_params = {**base_params, "stopLossPrice": float(ex.price_to_precision(symbol, sl_price)), "clientOrderId": sl_id}
        if idx is not None:
            sl_params["orderLinkId"] = sl_id
        results["sl"] = ex.create_order(symbol, "market", close_side, qty, None, sl_params)
    except Exception as e:
        results["sl_error"] = str(e)
    try:
        tp_params = {**base_params, "takeProfitPrice": float(ex.price_to_precision(symbol, tp_price)), "clientOrderId": tp_id}
        if idx is not None:
            tp_params["orderLinkId"] = tp_id
        results["tp"] = ex.create_order(symbol, "market", close_side, qty, None, tp_params)
    except Exception as e:
        results["tp_error"] = str(e)

    has_sl = "sl" in results
    has_tp = "tp" in results
    has_sl_err = "sl_error" in results
    has_tp_err = "tp_error" in results

    if has_sl_err and has_tp_err:
        results["both_failed"] = True
        results["protection_missing"] = True
        results["verify_failed"] = True
        return results

    if (has_sl and has_tp_err) or (has_tp and has_sl_err):
        results["partial"] = True
        results["protection_missing"] = True
        try:
            if has_sl:
                ex.cancel_order(results["sl"].get("id") or sl_id, symbol)
        except Exception: pass
        try:
            if has_tp:
                ex.cancel_order(results["tp"].get("id") or tp_id, symbol)
        except Exception: pass
        return results

    if has_sl and has_tp:
        try:
            opens = ex.fetch_open_orders(symbol)
            open_ids = {o.get("clientOrderId") or o.get("orderLinkId") or o.get("id") for o in (opens or [])}
            sl_found = sl_id in open_ids
            tp_found = tp_id in open_ids
            if not sl_found and not tp_found:
                results["protection_missing"] = True
                results["verify_failed"] = True
                results["verify_warn"] = "oco ids not in open_orders — protection missing"
                try:
                    ex.cancel_order(results["sl"].get("id") or sl_id, symbol)
                except Exception: pass
                try:
                    ex.cancel_order(results["tp"].get("id") or tp_id, symbol)
                except Exception: pass
            elif not sl_found or not tp_found:
                results["protection_missing"] = True
                results["verify_failed"] = True
                results["verify_warn"] = f"partial verify: sl_found={sl_found} tp_found={tp_found}"
        except Exception as e:
            results["protection_missing"] = True
            results["verify_failed"] = True
            results["verify_error"] = str(e)
        return results

    return results


def cancel_oco_orders(ex, symbol, pos_id: str = None, sl_id: str = None, tp_id: str = None):
    if pos_id:
        ids = {_oco_id(pos_id, "sl"), _oco_id(pos_id, "tp")}
    elif sl_id or tp_id:
        ids = {x for x in (sl_id, tp_id) if x}
    else:
        return
    try:
        open_orders = ex.fetch_open_orders(symbol)
        for o in open_orders:
            cid = o.get("clientOrderId") or o.get("orderLinkId") or o.get("id") or ""
            if cid in ids or o.get("id") in ids:
                try: ex.cancel_order(o["id"], symbol)
                except Exception: pass
    except Exception: pass


def place_order_idempotent(ex, symbol, side, qty, params=None, client_order_id: str = None):
    if not client_order_id:
        client_order_id = f"{OCO_PREFIX}-{uuid.uuid4().hex[:12]}"[:36]
    p = dict(params or {})
    p.setdefault("clientOrderId", client_order_id)
    if "orderLinkId" not in p and client_order_id.startswith(OCO_PREFIX):
        p["orderLinkId"] = client_order_id
    try:
        order = ex.create_order(symbol, "market", side, qty, None, p)
        return order, client_order_id
    except Exception as e:
        raise
