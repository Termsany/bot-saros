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

# Master key: prefer env VAULT_MASTER_KEY (survives redeploys, never on disk next to the vault).
# Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Fallback to a local file only for local dev.
MASTER_KEY_PATH = Path(__file__).parent.parent / ".master.key"
def get_fernet():
    env_key = os.getenv("VAULT_MASTER_KEY", "").strip()
    if env_key:
        return Fernet(env_key.encode())
    # P1-03a: fail closed in production (Render/Vercel/VPS) where VAULT_MASTER_KEY must be set.
    # Local dev fallback only: generate a dev-only key and warn.
    # Real money needs the master key apart from the encrypted keys: anyone who copies the app folder must not get both.
    # Moving an existing install over: VAULT_MASTER_KEY=<contents of backend/.master.key>, then delete the file.
    if os.getenv("ALLOW_LIVE_TRADING", "").strip().lower() == "true" or os.getenv("RENDER") or os.getenv("VERCEL") or os.getenv("RAILWAY_ENVIRONMENT"):
        raise RuntimeError("VAULT_MASTER_KEY not set — refusing to use a key file next to the vault (live trading / hosted)")
    if MASTER_KEY_PATH.exists():
        key = MASTER_KEY_PATH.read_bytes().strip()
    else:
        key = Fernet.generate_key()
        MASTER_KEY_PATH.write_bytes(key)
        try: MASTER_KEY_PATH.chmod(0o600)
        except: pass
        # Verify chmod actually took
        try:
            import stat as _stat
            if (MASTER_KEY_PATH.stat().st_mode & 0o777) & 0o077:
                print("WARN vault: .master.key is group/world-readable — fix permissions")
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
            f = get_fernet()
            data = json.loads(f.decrypt(VAULT_PATH.read_bytes()).decode())
        except Exception as e:
            # wrong master key or damaged file: writing now would silently drop every other exchange's keys
            raise RuntimeError(f"vault can't be decrypted ({type(e).__name__}) — not overwriting it; check VAULT_MASTER_KEY") from e
    # New keys always start in Paper; going LIVE is an explicit, separate step (set_paper).
    # Updating keys keeps the existing mode.
    paper = bool(data.get(exchange, {}).get("paper", True))
    data[exchange] = {"apiKey": apiKey, "secret": secret, "passphrase": passphrase, "paper": paper}
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
    except Exception as e:
        print(f"ERROR vault: can't decrypt ({type(e).__name__}) — no exchange keys, nothing will trade")
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
