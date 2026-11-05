"""Put one live strategy on its own Binance sub-account, or back on the main one (root; backend/app/live_accounts.py).

  sudo /opt/raqm-live/venv/bin/python -I /usr/local/lib/raqm/live_account.py show
  sudo /opt/raqm-live/venv/bin/python -I /usr/local/lib/raqm/live_account.py add trend trend_daily
  sudo /opt/raqm-live/venv/bin/python -I /usr/local/lib/raqm/live_account.py remove trend trend_daily

`add` makes the account's folders (keys folder root 700, ledger raqmlive:raqmrisk 2770), writes the unit's drop-in and
the registry, and reloads systemd. It never writes keys, never starts or stops a bot, and refuses while
raqm-live@<strategy> is running or still holds positions in the ledger it would leave: a bot must not change account under
its own open trades. The owner then writes, themselves:
  /etc/raqm-live/accounts/<name>/binance          BINANCE_API_KEY=... and BINANCE_SECRET=... (root, 600)
  /etc/raqm-live/accounts/<name>/allow-live.env   ALLOW_LIVE_TRADING=true, BINANCE_LIVE_ACCOUNT=<name>, RAQM_CAP_*_PCT (root, 600)
and runs scripts/live_preflight.py --strategy <strategy>, which checks all of it on that account.
"""
import argparse, json, os, subprocess, sys, tempfile
from pathlib import Path

for base in (Path("/opt/raqm-live"), Path(__file__).resolve().parents[3]):   # the server's copy, or the repo
    if (base / "backend" / "app" / "live_accounts.py").is_file():
        sys.path.insert(0, str(base)); break
from backend.app import live_accounts as la   # noqa: E402

UNITS = Path("/etc/systemd/system")
MAIN_LEDGER = Path("/opt/raqm-risk")


class Host:
    """Everything that touches the system, so the tests can run it in a folder."""
    def __init__(self, registry=la.REGISTRY, accounts_dir=la.ACCOUNTS_DIR, risk_root=la.RISK_ROOT, units=UNITS,
                 main_ledger=MAIN_LEDGER):
        self.registry, self.accounts_dir, self.risk_root, self.units, self.main_ledger = \
            Path(registry), Path(accounts_dir), Path(risk_root), Path(units), Path(main_ledger)

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
    """Atomic: a temp file in the same folder, then rename (a half-written drop-in would start a bot on mixed files)."""
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


def _check_free(host, strategy, leaving):
    if host.active(f"raqm-live@{strategy}"):
        raise SystemExit(f"raqm-live@{strategy} is running: stop it first (its open trades stay on the account they're on)")
    n = host.open_risk(leaving, strategy)
    if n:
        raise SystemExit(f"{strategy} still holds {n} position(s) in {leaving}: close them before it changes account")


def add(host, name, strategy):
    if not la.valid_name(name):
        raise SystemExit(f"bad account name {name!r}: 2–16 lowercase letters/digits, not {', '.join(sorted(la.RESERVED))}")
    if not la.STRATEGY_RE.match(strategy):
        raise SystemExit(f"bad strategy {strategy!r}")
    accounts = la.load(host.registry)
    now = la.account_of(strategy, accounts)
    if now == name:
        print(f"{strategy} is already on '{name}'"); return
    if now is not None:
        raise SystemExit(f"{strategy} is on '{now}': remove it from there first")
    _check_free(host, strategy, host.main_ledger)
    p = la.paths(name, host.accounts_dir, host.risk_root)
    p["dir"].mkdir(parents=True, exist_ok=True); os.chmod(p["dir"], 0o700)
    p["risk"].mkdir(parents=True, exist_ok=True); os.chmod(p["risk"], 0o2770)
    try:
        host.chown(p["risk"], "raqmlive", "raqmrisk")
    except (LookupError, OSError, PermissionError) as e:
        raise SystemExit(f"can't give {p['risk']} to raqmlive:raqmrisk: {e}")
    accounts = {**accounts, name: sorted(set(accounts.get(name, [])) | {strategy})}
    la.validate(json.loads(la.dump(accounts)))
    # the drop-in first, then the registry: the watchdog never sees a strategy on an account its unit doesn't use
    _write(_dropin(host, strategy), la.dropin_text(name, strategy, host.accounts_dir, host.risk_root), 0o644)
    _write(host.registry, la.dump(accounts), 0o644)
    host.reload()
    print(f"{strategy} → account '{name}'. Left for the owner (root, 600 each):\n"
          f"  {p['keys']}  BINANCE_API_KEY=... / BINANCE_SECRET=...  (a sub-account for this bot alone)\n"
          f"  {p['allow']}  ALLOW_LIVE_TRADING=true, BINANCE_LIVE_ACCOUNT={name}, the five RAQM_CAP_*_PCT\n"
          f"then: live_preflight.py --strategy {strategy}")


def remove(host, name, strategy):
    accounts = la.load(host.registry)
    if la.account_of(strategy, accounts) != name:
        raise SystemExit(f"{strategy} is not on '{name}'")
    _check_free(host, strategy, la.paths(name, host.accounts_dir, host.risk_root)["risk"])
    rest = [s for s in accounts[name] if s != strategy]
    accounts = {n: ss for n, ss in accounts.items() if n != name} | ({name: rest} if rest else {})
    # the registry first, then the drop-in: never a strategy listed on an account whose drop-in is gone
    _write(host.registry, la.dump(accounts), 0o644)
    _dropin(host, strategy).unlink(missing_ok=True)
    host.reload()
    print(f"{strategy} → the main account. The '{name}' folders and keys are left as they are.")


def show(host):
    accounts = la.load(host.registry)
    if not accounts:
        print("every live strategy is on the main account"); return
    for n, ss in sorted(accounts.items()):
        p = la.paths(n, host.accounts_dir, host.risk_root)
        have = lambda f: "present" if f.is_file() else "MISSING"
        print(f"{n}: {', '.join(ss)} · keys {have(p['keys'])} · allow-live.env {have(p['allow'])} · ledger {p['risk']}")
        for s in ss:
            d = _dropin(host, s)
            ok = d.is_file() and d.read_text(encoding="utf-8") == la.dropin_text(n, s, host.accounts_dir, host.risk_root)
            print(f"  raqm-live@{s} drop-in {'ok' if ok else 'MISSING OR CHANGED: run add again'}")


def main(argv=None, host=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show")
    for c in ("add", "remove"):
        s = sub.add_parser(c); s.add_argument("name"); s.add_argument("strategy")
    a = ap.parse_args(argv)
    if host is None:
        if hasattr(os, "geteuid") and os.geteuid() != 0:
            raise SystemExit("run as root")
        host = Host()
    try:
        {"show": lambda: show(host), "add": lambda: add(host, a.name, a.strategy),
         "remove": lambda: remove(host, a.name, a.strategy)}[a.cmd]()
    except la.RegistryError as e:
        raise SystemExit(f"registry: {e}")


if __name__ == "__main__":
    main()
