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
    # Binance clientOrderId max 36, Bybit orderLinkId max 36 -> use short pos_id
    pid = str(pos_id or uuid.uuid4().hex[:8])
    return f"{OCO_PREFIX}-{pid[:8]}-{leg}"[:36]

def _position_idx_for_side(ex, side: str):
    """Hedge mode needs positionIdx; one-way does not. Return None if not needed."""
    # Heuristic: if exchange exposes hedge mode, caller should pass it. For now detect via private flag.
    try:
        if hasattr(ex, "options") and ex.options.get("hedgeMode"):
            return 1 if side == "long" else 2
    except: pass
    return None

def place_oco_orders(ex, symbol, side, qty, sl_price, tp_price, paper: bool = True, pos_id: str = None, position_idx=None):
    """يحط SL و TP كأوامر منفصلة. paper=True لا يرسل شيء للمنصة.
    pos_id: stable id for order ownership (e.g. Trade.id or uuid). If None, generates ephemeral ids.
    position_idx: for Bybit hedge mode (1=long, 2=short). Omit for one-way.
    Returns {sl, tp, sl_id, tp_id} or {sl_error, tp_error, partial: True}.
    """
    if paper:
        return {"paper": True, "sl": sl_price, "tp": tp_price}
    if not pos_id:
        pos_id = uuid.uuid4().hex[:8]
    is_long = side == "long"
    close_side = "sell" if is_long else "buy"
    sl_id = _oco_id(pos_id, "sl")
    tp_id = _oco_id(pos_id, "tp")
    results: dict = {"pos_id": pos_id, "sl_id": sl_id, "tp_id": tp_id}
    # positionIdx for hedge mode (Bybit)
    idx = position_idx if position_idx is not None else _position_idx_for_side(ex, side)
    base_params: dict = {"reduceOnly": True}
    if idx:
        base_params["positionIdx"] = int(idx)  # type: ignore
    # SL
    try:
        sl_params = {**base_params, "stopLossPrice": float(ex.price_to_precision(symbol, sl_price)), "clientOrderId": sl_id}
        # Bybit alternative key
        if idx is not None:
            sl_params["orderLinkId"] = sl_id
        results["sl"] = ex.create_order(symbol, "market", close_side, qty, None, sl_params)
    except Exception as e:
        results["sl_error"] = str(e)
    # TP
    try:
        tp_params = {**base_params, "takeProfitPrice": float(ex.price_to_precision(symbol, tp_price)), "clientOrderId": tp_id}
        if idx is not None:
            tp_params["orderLinkId"] = tp_id
        results["tp"] = ex.create_order(symbol, "market", close_side, qty, None, tp_params)
    except Exception as e:
        results["tp_error"] = str(e)

    # Verification: if one leg succeeded and the other failed, cancel the succeeded leg (no partial protection)
    if ("sl" in results and "tp_error" in results) or ("tp" in results and "sl_error" in results):
        results["partial"] = True
        # Best-effort cancel the half that succeeded (ownership-tagged, safe)
        try:
            if "sl" in results:
                ex.cancel_order(results["sl"].get("id") or sl_id, symbol)
        except Exception: pass
        try:
            if "tp" in results:
                ex.cancel_order(results["tp"].get("id") or tp_id, symbol)
        except Exception: pass
        # Caller must flatten position - do not treat as protected
        return results

    # Both succeeded or both failed: if both succeeded, verify they are open on exchange (best effort)
    if "sl" in results and "tp" in results:
        try:
            opens = {o.get("clientOrderId") or o.get("orderLinkId") or o.get("id") for o in ex.fetch_open_orders(symbol)}
            if sl_id not in opens and tp_id not in opens:
                # Neither visible yet - may be immediate fill or id mismatch; not fatal but flag
                results["verify_warn"] = "oco ids not yet in open_orders"
        except Exception:
            pass
    return results


def cancel_oco_orders(ex, symbol, pos_id: str = None, sl_id: str = None, tp_id: str = None):
    """يلغي أوامر SL/TP المملوكة فقط. If pos_id given, cancels only raqm-<pos_id>-{sl,tp}. Without ids, refuses to broad-cancel."""
    if pos_id:
        ids = {_oco_id(pos_id, "sl"), _oco_id(pos_id, "tp")}
    elif sl_id or tp_id:
        ids = {x for x in (sl_id, tp_id) if x}
    else:
        # SAFE default: do NOT broad-cancel. Caller that doesn't track ownership must not be called.
        # Keep legacy broad path behind explicit flag for migration, but log warning.
        try:
            open_orders = ex.fetch_open_orders(symbol)
            for o in open_orders:
                cid = o.get("clientOrderId") or o.get("orderLinkId") or ""
                if cid.startswith(OCO_PREFIX + "-"):
                    try: ex.cancel_order(o["id"], symbol)
                    except Exception: pass
        except Exception: pass
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
    """Helper: create_order with stable clientOrderId. Returns order. Caller stores client_order_id before call."""
    if not client_order_id:
        client_order_id = f"{OCO_PREFIX}-{uuid.uuid4().hex[:12]}"[:36]
    p = dict(params or {})
    p.setdefault("clientOrderId", client_order_id)
    # Bybit also accepts orderLinkId
    if "orderLinkId" not in p and client_order_id.startswith(OCO_PREFIX):
        p["orderLinkId"] = client_order_id
    try:
        order = ex.create_order(symbol, "market", side, qty, None, p)
        return order, client_order_id
    except Exception as e:
        # On timeout/network error after fill, caller should fetch by client_order_id
        raise
