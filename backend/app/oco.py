
"""OCO: عند الدخول نحط STOP_MARKET + TAKE_PROFIT_MARKET على Binance"""
import os

def place_oco_orders(ex, symbol, side, qty, sl_price, tp_price):
    """يحط SL و TP كأوامر منفصلة على Binance Futures"""
    if os.getenv("PAPER_TRADING", "true").lower() != "false":
        # Paper: لا يرسل للمنصة
        return {"paper": True, "sl": sl_price, "tp": tp_price}
    is_long = side == "long"
    close_side = "sell" if is_long else "buy"
    results = {}
    try:
        # SL: STOP_MARKET
        sl_order = ex.create_order(symbol, "STOP_MARKET", close_side, qty, None, {
            "stopPrice": ex.price_to_precision(symbol, sl_price),
            "closePosition": False,
        })
        results["sl"] = sl_order
    except Exception as e:
        results["sl_error"] = str(e)
    try:
        # TP: TAKE_PROFIT_MARKET
        tp_order = ex.create_order(symbol, "TAKE_PROFIT_MARKET", close_side, qty, None, {
            "stopPrice": ex.price_to_precision(symbol, tp_price),
            "closePosition": False,
        })
        results["tp"] = tp_order
    except Exception as e:
        results["tp_error"] = str(e)
    return results

def cancel_oco_orders(ex, symbol):
    """يلغي أوامر SL/TP المفتوحة"""
    try:
        open_orders = ex.fetch_open_orders(symbol)
        for o in open_orders:
            if o["type"] in ("STOP_MARKET", "TAKE_PROFIT_MARKET", "STOP", "TAKE_PROFIT"):
                try: ex.cancel_order(o["id"], symbol)
                except: pass
    except: pass
