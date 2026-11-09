"""Live strategies on their own Binance sub-accounts (root; backend/app/live_accounts.py).

Two ways, both read by the watchdog, the backup, the preflight and the check:
  move   a strategy trades on its own account instead of the main one (raqm-live@<strategy> gets a drop-in)
  copy   one more copy of a strategy on its own account, the main account's bot unchanged
         (its own unit raqm-live-<name>@<strategy>, status folder /opt/raqm-ipc/acct-<name>/<strategy> and state)

  sudo /opt/raqm-live/venv/bin/python -I /usr/local/lib/raqm/live_account.py show
  sudo /opt/raqm-live/venv/bin/python -I /usr/local/lib/raqm/live_account.py add trend trend_daily          # move
  sudo /opt/raqm-live/venv/bin/python -I /usr/local/lib/raqm/live_account.py remove trend trend_daily
  sudo /opt/raqm-live/venv/bin/python -I /usr/local/lib/raqm/live_account.py add-copy mom2 momentum_ls     # copy
  sudo /opt/raqm-live/venv/bin/python -I /usr/local/lib/raqm/live_account.py remove-copy mom2 momentum_ls

Each makes the account's folders (keys folder root 700, ledger /opt/raqm-risk-accounts/<name> raqmlive:raqmrisk 2770,
and for a copy its status folder), writes its unit file and the registry, and reloads systemd. It never writes keys,
never starts or stops a bot, and refuses while the bot it changes is running or still holds positions in the ledger it
would leave. The owner then writes, themselves (root, 600 each):
  /etc/raqm-live/accounts/<name>/binance          BINANCE_API_KEY=... and BINANCE_SECRET=...
  /etc/raqm-live/accounts/<name>/allow-live.env   ALLOW_LIVE_TRADING=true, BINANCE_LIVE_ACCOUNT=<name>, the five RAQM_CAP_*_PCT
and runs scripts/live_preflight.py --strategy <strategy> [--account <name> for a copy].
"""
import argparse, json, os, subprocess, sys, tempfile
from pathlib import Path

for base in (Path("/opt/raqm-live"), Path(__file__).resolve().parents[3]):   # the server's copy, or the repo
    if (base / "backend" / "app" / "live_accounts.py").is_file():
        sys.path.insert(0, str(base)); break
from backend.app import live_accounts as la   # noqa: E402

UNITS = Path("/etc/systemd/system")
MAIN_LEDGER = Path("/opt/raqm-risk")
IPC_ROOT = Path("/opt/raqm-ipc")


class Host:
    """Everything that touches the system, so the tests can run it in a folder."""
    def __init__(self, registry=la.REGISTRY, accounts_dir=la.ACCOUNTS_DIR, risk_root=la.RISK_ROOT, units=UNITS,
                 main_ledger=MAIN_LEDGER, ipc_root=IPC_ROOT):
        self.registry, self.accounts_dir, self.risk_root, self.units, self.main_ledger, self.ipc_root = \
            Path(registry), Path(accounts_dir), Path(risk_root), Path(units), Path(main_ledger), Path(ipc_root)

    def active(self, unit):
        return subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True).stdout.strip() == "active"

    def reload(self):
        subprocess.run(["systemctl", "daemon-reload"], check=True)

    def chown(self, path, user, group):
        import shutil
        shutil.chown(path, user, group)

    def open_risk(self, ledger_dir, strategy):
        """The strategy's rows in a ledger (0 when there is none yet)."""
        p = Path(ledger_dir) / "risk_state.json"
        if not p.exists() and not (Path(ledger_dir) / "risk_state.sqlite3").exists():
            return 0
        from backend.app import risk_manager as rm
        rows = (rm.load_risk_state(p).get("open_risk") or {}).values()
        return sum(1 for r in rows if r.get("strategy") == strategy)


def _write(path, text, mode):
    """Atomic: a temp file in the same folder, then rename (a half-written unit would start a bot on mixed files)."""
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, mode); os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True); raise


def _dropin(host, strategy):
    return host.units / f"raqm-live@{strategy}.service.d" / "account.conf"


def _copy_unit(host, name):
    return host.units / f"raqm-live-{name}@.service"


def _registry(host):
    return la.load(host.registry), la.load_copies(host.registry)


def _save(host, accounts, copies):
    text = la.dump(accounts, copies)
    la.validate(json.loads(text)); la.validate_copies(json.loads(text))
    _write(host.registry, text, 0o644)


def _shared(host, path):
    """A folder the bot (raqmlive) and the API (group raqmrisk) both write: 2770, as setup-live.sh's shared_dir."""
    path.mkdir(parents=True, exist_ok=True); os.chmod(path, 0o2770)
    try:
        host.chown(path, "raqmlive", "raqmrisk")
    except (LookupError, OSError, PermissionError) as e:
        raise SystemExit(f"can't give {path} to raqmlive:raqmrisk: {e}")


def _account_dirs(host, name):
    p = la.paths(name, host.accounts_dir, host.risk_root)
    p["dir"].mkdir(parents=True, exist_ok=True); os.chmod(p["dir"], 0o700)
    host.risk_root.mkdir(parents=True, exist_ok=True); os.chmod(host.risk_root, 0o755)
    _shared(host, p["risk"])
    return p


def _check_free(host, unit, strategy, leaving):
    if host.active(unit):
        raise SystemExit(f"{unit} is running: stop it first (its open trades stay on the account they're on)")
    n = host.open_risk(leaving, strategy)
    if n:
        raise SystemExit(f"{strategy} still holds {n} position(s) in {leaving}: close them before it changes account")


def _checked(name, strategy):
    if not la.valid_name(name):
        raise SystemExit(f"bad account name {name!r}: 2–16 lowercase letters/digits, not {', '.join(sorted(la.RESERVED))}")
    if not la.STRATEGY_RE.match(strategy):
        raise SystemExit(f"bad strategy {strategy!r}")


def _owner_steps(p, name, strategy, copy):
    flag = f" --account {name}" if copy else ""
    return (f"Left for the owner (root, 600 each):\n"
            f"  {p['keys']}  BINANCE_API_KEY=... / BINANCE_SECRET=...  (a sub-account for this bot alone)\n"
            f"  {p['allow']}  ALLOW_LIVE_TRADING=true, BINANCE_LIVE_ACCOUNT={name}, the five RAQM_CAP_*_PCT\n"
            f"then: live_preflight.py --strategy {strategy}{flag}")


def add(host, name, strategy):
    _checked(name, strategy)
    accounts, copies = _registry(host)
    if name in copies:
        raise SystemExit(f"'{name}' is a copy account: use add-copy")
    now = la.account_of(strategy, accounts)
    if now == name:
        print(f"{strategy} is already on '{name}'"); return
    if now is not None:
        raise SystemExit(f"{strategy} is on '{now}': remove it from there first")
    _check_free(host, f"raqm-live@{strategy}", strategy, host.main_ledger)
    p = _account_dirs(host, name)
    accounts = {**accounts, name: sorted(set(accounts.get(name, [])) | {strategy})}
    # the drop-in first, then the registry: the watchdog never sees a strategy on an account its unit doesn't use
    _write(_dropin(host, strategy), la.dropin_text(name, strategy, host.accounts_dir, host.risk_root), 0o644)
    _save(host, accounts, copies)
    host.reload()
    print(f"{strategy} → account '{name}'. " + _owner_steps(p, name, strategy, False))


def remove(host, name, strategy):
    accounts, copies = _registry(host)
    if la.account_of(strategy, accounts) != name:
        raise SystemExit(f"{strategy} is not on '{name}'")
    _check_free(host, f"raqm-live@{strategy}", strategy, la.paths(name, host.accounts_dir, host.risk_root)["risk"])
    rest = [s for s in accounts[name] if s != strategy]
    accounts = {n: ss for n, ss in accounts.items() if n != name} | ({name: rest} if rest else {})
    # the registry first, then the drop-in: never a strategy listed on an account whose drop-in is gone
    _save(host, accounts, copies)
    _dropin(host, strategy).unlink(missing_ok=True)
    host.reload()
    print(f"{strategy} → the main account. The '{name}' folders and keys are left as they are.")


def add_copy(host, name, strategy):
    _checked(name, strategy)
    accounts, copies = _registry(host)
    if name in accounts:
        raise SystemExit(f"'{name}' is a moved account: a copy needs an account of its own")
    if strategy in copies.get(name, []):
        print(f"{strategy} already has a copy on '{name}'"); return
    unit = la.copy_unit_name(name, strategy)
    if host.active(unit):
        raise SystemExit(f"{unit} is running")
    p = _account_dirs(host, name)
    ipc = la.copy_ipc(name, strategy, host.ipc_root)
    for d in (ipc.parent, ipc, ipc / "commands", ipc / "results"):
        _shared(host, d)
    copies = {**copies, name: sorted(set(copies.get(name, [])) | {strategy})}
    # the unit first, then the registry: the watchdog never watches a unit that doesn't exist yet
    _write(_copy_unit(host, name), la.copy_unit_text(name, host.accounts_dir, host.risk_root), 0o644)
    _save(host, accounts, copies)
    host.reload()
    print(f"{strategy}: one more copy on account '{name}' ({unit}, not started). " + _owner_steps(p, name, strategy, True))


def remove_copy(host, name, strategy):
    accounts, copies = _registry(host)
    if strategy not in copies.get(name, []):
        raise SystemExit(f"{strategy} has no copy on '{name}'")
    _check_free(host, la.copy_unit_name(name, strategy), strategy, la.paths(name, host.accounts_dir, host.risk_root)["risk"])
    rest = [s for s in copies[name] if s != strategy]
    copies = {n: ss for n, ss in copies.items() if n != name} | ({name: rest} if rest else {})
    _save(host, accounts, copies)
    if not rest:
        _copy_unit(host, name).unlink(missing_ok=True)
    host.reload()
    print(f"the copy of {strategy} on '{name}' is gone. Its folders, ledger and keys are left as they are.")


def show(host):
    accounts, copies = _registry(host)
    if not accounts and not copies:
        print("every live strategy is on the main account"); return
    have = lambda f: "present" if f.is_file() else "MISSING"
    for n, ss in sorted(accounts.items()):
        p = la.paths(n, host.accounts_dir, host.risk_root)
        print(f"{n} (moved): {', '.join(ss)} · keys {have(p['keys'])} · allow-live.env {have(p['allow'])} · ledger {p['risk']}")
        for s in ss:
            d = _dropin(host, s)
            ok = d.is_file() and d.read_text(encoding="utf-8") == la.dropin_text(n, s, host.accounts_dir, host.risk_root)
            print(f"  raqm-live@{s} drop-in {'ok' if ok else 'MISSING OR CHANGED: run add again'}")
    for n, ss in sorted(copies.items()):
        p = la.paths(n, host.accounts_dir, host.risk_root)
        u = _copy_unit(host, n)
        ok = u.is_file() and u.read_text(encoding="utf-8") == la.copy_unit_text(n, host.accounts_dir, host.risk_root)
        print(f"{n} (copy): {', '.join(ss)} · keys {have(p['keys'])} · allow-live.env {have(p['allow'])} · ledger {p['risk']}"
              f" · unit {'ok' if ok else 'MISSING OR CHANGED: run add-copy again'}")


def main(argv=None, host=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show")
    for c in ("add", "remove", "add-copy", "remove-copy"):
        s = sub.add_parser(c); s.add_argument("name"); s.add_argument("strategy")
    a = ap.parse_args(argv)
    if host is None:
        if hasattr(os, "geteuid") and os.geteuid() != 0:
            raise SystemExit("run as root")
        host = Host()
    try:
        {"show": lambda: show(host), "add": lambda: add(host, a.name, a.strategy),
         "remove": lambda: remove(host, a.name, a.strategy), "add-copy": lambda: add_copy(host, a.name, a.strategy),
         "remove-copy": lambda: remove_copy(host, a.name, a.strategy)}[a.cmd]()
    except la.RegistryError as e:
        raise SystemExit(f"registry: {e}")


if __name__ == "__main__":
    main()
