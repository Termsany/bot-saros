"""
Per-user encrypted key vault — multi-tenant extension of keys_vault.py.

keys_vault.py stores ONE global vault.json keyed by exchange name, used by the
admin/owner account only (admin-only /api/keys/* endpoints, live_activation.py).

This module stores a SEPARATE vault.json keyed by user_id -> exchange, so any
registered (non-admin) user can hold their own exchange API keys, isolated
from every other user and from the admin vault. It reuses the exact same
Fernet master-key pattern (get_fernet) from keys_vault.py so there is only one
key-derivation/fail-closed policy to reason about.

A user can only ever read/write their own entry — callers must pass the
user_id taken from the authenticated session (see auth.require_user), never
from client-supplied input.
"""
import json
from pathlib import Path

from app.keys_vault import get_fernet, EXCHANGES

VAULT_PATH = Path(__file__).parent.parent / "user_vault.json"


def _load_all():
    if not VAULT_PATH.exists():
        return {}
    f = get_fernet()
    try:
        return json.loads(f.decrypt(VAULT_PATH.read_bytes()).decode())
    except Exception as e:
        raise RuntimeError(f"user vault can't be decrypted ({type(e).__name__}) — check VAULT_MASTER_KEY") from e


def _write_all(data):
    """New file, then rename over the vault: a crash mid-write used to leave every user's keys unreadable."""
    import os, tempfile
    f = get_fernet()
    blob = f.encrypt(json.dumps(data, ensure_ascii=False).encode())
    fd, tmp = tempfile.mkstemp(dir=str(VAULT_PATH.parent), prefix=".user_vault-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(blob); fh.flush(); os.fsync(fh.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, VAULT_PATH)
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise


def save_user_keys(user_id: str, exchange: str, apiKey: str, secret: str, passphrase: str = ""):
    if not user_id:
        raise ValueError("user_id required")
    exchange = exchange.lower().strip()
    if exchange not in EXCHANGES:
        raise ValueError(f"Unknown exchange {exchange}")
    data = {}
    if VAULT_PATH.exists():
        try:
            data = _load_all()
        except RuntimeError:
            raise
    user_entry = data.get(user_id, {})
    # New keys always start in Paper; going LIVE is a separate, explicit per-user step.
    paper = bool(user_entry.get(exchange, {}).get("paper", True))
    user_entry[exchange] = {"apiKey": apiKey, "secret": secret, "passphrase": passphrase, "paper": paper}
    data[user_id] = user_entry
    _write_all(data)
    return True


def load_user_keys(user_id: str, exchange: str):
    exchange = exchange.lower().strip()
    data = _load_all()
    return (data.get(user_id) or {}).get(exchange)


def delete_user_keys(user_id: str, exchange: str):
    exchange = exchange.lower().strip()
    if not VAULT_PATH.exists():
        return False
    data = _load_all()
    user_entry = data.get(user_id)
    if not user_entry or exchange not in user_entry:
        return False
    del user_entry[exchange]
    data[user_id] = user_entry
    _write_all(data)
    return True


def set_user_paper(user_id: str, exchange: str, paper: bool):
    exchange = exchange.lower().strip()
    if not VAULT_PATH.exists():
        return False
    data = _load_all()
    user_entry = data.get(user_id)
    if not user_entry or exchange not in user_entry:
        return False
    user_entry[exchange]["paper"] = bool(paper)
    data[user_id] = user_entry
    _write_all(data)
    return True


def user_key_status(user_id: str):
    """Returns {exchange: {configured: bool, paper: bool}} for this user only — never secrets."""
    data = {}
    if VAULT_PATH.exists():
        data = _load_all()
    user_entry = data.get(user_id, {})
    out = {}
    for ex in EXCHANGES:
        k = user_entry.get(ex)
        out[ex] = {"configured": bool(k and k.get("apiKey")), "paper": bool(k.get("paper", True)) if k else True}
    return out


def has_live_configured_keys(user_id: str, exchange: str) -> bool:
    """True only if this user has real (non-empty) keys for this exchange, i.e. the
    live-execution path may actually use them. Used as the key half of the
    'only fires for a user actually enabled with their own keys' gate."""
    k = load_user_keys(user_id, exchange)
    return bool(k and k.get("apiKey") and k.get("secret"))
