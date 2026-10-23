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


def place_oco_orders(ex, symbol, side, qty, sl_price, tp_price, paper: bool = True, pos_id: str = None, position_idx=None):
    """Places the stop and the target as reduceOnly orders tagged with our own ids.

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
        try:
            params = {**base_params, key: float(ex.price_to_precision(symbol, price)), "clientOrderId": cid}
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


def cancel_oco_orders(ex, symbol, pos_id: str = None, sl_id: str = None, tp_id: str = None):
    """Cancels only our own protective orders (by their ids) — plain and conditional (trigger) open orders both,
    since Binance/Bybit keep stop/take-profit orders apart. Never a broad cancel: manual orders stay."""
    ids = {x for x in (sl_id, tp_id) if x}
    if pos_id:
        ids |= {_oco_id(pos_id, "sl"), _oco_id(pos_id, "tp")}
    if not ids:
        return
    seen = set()
    for params in ({}, {"trigger": True}, {"stop": True}):
        try:
            opens = ex.fetch_open_orders(symbol, None, None, params) if params else ex.fetch_open_orders(symbol)
        except Exception:
            continue
        for o in opens if isinstance(opens, list) else []:
            if not isinstance(o, dict) or o.get("id") in seen:
                continue
            if _order_cid(o) in ids or o.get("id") in ids:
                seen.add(o.get("id"))
                try: ex.cancel_order(o["id"], symbol, params) if params else ex.cancel_order(o["id"], symbol)
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
