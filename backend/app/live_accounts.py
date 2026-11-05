"""The owner's real-money accounts: which Binance sub-account each live strategy trades on (docs/trend-daily-live-plan.md §2).

One account per strategy at most. A strategy not in the registry trades on the main account, as before:
/opt/raqm-live/.env.real, /opt/raqm-live/allow-live.env, the ledger /opt/raqm-risk. A strategy in it trades on its own
account only:
  /etc/raqm-live/accounts/<name>/binance          its keys (BINANCE_API_KEY= / BINANCE_SECRET= lines; root, 600), read
                                                  through systemd LoadCredential, so the bot never falls back to the
                                                  main account's keys (bot.py _binance_keys)
  /etc/raqm-live/accounts/<name>/allow-live.env   ALLOW_LIVE_TRADING, BINANCE_LIVE_ACCOUNT and the five RAQM_CAP_*_PCT
                                                  of that account (root, 600)
  /opt/raqm-risk-<name>/                          its own risk ledger and activation record
The unit raqm-live@<strategy> gets a drop-in (dropin_text) that resets every environment file and writable path it
inherits and hides the main account's keys and ledger from it.

Registry: /etc/raqm-live/accounts.json, {"accounts": {"<name>": {"strategies": ["<strategy>", ...]}}}, written only
by deploy/vps/tools/live_account.py (root), readable by the watchdog, the backup and the preflight. No secrets in it.
Stdlib only: the bot's copy, the tools and the API import it.
"""
import json
import re
from pathlib import Path

REGISTRY = Path("/etc/raqm-live/accounts.json")
ACCOUNTS_DIR = Path("/etc/raqm-live/accounts")
RISK_ROOT = Path("/opt")                       # /opt/raqm-risk-<name>
MAIN = "main"                                  # the default account's name in reports; never a registry entry
NAME_RE = re.compile(r"^[a-z][a-z0-9]{1,15}$")
RESERVED = {MAIN, "demo", "live", "users", "paper"}   # /opt/raqm-risk-demo is the Demo ledger
STRATEGY_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


class RegistryError(ValueError):
    pass


def valid_name(name):
    return isinstance(name, str) and bool(NAME_RE.match(name)) and name not in RESERVED


def validate(doc):
    """{name: [strategies]} from a registry document; raises RegistryError on anything off (a bad name, a strategy on
    two accounts, a wrong shape): a registry that can't be trusted must stop the tools, never be read as empty."""
    if not isinstance(doc, dict) or not isinstance(doc.get("accounts", {}), dict):
        raise RegistryError("registry must be {\"accounts\": {...}}")
    out, seen = {}, {}
    for name, a in doc.get("accounts", {}).items():
        if not valid_name(name):
            raise RegistryError(f"bad account name {name!r}")
        strategies = (a or {}).get("strategies") if isinstance(a, dict) else None
        if not isinstance(strategies, list) or not all(isinstance(s, str) and STRATEGY_RE.match(s) for s in strategies):
            raise RegistryError(f"account {name}: strategies must be a list of strategy names")
        for s in strategies:
            if s in seen:
                raise RegistryError(f"{s} is on two accounts ({seen[s]}, {name})")
            seen[s] = name
        out[name] = sorted(set(strategies))
    return out


def load(path=REGISTRY):
    """{name: [strategies]}; {} when there is no registry (every strategy on the main account)."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise RegistryError(f"{p}: {e}")
    return validate(doc)


def account_of(strategy, accounts):
    """The account `strategy` trades on: its registry name, or None for the main account."""
    return next((n for n, ss in accounts.items() if strategy in ss), None)


def paths(name, accounts_dir=ACCOUNTS_DIR, risk_root=RISK_ROOT):
    if not valid_name(name):
        raise RegistryError(f"bad account name {name!r}")
    d = Path(accounts_dir) / name
    return {"dir": d, "keys": d / "binance", "allow": d / "allow-live.env", "risk": Path(risk_root) / f"raqm-risk-{name}"}


def ledger_dirs(accounts, main=Path("/opt/raqm-risk"), risk_root=RISK_ROOT):
    """{account: ledger folder} for the main account and every registered one."""
    return {MAIN: Path(main), **{n: paths(n, risk_root=risk_root)["risk"] for n in sorted(accounts)}}


def ledger_exists(ledger_dir):
    """True when the folder holds a ledger (the JSON of old or the SQLite file). Reading one with
    risk_manager.load_risk_state creates it, so a check by root or by the watchdog asks this first: a ledger made by
    the wrong user would lock the bot out of its own account's ledger."""
    d = Path(ledger_dir)
    return (d / "risk_state.sqlite3").is_file() or (d / "risk_state.json").is_file()


def dropin_text(name, strategy, accounts_dir=ACCOUNTS_DIR, risk_root=RISK_ROOT):
    """raqm-live@<strategy>.service.d/account.conf: this strategy on account `name` only. Every list the unit sets is
    reset first (an empty assignment clears it in systemd), so no line of the main account's files reaches the bot."""
    if not STRATEGY_RE.match(strategy or ""):
        raise RegistryError(f"bad strategy {strategy!r}")
    p = {k: v.as_posix() for k, v in paths(name, accounts_dir, risk_root).items()}   # unit files take POSIX paths
    return (
        f"# written by deploy/vps/tools/live_account.py: {strategy} trades on the Binance account '{name}' only\n"
        "[Service]\n"
        "EnvironmentFile=\n"
        "EnvironmentFile=-/opt/raqm-live/.env.telegram\n"
        f"EnvironmentFile={p['allow']}\n"
        f"EnvironmentFile=-/opt/raqm-live/strategies/{strategy}.env\n"
        f"Environment=RAQM_RISK_DIR={p['risk']}\n"
        f"Environment=RAQM_LIVE_ACCOUNT_NAME={name}\n"
        f"LoadCredential=binance:{p['keys']}\n"
        "UnsetEnvironment=BINANCE_API_KEY BINANCE_SECRET\n"
        "ReadWritePaths=\n"
        f"ReadWritePaths=/opt/raqm-live/state /opt/raqm-ipc {p['risk']}\n"
        "InaccessiblePaths=-/opt/raqm-live/.env.real -/opt/raqm-live/allow-live.env -/opt/raqm-risk\n"
    )


def dump(accounts):
    return json.dumps({"accounts": {n: {"strategies": sorted(set(ss))} for n, ss in sorted(accounts.items())}}, indent=2) + "\n"
