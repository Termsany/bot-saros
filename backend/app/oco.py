"""OCO: عند الدخول نحط أمر وقف + أمر هدف على المنصة (reduceOnly) — ccxt unified params تشتغل على Binance/Bybit/OKX"""


def place_oco_orders(ex, symbol, side, qty, sl_price, tp_price, paper: bool = True):
    """يحط SL و TP كأوامر منفصلة. paper=True لا يرسل شيء للمنصة (القرار من البوت نفسه، مش من env)"""
    if paper:
        return {"paper": True, "sl": sl_price, "tp": tp_price}
    is_long = side == "long"
    close_side = "sell" if is_long else "buy"
    results = {}
    try:
        # ccxt maps stopLossPrice -> STOP_MARKET (Binance) / conditional stop (Bybit/OKX)
        results["sl"] = ex.create_order(symbol, "market", close_side, qty, None, {
            "stopLossPrice": float(ex.price_to_precision(symbol, sl_price)),
            "reduceOnly": True,
        })
    except Exception as e:
        results["sl_error"] = str(e)
    try:
        results["tp"] = ex.create_order(symbol, "market", close_side, qty, None, {
            "takeProfitPrice": float(ex.price_to_precision(symbol, tp_price)),
            "reduceOnly": True,
        })
    except Exception as e:
        results["tp_error"] = str(e)
    return results


def cancel_oco_orders(ex, symbol):
    """يلغي أوامر SL/TP المفتوحة"""
    try:
        open_orders = ex.fetch_open_orders(symbol)
        for o in open_orders:
            if o.get("reduceOnly") or o.get("stopPrice") or o.get("triggerPrice") or \
                    o.get("type") in ("STOP_MARKET", "TAKE_PROFIT_MARKET", "STOP", "TAKE_PROFIT"):
                try: ex.cancel_order(o["id"], symbol)
                except Exception: pass
    except Exception: pass
