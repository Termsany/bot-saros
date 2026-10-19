"""
Keys Vault — Multi-Exchange encrypted storage
Backend stores keys, never exposes secrets to frontend.
Frontend: POST /api/keys/save {exchange, apiKey, secret, passphrase}
Backend: saves to Supabase vault table or local .env (encrypted)
Read: GET /api/keys/status -> {binance:true, bybit:false, okx:false, mexc:false} (masked)
"""
import os, json, base64
from pathlib import Path
from cryptography.fernet import Fernet

# Generate or load master key
MASTER_KEY_PATH = Path(__file__).parent.parent / ".master.key"
def get_fernet():
    if MASTER_KEY_PATH.exists():
        key = MASTER_KEY_PATH.read_bytes().strip()
    else:
        key = Fernet.generate_key()
        MASTER_KEY_PATH.write_bytes(key)
        try: MASTER_KEY_PATH.chmod(0o600)
        except: pass
    return Fernet(key)

VAULT_PATH = Path(__file__).parent.parent / "vault.json"
EXCHANGES = ["binance","bybit","okx","mexc"]

def save_keys(exchange: str, apiKey: str, secret: str, passphrase: str = ""):
    if exchange not in EXCHANGES:
        raise ValueError(f"Unknown exchange {exchange}")
    data = {}
    if VAULT_PATH.exists():
        try:
            # Decrypt existing
            f = get_fernet()
            raw = VAULT_PATH.read_bytes()
            data = json.loads(f.decrypt(raw).decode())
        except:
            data = {}
    data[exchange] = {"apiKey": apiKey, "secret": secret, "passphrase": passphrase, "paper": False}
    f = get_fernet()
    VAULT_PATH.write_bytes(f.encrypt(json.dumps(data, ensure_ascii=False).encode()))
    try: VAULT_PATH.chmod(0o600)
    except: pass
    return True

def load_keys(exchange: str):
    if not VAULT_PATH.exists():
        return None
    try:
        f = get_fernet()
        data = json.loads(f.decrypt(VAULT_PATH.read_bytes()).decode())
        return data.get(exchange)
    except:
        return None

def load_all_status():
    """Returns {exchange: {configured: bool, paper: bool}} without secrets"""
    out = {}
    for ex in EXCHANGES:
        k = load_keys(ex)
        out[ex] = {"configured": bool(k and k.get("apiKey")), "paper": bool(k and k.get("paper", True)) if k else True}
        if k and not k.get("apiKey"):
            out[ex]["configured"] = False
    return out

def set_paper(exchange: str, paper: bool):
    if not VAULT_PATH.exists():
        return False
    try:
        f = get_fernet()
        data = json.loads(f.decrypt(VAULT_PATH.read_bytes()).decode())
        if exchange in data:
            data[exchange]["paper"] = bool(paper)
            VAULT_PATH.write_bytes(f.encrypt(json.dumps(data, ensure_ascii=False).encode()))
            return True
    except: pass
    return False

def delete_keys(exchange: str):
    if not VAULT_PATH.exists():
        return False
    try:
        f = get_fernet()
        data = json.loads(f.decrypt(VAULT_PATH.read_bytes()).decode())
        if exchange in data:
            del data[exchange]
            VAULT_PATH.write_bytes(f.encrypt(json.dumps(data, ensure_ascii=False).encode()))
            return True
    except: pass
    return False

def get_exchanges_for_trading():
    """Returns list of exchanges that are configured and not in paper mode"""
    status = load_all_status()
    return [ex for ex, v in status.items() if v["configured"] and not v["paper"]]

def get_all_configured():
    """Returns all configured exchanges regardless of paper mode"""
    status = load_all_status()
    return [ex for ex, v in status.items() if v["configured"]]
