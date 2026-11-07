"""The owner's real-money accounts: which Binance sub-account each live strategy trades on (docs/trend-daily-live-plan.md §2).

One account per strategy at most. A strategy not in the registry trades on the main account, as before:
/opt/raqm-live/.env.real, /opt/raqm-live/allow-live.env, the ledger /opt/raqm-risk. A strategy in it trades on its own
account only:
  /etc/raqm-live/accounts/<name>/binance          its keys (BINANCE_API_KEY= / BINANCE_SECRET= lines; root, 600), read
                                                  through systemd LoadCredential, so the bot never falls back to the
                                                  main account's keys (bot.py _binance_keys)
  /etc/raqm-live/accounts/<name>/allow-live.env   ALLOW_LIVE_TRADING, BINANCE_LIVE_ACCOUNT and the five RAQM_CAP_*_PCT
                                                  of that account (root, 600)
  /opt/raqm-risk-accounts/<name>/                 its own risk ledger and activation record (one parent folder,
                                                  so the API's unit opens them all with one ReadWritePaths line)
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
RISK_ROOT = Path("/opt/raqm-risk-accounts")    # <name>/ per account
MAIN = "main"                                  # the default account's name in reports; never a registry entry
NAME_RE = re.compile(r"^[a-z][a-z0-9]{1,15}$")
RESERVED = {MAIN, "demo", "live", "users", "paper"}   # /opt/raqm-risk-demo is the Demo ledger
STRATEGY_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


class RegistryError(ValueError):
    pass


def valid_name(name):
    return isinstance(name, str) and bool(NAME_RE.match(name)) and name not in RESERVED


def _entries(doc, key):
    out = {}
    for name, a in (doc.get(key) or {}).items():
        if not valid_name(name):
            raise RegistryError(f"bad account name {name!r}")
        strategies = (a or {}).get("strategies") if isinstance(a, dict) else None
        if not isinstance(strategies, list) or not strategies or not all(isinstance(s, str) and STRATEGY_RE.match(s) for s in strategies):
            raise RegistryError(f"account {name}: strategies must be a non-empty list of strategy names")
        out[name] = sorted(set(strategies))
    return out


def validate_copies(doc):
    """{name: [strategies]} of the "copies" section: accounts that run one more copy of a strategy that also runs on
    the main account (owner, 2026-11-07: momentum_ls on a second sub-account). Each copy has its own unit
    (copy_unit_text), status folder and state, so the main account's bot never changes. A copy account's name is not
    also a moved account's, and a strategy appears once per copy account."""
    if not isinstance(doc, dict) or not isinstance(doc.get("copies", {}), dict):
        raise RegistryError("registry \"copies\" must be {...}")
    copies = _entries(doc, "copies")
    clash = set(copies) & set((doc.get("accounts") or {}))
    if clash:
        raise RegistryError(f"{', '.join(sorted(clash))}: an account is either moved or a copy, not both")
    return copies


def validate(doc):
    """{name: [strategies]} from a registry document; raises RegistryError on anything off (a bad name, a strategy on
    two accounts, a wrong shape): a registry that can't be trusted must stop the tools, never be read as empty.
    The "copies" section is checked too (validate_copies) and read with load_copies."""
    if not isinstance(doc, dict) or not isinstance(doc.get("accounts", {}), dict):
        raise RegistryError("registry must be {\"accounts\": {...}}")
    validate_copies(doc)
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


def _doc(path):
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise RegistryError(f"{p}: {e}")


def load_copies(path=REGISTRY):
    """{name: [strategies]} of the copy accounts; {} when there is no registry."""
    doc = _doc(path)
    if doc is None:
        return {}
    validate(doc)
    return validate_copies(doc)


def copy_unit_name(name, strategy):
    return f"raqm-live-{name}@{strategy}"


def copy_ipc(name, strategy, ipc_root=Path("/opt/raqm-ipc")):
    """A copy's status folder: inside /opt/raqm-ipc (the API and the watchdog read there), apart from the main bot's."""
    return Path(ipc_root) / f"acct-{name}" / strategy


def copy_state(name, strategy):
    """A copy's state file, relative to /opt/raqm-live (bot.py --state)."""
    return f"state/live-{name}-{strategy}.json"


def copy_unit_text(name, accounts_dir=ACCOUNTS_DIR, risk_root=RISK_ROOT):
    """/etc/systemd/system/raqm-live-<name>@.service: a strategy (%i) on the copy account `name`. The same bot as
    raqm-live@ (bot.py unchanged) with only this account's files: its keys through LoadCredential (bot.py then never
    reads keys from the environment), its allow-live.env (root's ceilings, BINANCE_LIVE_ACCOUNT), its ledger and
    activation, its own status folder and state. The main account's keys and ledger are hidden from it."""
    p = {k: v.as_posix() for k, v in paths(name, accounts_dir, risk_root).items()}
    return (
        f"# written by deploy/vps/tools/live_account.py: a copy of a live strategy on the Binance account '{name}'\n"
        "[Unit]\n"
        f"Description=Raqm live bot %i with REAL MONEY on the Binance account '{name}'\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n"
        f"ConditionPathExists={p['keys']}\n"
        f"ConditionPathExists={p['allow']}\n"
        "\n[Service]\n"
        "User=raqmlive\n"
        "Group=raqmlive\n"
        "WorkingDirectory=/opt/raqm-live\n"
        "EnvironmentFile=-/opt/raqm-live/.env.telegram\n"
        f"EnvironmentFile={p['allow']}\n"
        "Environment=BINANCE_ENV=live\n"
        f"Environment=RAQM_IPC_DIR=/opt/raqm-ipc/acct-{name}/%i\n"
        f"Environment=RAQM_RISK_DIR={p['risk']}\n"
        f"Environment=RAQM_LIVE_ACCOUNT_NAME={name}\n"
        "Environment=\"RAQM_ARGS=--leverage 2 --amount 100 --poll 60\"\n"
        f"EnvironmentFile=-/opt/raqm-live/strategies/{name}-%i.env\n"
        f"LoadCredential=binance:{p['keys']}\n"
        "UnsetEnvironment=PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONUSERBASE PYTHONINSPECT BINANCE_API_KEY BINANCE_SECRET\n"
        "ExecStart=/opt/raqm-live/venv/bin/python -E -s -u bot.py --live --expect-env live --strategy %i $RAQM_ARGS --notify "
        f"--state state/live-{name}-%i.json\n"
        "Restart=always\n"
        "RestartSec=60\n"
        "NoNewPrivileges=true\n"
        "ProtectSystem=strict\n"
        "ProtectHome=true\n"
        "PrivateTmp=true\n"
        f"ReadWritePaths=/opt/raqm-live/state /opt/raqm-ipc {p['risk']}\n"
        "InaccessiblePaths=-/opt/raqm-live/.env.real -/opt/raqm-live/allow-live.env -/opt/raqm-risk\n"
        "\n[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def account_of(strategy, accounts):
    """The account `strategy` trades on: its registry name, or None for the main account."""
    return next((n for n, ss in accounts.items() if strategy in ss), None)


def paths(name, accounts_dir=ACCOUNTS_DIR, risk_root=RISK_ROOT):
    if not valid_name(name):
        raise RegistryError(f"bad account name {name!r}")
    d = Path(accounts_dir) / name
    return {"dir": d, "keys": d / "binance", "allow": d / "allow-live.env", "risk": Path(risk_root) / name}


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


def dump(accounts, copies=None):
    doc = {"accounts": {n: {"strategies": sorted(set(ss))} for n, ss in sorted(accounts.items())}}
    if copies:
        doc["copies"] = {n: {"strategies": sorted(set(ss))} for n, ss in sorted(copies.items())}
    return json.dumps(doc, indent=2) + "\n"
