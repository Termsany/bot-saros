"""Thin per-user ccxt client factory — Phase 2 (2) support module.

Mirrors exchange_manager.py's CCXT_MAP/instance pattern, but reads ONLY the
calling user's own keys from user_keys_vault.py. It must NEVER read the
admin/owner's vault (keys_vault.py) and NEVER be used to build an instance for
a user other than the one whose id is passed in.
"""
from typing import Any, Dict, Optional

from app.exchange_manager import CCXT_MAP
from app import user_keys_vault as ukv


def get_user_exchange_instance(user_id: str, exchange: str, *, enableRateLimit: bool = True) -> Optional[Any]:
    """Builds a ccxt-compatible client for this user's own configured keys only.

    Returns None if the user has no (complete) keys for this exchange — callers
    must treat that as "cannot trade for this user right now", never substitute
    the admin/owner's own vault or another user's keys.
    """
    exchange = (exchange or "").lower().strip()
    cls = CCXT_MAP.get(exchange)
    if not cls:
        raise ValueError(f"Unknown exchange {exchange}")
    keys = ukv.load_user_keys(user_id, exchange)
    if not keys or not keys.get("apiKey") or not keys.get("secret"):
        return None
    kwargs: Dict[str, Any] = {"enableRateLimit": enableRateLimit, "options": {"defaultType": "future"},
                              "apiKey": keys["apiKey"], "secret": keys["secret"]}
    if exchange == "okx" and keys.get("passphrase"):
        kwargs["password"] = keys["passphrase"]
    return cls(kwargs)
