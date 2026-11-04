"""
Per-user encrypted key vault — each user's own Binance Demo keys (/settings/live), keyed by user_id -> exchange.

A user can only ever read/write their own entry — callers must pass the user_id taken from the authenticated
session (see auth.require_user), never from client-supplied input. scripts/provision_users.py decrypts them with the
same VAULT_MASTER_KEY to hand each user's Demo bot its key.

The admin's single-account vault (keys_vault.py, vault.json, /api/keys/*) was removed on 2026-11-04: it fed only the
paper dashboard loop. Its master-key policy lives here now.
"""
import json, os
from pathlib import Path

from cryptography.fernet import Fernet

EXCHANGES = ["binance", "bybit", "okx", "mexc"]

# Master key: VAULT_MASTER_KEY (survives redeploys, never on disk next to the vault). Generate one with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# A key file next to the vault is a local-dev fallback only.
MASTER_KEY_PATH = Path(__file__).parent.parent / ".master.key"


def get_fernet():
    env_key = os.getenv("VAULT_MASTER_KEY", "").strip()
    if env_key:
        return Fernet(env_key.encode())
    # P1-03a: fail closed where the master key must be kept apart from the encrypted keys (live / hosted): anyone
    # who copies the app folder must not get both.
    if os.getenv("ALLOW_LIVE_TRADING", "").strip().lower() == "true" or os.getenv("RENDER") or os.getenv("VERCEL") or os.getenv("RAILWAY_ENVIRONMENT"):
        raise RuntimeError("VAULT_MASTER_KEY not set — refusing to use a key file next to the vault (live trading / hosted)")
    if MASTER_KEY_PATH.exists():
        key = MASTER_KEY_PATH.read_bytes().strip()
    else:
        key = Fernet.generate_key()
        MASTER_KEY_PATH.write_bytes(key)
        try: MASTER_KEY_PATH.chmod(0o600)
        except OSError: pass
        try:
            if (MASTER_KEY_PATH.stat().st_mode & 0o777) & 0o077:
                print("WARN vault: .master.key is group/world-readable — fix permissions")
        except OSError: pass
    return Fernet(key)


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
