"""Phase 2 provisioner (docs/phase2-design.md, step P2.2): runs other users' strategies as the owner's bot runs them.

Root, every minute (raqm-users-provision.timer). Reads each user's desired state — /opt/raqm-users/desired/<uid>.json,
written by the API: environment, strategies, capital plan, risk limits, on/off; never keys — checks everything in it
itself, then for each user who passes every gate:
  - an OS user ru<20 hex of the uid> (all of that user's bots run as it; no user can read another's files);
  - their Binance keys, decrypted from the API's user vault, as a systemd credential /etc/raqm-users/<uid>/binance
    (root 0600; the service reads it through LoadCredential, bot._binance_keys never falls back to other keys);
  - their risk limits, capital plan and yes/no per strategy in their own ledger /var/lib/raqm-users/<uid>/risk;
  - raqm-user@<uid>--<strategy>.service per chosen strategy: bot.py --live, a drop-in written here.
A strategy or user switched off stops entering at once (their yes/no is emptied); its service keeps running until
it is flat — its positions exit on their own rules — then it is stopped and disabled. The keys are wiped once every
service of that user is stopped.

Gates: the user in the owner's allow-list (/etc/raqm-users/allow.list, one uid a line, its order = who gets a place
first), their audited consent (the API's user_live_activation record, enabled, exchange binance), keys in the vault.
P2.2 is Demo only: any other environment is refused here, whatever the desired state says. Capacity cap: MAX_USERS
users × MAX_STRATEGIES strategies (≈140 MB per bot process, measured 2026-11-01).

  /opt/raqm-live/venv/bin/python -E -s /opt/raqm-live/scripts/provision_users.py [--dry-run]
"""
import json, os, re, sqlite3, stat, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESIRED = Path("/opt/raqm-users/desired")
ALLOW = Path("/etc/raqm-users/allow.list")
CRED_ROOT = Path("/etc/raqm-users")
DATA_ROOT = Path("/var/lib/raqm-users")
APPLIED = Path("/var/lib/raqm-users-applied")   # root's record of what was applied, outside every user's folder
IPC_ROOT = Path("/opt/raqm-users/ipc")
UNIT_DIR = Path("/etc/systemd/system")
CODE = Path("/opt/raqm-users/code")   # the owner's code at the same commit, readable by users' accounts (setup-live.sh)
VAULT = Path("/opt/raqm-api/app/backend/user_vault.json")
API_ENV = Path("/opt/raqm-api/.env")
CONSENT_DB = Path("/opt/raqm-api/app/user_live_activation.sqlite3")

ENVS_ALLOWED = ("demo",)      # P2.2: real money is refused in code, not by a setting
MAX_USERS, MAX_STRATEGIES = 4, 2
STRATEGIES = ("trend_daily", "vol_breakout", "rsi2_pullback", "trend_breakout", "listing_short", "momentum_ls", "ratio_trend")
EXTRA_ARGS = {"trend_daily": "--universe 10"}      # as the owner's /opt/raqm-live/strategies/*.env
UID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# the per-user bounds of the existing consent record (backend/app/user_live_activation.py)
BOUNDS = {"leverage": (1, 5), "risk_per_trade_pct": (0.01, 1.0), "max_aggregate_risk_pct": (0.01, 3.0),
          "capital_usdt": (0.0, 1_000_000.0), "capital_margin_override_usdt": (0.0, 100_000.0)}


def os_user(uid):
    return "ru" + uid.replace("-", "")[:20]


def unit(uid, strategy):
    return f"raqm-user@{uid}--{strategy}.service"


def validate(uid, doc):
    """The desired state, checked as if hostile (written by a less trusted process). ValueError on anything off."""
    if not UID_RE.match(uid) or doc.get("user_id") != uid:
        raise ValueError("user id")
    env = doc.get("env")
    if env not in ENVS_ALLOWED:
        raise ValueError(f"environment {env!r} not allowed")
    strategies = doc.get("strategies") or []
    if not isinstance(strategies, list) or len(set(strategies)) != len(strategies) or any(s not in STRATEGIES for s in strategies):
        raise ValueError("strategies")
    if len(strategies) > MAX_STRATEGIES:
        raise ValueError(f"more than {MAX_STRATEGIES} strategies")
    clean = {"env": env, "enabled": doc.get("enabled") is True, "strategies": list(strategies)}
    for k, (lo, hi) in BOUNDS.items():
        v = doc.get(k, 0 if k.startswith("capital") else None)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
            raise ValueError(f"{k} out of bounds")
        clean[k] = float(v)
    clean["leverage"] = int(clean["leverage"])
    if clean["risk_per_trade_pct"] > clean["max_aggregate_risk_pct"]:
        raise ValueError("risk per trade above the aggregate limit")
    if clean["capital_margin_override_usdt"] > clean["capital_usdt"]:
        raise ValueError("margin above the capital")
    return clean


def _read_small(path, limit=16384):
    """A regular file, not followed through a symlink, at most `limit` bytes."""
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > limit:
            raise ValueError("not a small regular file")
        return os.read(fd, limit + 1).decode("utf-8")
    finally:
        os.close(fd)


def read_desired(folder=DESIRED):
    """({uid: clean desired state}, {name: why refused})."""
    good, bad = {}, {}
    for f in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        uid = f.stem
        try:
            good[uid] = validate(uid, json.loads(_read_small(f)))
        except Exception as e:
            bad[f.name] = str(e)
    return good, bad


def read_allow(path=ALLOW):
    try:
        return [l.strip() for l in _read_small(path).splitlines() if UID_RE.match(l.strip())]
    except OSError:
        return []


def read_consent(path=CONSENT_DB):
    """{uid} with an enabled consent on binance (the existing audited record)."""
    try:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            return {r[0] for r in con.execute("SELECT user_id FROM user_live_activation WHERE enabled=1 AND exchange='binance'")}
        finally:
            con.close()
    except sqlite3.Error:
        return set()


def read_keys(uids, vault=VAULT, api_env=API_ENV):
    """{uid: (api key, secret)} for those with both in the API's user vault. Only VAULT_MASTER_KEY is read from the
    API's environment file."""
    if not uids:
        return {}
    from cryptography.fernet import Fernet
    key = next((l.split("=", 1)[1].strip().strip('"').strip("'") for l in _read_small(api_env, 65536).splitlines()
                if l.startswith("VAULT_MASTER_KEY=")), "")
    if not key or not vault.exists():
        return {}
    data = json.loads(Fernet(key.encode()).decrypt(_read_small(vault, 1 << 20).encode()).decode())
    out = {}
    for uid in uids:
        k = ((data.get(uid) or {}).get("binance") or {})
        if k.get("apiKey") and k.get("secret"):
            out[uid] = (k["apiKey"], k["secret"])
    return out


def is_flat(state_file):
    """No position and nothing pending in this bot's state. A missing file = never traded; unreadable = not flat."""
    if not state_file.exists():
        return True
    try:
        st = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        return False
    return not (st.get("positions") or st.get("pending_orders") or st.get("recovery_required"))


def plan(desired, allow, consent, keys, running, flat):
    """The actions to take, from what is wanted and what runs. Pure: everything it needs is passed in.
    running: {uid: {strategy}} services enabled now; flat(uid, strategy) -> bool."""
    actions, wanted = [], {}
    for uid in allow:                                         # the allow-list's order decides who gets the places
        d = desired.get(uid)
        if d and d["enabled"] and d["strategies"] and uid in consent and uid in keys and len(wanted) < MAX_USERS:
            wanted[uid] = d
    for uid, d in wanted.items():
        actions.append(("user", uid))
        actions.append(("keys", uid))
        actions.append(("limits", uid, d))
        for s in d["strategies"]:
            actions.append(("ensure", uid, s, d, flat(uid, s)))
    for uid, now in running.items():
        keep = set(wanted[uid]["strategies"]) if uid in wanted else set()
        if uid not in wanted:
            actions.append(("no_entries", uid))               # entries stop at once; open positions still exit
        stopping = [s for s in sorted(now - keep)]
        for s in stopping:
            if flat(uid, s):
                actions.append(("stop", uid, s))
        if uid not in wanted and all(flat(uid, s) for s in now):
            actions.append(("wipe_keys", uid))
    return actions


def dropin(uid, s, d):
    """The per-instance settings of raqm-user@.service."""
    data = DATA_ROOT / uid
    ipc = IPC_ROOT / uid / s
    args = f"--leverage {d['leverage']} --amount {max(d['capital_margin_override_usdt'], 10):g} {EXTRA_ARGS.get(s, '')} --poll 60".split()
    return "\n".join([
        "# written by scripts/provision_users.py — do not edit by hand",
        "[Service]",
        f"User={os_user(uid)}", f"Group={os_user(uid)}",
        f"Environment=BINANCE_ENV={d['env']}",
        f"Environment=RAQM_RISK_DIR={data / 'risk'}",
        f"Environment=RAQM_IPC_DIR={ipc}",
        f"LoadCredential=binance:{CRED_ROOT / uid / 'binance'}",
        f"ReadWritePaths={data / 'risk'} {data / 'state'} {ipc}",
        "ExecStart=",
        f"ExecStart={CODE}/venv/bin/python -E -s -u bot.py --live --expect-env {d['env']} --strategy {s} "
        f"{' '.join(args)} --state {data / 'state' / (s + '.json')}",
        ""])


class System:
    """What apply() does to the machine; tests pass a recording fake."""
    def run(self, *cmd):
        subprocess.run(cmd, check=True, capture_output=True, text=True)

    def write(self, path, text, mode, owner=None):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), mode)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(tmp, mode)
        if owner: self.run("chown", owner, str(tmp))
        os.replace(tmp, path)

    def read(self, path):
        try: return path.read_text(encoding="utf-8")
        except FileNotFoundError: return None

    def remove(self, path):
        try: path.unlink()
        except FileNotFoundError: pass

    def ensure_user(self, uid):
        name = os_user(uid)
        r = subprocess.run(["getent", "passwd", name], capture_output=True, text=True)
        if r.returncode == 0:
            if r.stdout.split(":")[4] != uid:
                raise RuntimeError(f"OS user {name} exists for someone else")
            return
        self.run("useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin", "--comment", uid, name)

    def own_dir(self, path, user, group, mode):
        """A folder owned by the user, in a parent only root can change: created if missing, never through a
        symlink (a user could otherwise point it at a system folder and have root hand that over)."""
        import grp, pwd
        try:
            os.mkdir(path, mode)
        except FileExistsError:
            pass
        if not stat.S_ISDIR(os.lstat(path).st_mode):
            raise RuntimeError(f"{path} is not a plain folder")
        os.chown(path, pwd.getpwnam(user).pw_uid, grp.getgrnam(group).gr_gid, follow_symlinks=False)
        os.chmod(path, mode)          # a plain folder (checked above, in a parent only root can change)

    def set_limits(self, uid, d):
        """The user's ledger and yes/no per strategy. Root makes the folders (their parents are root's); what is inside
        the ledger folder is written as the user, never by root."""
        name = os_user(uid)
        for parent in (DATA_ROOT / uid, IPC_ROOT / uid):          # root's, so the user can't swap what is below
            parent.mkdir(parents=True, exist_ok=True)
            if parent.is_symlink() or os.lstat(parent).st_uid != 0:
                raise RuntimeError(f"{parent} is not root's")
            os.chmod(parent, 0o755)
        self.own_dir(DATA_ROOT / uid / "risk", name, name, 0o700)
        self.own_dir(DATA_ROOT / uid / "state", name, name, 0o700)
        for s in d["strategies"]:
            self.own_dir(IPC_ROOT / uid / s, name, "raqmapi", 0o2770)   # the API reads status, writes close requests
        risk = DATA_ROOT / uid / "risk"
        code = ("import sys; sys.path.insert(0, 'backend'); from pathlib import Path; from app import risk_manager as r, live_activation as a;"
                f"p = Path({str(risk)!r}); r.update_limits(p / 'risk_state.json', {json.dumps(_limits(d))});"
                f"a.set_demo_strategies(p / 'live_activation.sqlite3', strategies={d['strategies']!r}, set_by='provisioner')")
        self.run("runuser", "-u", os_user(uid), "--", f"{CODE}/venv/bin/python", "-E", "-s", "-c", f"import os; os.chdir({str(CODE)!r}); {code}")

    def no_entries(self, uid):
        risk = DATA_ROOT / uid / "risk"
        code = (f"import sys; sys.path.insert(0, 'backend'); from pathlib import Path; from app import live_activation as a;"
                f"a.set_demo_strategies(Path({str(risk)!r}) / 'live_activation.sqlite3', strategies=[], set_by='provisioner')")
        self.run("runuser", "-u", os_user(uid), "--", f"{CODE}/venv/bin/python", "-E", "-s", "-c", f"import os; os.chdir({str(CODE)!r}); {code}")

    def running(self):
        """{uid: {strategy}} of the raqm-user@ services enabled now."""
        out = {}
        for f in UNIT_DIR.glob("raqm-user@*--*.service.d/user.conf"):
            inst = f.parent.name[len("raqm-user@"):-len(".service.d")]
            uid, _, s = inst.partition("--")
            if UID_RE.match(uid) and s in STRATEGIES:
                out.setdefault(uid, set()).add(s)
        return out


def _limits(d):
    return {"risk_per_trade_pct": d["risk_per_trade_pct"], "max_aggregate_risk_pct": d["max_aggregate_risk_pct"],
            "max_correlated_risk_pct": d["max_aggregate_risk_pct"], "capital_usdt": d["capital_usdt"],
            "capital_margin_override_usdt": d["capital_margin_override_usdt"]}


def apply(actions, keys, sys_=None, log=print):
    sys_ = sys_ or System()
    reload = False
    for a in actions:
        kind, uid = a[0], a[1]
        try:
            if kind == "user":
                sys_.ensure_user(uid)
            elif kind == "keys":
                ak, sc = keys[uid]
                text, path = f"BINANCE_API_KEY={ak}\nBINANCE_SECRET={sc}\n", CRED_ROOT / uid / "binance"
                if sys_.read(path) != text:      # new keys reach a running bot at its next start (systemd copies them)
                    sys_.write(path, text, 0o600)
            elif kind == "limits":
                applied, want = APPLIED / f"{uid}.json", json.dumps(a[2], sort_keys=True)
                if sys_.read(applied) != want:
                    sys_.set_limits(uid, a[2]); sys_.write(applied, want, 0o600)
            elif kind == "ensure":
                # new: write and start. Changed settings: only while flat (a restart mid-order goes to review), else
                # left for a later run. Same: nothing.
                _, _, s, d, is_flat_now = a
                conf, text = UNIT_DIR / f"raqm-user@{uid}--{s}.service.d" / "user.conf", dropin(uid, s, d)
                old = sys_.read(conf)
                if old == text:
                    continue
                if old is not None and not is_flat_now:
                    log(f"{unit(uid, s)}: new settings wait until it is flat"); continue
                sys_.write(conf, text, 0o644)
                sys_.run("systemctl", "daemon-reload")
                sys_.run("systemctl", "enable", unit(uid, s)); sys_.run("systemctl", "restart", unit(uid, s))
                log(f"{'started' if old is None else 'restarted with new settings'} {unit(uid, s)}")
            elif kind == "no_entries":
                sys_.no_entries(uid)
            elif kind == "stop":
                s = a[2]
                sys_.run("systemctl", "disable", "--now", unit(uid, s))
                sys_.remove(UNIT_DIR / f"raqm-user@{uid}--{s}.service.d" / "user.conf")
                reload = True
                log(f"stopped {unit(uid, s)} (flat)")
            elif kind == "wipe_keys":
                sys_.remove(CRED_ROOT / uid / "binance")
                log(f"keys wiped for {uid}")
        except Exception as e:                         # one user's failure never stops the others
            log(f"{kind} {uid}: {type(e).__name__}: {e}")
    if reload:
        sys_.run("systemctl", "daemon-reload")


def main(argv=None):
    dry = "--dry-run" in (argv if argv is not None else sys.argv[1:])
    desired, bad = read_desired()
    for name, why in bad.items():
        print(f"refused {name}: {why}")
    allow, consent = read_allow(), read_consent()
    keys = read_keys([u for u in allow if u in desired])
    sys_ = System()
    running = sys_.running()
    actions = plan(desired, allow, consent, keys, running, lambda u, s: is_flat(DATA_ROOT / u / "state" / f"{s}.json"))
    if dry:
        for a in actions: print(a[:3])
        return
    apply(actions, keys, sys_)


if __name__ == "__main__":
    main()
