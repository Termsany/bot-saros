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
    # the random part of the entry id (12 hex): 8 characters of "raqm-xxxxxxxx" left only 3 random ones, so two
    # positions could share ids and one close would cancel the other's stop
    pid = str(pos_id or uuid.uuid4().hex[:12])
    if pid.startswith(OCO_PREFIX + "-"): pid = pid[len(OCO_PREFIX) + 1:]
    return f"{OCO_PREFIX}-{pid[-12:]}-{leg}"[:36]

def _position_idx_for_side(ex, side: str):
    """positionIdx / orderLinkId are Bybit fields — other exchanges reject unknown parameters."""
    try:
        if str(getattr(ex, "id", "")).lower() == "bybit" and hasattr(ex, "options") and ex.options.get("hedgeMode"):
            return 1 if side == "long" else 2
    except: pass
    return None

def _order_cid(o):
    return (o or {}).get("clientOrderId") or ((o or {}).get("info") or {}).get("clientOrderId") or (o or {}).get("orderLinkId")


def _leg_on_exchange(ex, symbol, order, cid):
    """True if the exchange shows this protective order as open. Conditional (stop / take-profit) orders are kept
    apart from plain orders on several exchanges (Binance algo orders, Bybit conditional), so look by id first,
    then in the open orders, then in the open trigger orders."""
    oid = (order or {}).get("id")
    if oid:
        try:
            o = ex.fetch_order(oid, symbol)
            if isinstance(o, dict) and (o.get("id") == oid or _order_cid(o) == cid):
                return (o.get("status") or "open") == "open"
        except Exception:
            pass
    for params in ({}, {"trigger": True}, {"stop": True}):
        try:
            opens = ex.fetch_open_orders(symbol, None, None, params) if params else ex.fetch_open_orders(symbol)
        except Exception:
            continue
        if not isinstance(opens, list):
            continue
        for o in opens:
            if isinstance(o, dict) and (_order_cid(o) == cid or (oid and o.get("id") == oid)):
                return True
    return False


def _protective_params(ex, side, cid):
    ex_id = str(getattr(ex, "id", "")).lower()
    hedge = bool(getattr(ex, "options", {}).get("hedgeMode"))
    params = {"clientOrderId": cid}
    if ex_id == "bybit":
        params["orderLinkId"] = cid
        params["reduceOnly"] = True
        if hedge:
            params["positionIdx"] = 1 if side == "long" else 2
    elif ex_id.startswith("binance"):
        if hedge:
            params["positionSide"] = "LONG" if side == "long" else "SHORT"
        else:
            params["reduceOnly"] = True
    elif ex_id == "okx":
        params["tdMode"] = getattr(ex, "options", {}).get("marginMode", "isolated")
        if hedge:
            params["posSide"] = "long" if side == "long" else "short"
        params["reduceOnly"] = True
    else:
        params["reduceOnly"] = True
    return params


def place_oco_orders(ex, symbol, side, qty, sl_price, tp_price, paper: bool = True, pos_id: str = None, position_idx=None):
    """Places the stop and the target as reduceOnly orders tagged with our own ids.

    tp_price=None places the stop alone.
    A leg that was accepted is never cancelled here — a position with its stop is safer than one without.
    Result flags for the caller:
      protection_missing — the stop was rejected: the position has no exchange stop, the caller must close it
      tp_missing         — only the target was rejected: the stop protects the position, the bot exits at the target itself
      sl_unverified / tp_unverified — the exchange accepted the order but it can't be found afterwards:
                           the caller keeps the position, alerts and blocks new entries until someone checks
    """
    if paper:
        return {"paper": True, "sl": sl_price, "tp": tp_price}
    if not pos_id:
        pos_id = uuid.uuid4().hex[:8]
    close_side = "sell" if side == "long" else "buy"
    sl_id, tp_id = _oco_id(pos_id, "sl"), _oco_id(pos_id, "tp")
    results: dict = {"pos_id": pos_id, "sl_id": sl_id, "tp_id": tp_id}
    idx = position_idx if position_idx is not None else _position_idx_for_side(ex, side)
    base_params: dict = {"reduceOnly": True}
    if idx:
        base_params["positionIdx"] = int(idx)
    for leg, cid, key, price in (("sl", sl_id, "stopLossPrice", sl_price), ("tp", tp_id, "takeProfitPrice", tp_price)):
        if price is None:   # stop only (the daily trend exits on its signal, not at a target)
            continue
        try:
            params = {**_protective_params(ex, side, cid), key: float(ex.price_to_precision(symbol, price))}
            if idx is not None:
                params["orderLinkId"] = cid
            results[leg] = ex.create_order(symbol, "market", close_side, qty, None, params)
        except Exception as e:
            results[f"{leg}_error"] = str(e)

    if "sl_error" in results:
        results["protection_missing"] = True
        if "tp_error" in results:
            results["both_failed"] = True
        else:
            results["partial"] = True
        return results
    if "tp_error" in results:
        results["partial"] = True
        results["tp_missing"] = True

    missing = []
    for leg, cid in (("sl", sl_id), ("tp", tp_id)):
        if leg in results and not _leg_on_exchange(ex, symbol, results[leg], cid):
            results[f"{leg}_unverified"] = True
            missing.append(leg)
    if missing:
        results["verify_failed"] = True
        results["verify_warn"] = f"accepted but not found on the exchange: {', '.join(missing)}"
    return results


def _owned_orders(ex, symbol, ids):
    """Read owned orders from plain and trigger/algo views; errors are inconclusive."""
    found = {}
    complete = True
    for params in ({}, {"trigger": True}, {"stop": True}):
        try:
            opens = ex.fetch_open_orders(symbol, None, None, params) if params else ex.fetch_open_orders(symbol)
        except Exception:
            complete = False
            continue
        if not isinstance(opens, list):
            complete = False
            continue
        for order in opens:
            if not isinstance(order, dict):
                continue
            if _order_cid(order) in ids or order.get("id") in ids:
                found[order.get("id")] = order
    return found, complete


def cancel_oco_orders(ex, symbol, pos_id: str = None, sl_id: str = None, tp_id: str = None):
    """Cancel owned protection and verify absence across plain and trigger/algo views."""
    ids = {x for x in (sl_id, tp_id) if x}
    if pos_id:
        ids |= {_oco_id(pos_id, "sl"), _oco_id(pos_id, "tp")}
    if not ids:
        return False
    found, complete = _owned_orders(ex, symbol, ids)
    if not complete:
        return False
    ok = True
    for oid in found:
        try:
            ex.cancel_order(oid, symbol)
        except Exception:
            ok = False
    if not ok:
        return False
    remaining, complete = _owned_orders(ex, symbol, ids)
    return bool(complete and not remaining)


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
