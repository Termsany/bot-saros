"""
Multi-Exchange Manager — 4 exchanges isolated
Each toggle is independent: paper or LIVE per exchange
"""
import ccxt
from typing import Dict, Any

EXCHANGES = ["binance","bybit","okx","mexc"]

# Map to ccxt class
CCXT_MAP = {
    "binance": ccxt.binance,
    "bybit": ccxt.bybit,
    "okx": ccxt.okx,
    "mexc": ccxt.mexc,
}

# OKX needs passphrase
def get_exchange_instance(exchange: str, apiKey: str, secret: str, passphrase: str = "", enableRateLimit=True):
    cls = CCXT_MAP.get(exchange.lower())
    if not cls:
        raise ValueError(f"Unknown exchange {exchange}")
    kwargs: Dict[str,Any] = {"enableRateLimit": enableRateLimit, "options": {"defaultType": "future"}}
    if apiKey and secret:
        kwargs["apiKey"] = apiKey
        kwargs["secret"] = secret
        if exchange.lower() == "okx" and passphrase:
            kwargs["password"] = passphrase
    return cls(kwargs)

def get_all_instances(mode: str = "live"):
    """
    mode: "live" -> only LIVE exchanges, "all" -> all configured, "paper" -> only paper
    Returns dict {exchange: instance}
    """
    from app.keys_vault import load_keys, load_all_status
    status = load_all_status()
    out = {}
    for ex in EXCHANGES:
        st = status.get(ex, {})
        if not st.get("configured"):
            continue
        is_paper = st.get("paper", True)
        if mode == "live" and is_paper:
            continue
        if mode == "paper" and not is_paper:
            continue
        keys = load_keys(ex)
        if not keys:
            continue
        try:
            inst = get_exchange_instance(ex, keys.get("apiKey",""), keys.get("secret",""), keys.get("passphrase",""))
            out[ex] = inst
        except Exception as e:
            print(f"exchange {ex} init failed: {e}")
    return out

def fetch_balances():
    """Returns {exchange: {USDT: free}} for LIVE only"""
    instances = get_all_instances("live")
    out = {}
    for ex, inst in instances.items():
        try:
            bal = inst.fetch_balance()
            # Try common keys
            free = 0
            for k in ["USDT","USDC","USDT:USDT"]:
                if k in bal and isinstance(bal[k], dict) and "free" in bal[k]:
                    free = float(bal[k]["free"])
                    break
            if not free and "free" in bal and isinstance(bal["free"], dict):
                free = float(bal["free"].get("USDT", 0))
            out[ex] = {"USDT": free, "raw": bal}
        except Exception as e:
            out[ex] = {"USDT": 0, "error": str(e)[:100]}
    return out
