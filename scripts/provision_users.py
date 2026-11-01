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

sys.path.insert(0, str(ROOT / "backend"))
# the rules shared with the API (the same checks on both sides): Demo only, the cap, the strategies, the bounds
from app.user_bots import ENVS_ALLOWED, MAX_USERS, MAX_STRATEGIES, STRATEGIES, UID_RE, BOUNDS, validate  # noqa: E402,F401

EXTRA_ARGS = {"trend_daily": "--universe 10"}      # as the owner's /opt/raqm-live/strategies/*.env
NO_ENTRIES = '"no entries"'   # the applied record while a user is wound down


def os_user(uid):
    return "ru" + uid.replace("-", "")[:20]


def unit(uid, strategy):
    return f"raqm-user@{uid}--{strategy}.service"


def _read_small(path, limit=16384):
    """A regular file, not followed through a symlink, at most `limit` bytes. O_NONBLOCK: a FIFO planted in its place
    must not hang root's run (open blocks before the regular-file check could refuse it)."""
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
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
    """{uid: environment consented to} for an enabled consent on binance (the existing audited record; records from
    before the environment was recorded are real-money ones). No record yet = nobody. A record that can't be read now
    (locked while the API writes) raises: the run is skipped, never read as "nobody consents" — that winds everyone down."""
    if not path.exists():
        return {}
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=10)
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(user_live_activation)")}
        env = "environment" if "environment" in cols else "'live'"
        return {r[0]: r[1] for r in con.execute(f"SELECT user_id, {env} FROM user_live_activation WHERE enabled=1 AND exchange='binance'")}
    finally:
        con.close()


def consent_ok(consent, uid, env):
    """A Demo bot needs a consent for Demo or real money; a real-money bot (not allowed yet) a real-money one only."""
    return consent.get(uid) in (("demo", "live") if env == "demo" else ("live",))


def read_keys(uids, vault=VAULT, api_env=API_ENV):
    """{uid: (api key, secret)} for those with both in the API's user vault. Only VAULT_MASTER_KEY is read from the
    API's environment file."""
    if not uids:
        return {}
    from cryptography.fernet import Fernet
    key = next((l.split("=", 1)[1].strip().strip('"').strip("'") for l in _read_small(api_env, 65536).splitlines()
                if l.startswith("VAULT_MASTER_KEY=")), "")
    if not key:                       # a missing master key is a broken server, not "nobody has keys": skip the run
        raise RuntimeError("VAULT_MASTER_KEY not found in the API's environment file")
    if not vault.exists():
        return {}
    data = json.loads(Fernet(key.encode()).decrypt(_read_small(vault, 1 << 20).encode()).decode())
    out = {}
    for uid in uids:
        k = ((data.get(uid) or {}).get("binance") or {})
        ak, sc = str(k.get("apiKey") or ""), str(k.get("secret") or "")
        if ak and sc and not any(c.isspace() or c in "=\"'" for c in ak + sc):   # one line each in the credential
            out[uid] = (ak, sc)
    return out


def is_flat(state_file):
    """No position and nothing pending in this bot's state. A missing file = never traded; anything else that isn't a
    small regular file read without following a link (the user's own folder) = not flat."""
    try:
        st = json.loads(_read_small(state_file, 8 << 20))
    except FileNotFoundError:
        return True
    except Exception:
        return False
    return not (st.get("positions") or st.get("pending_orders") or st.get("recovery_required"))


def plan(desired, allow, consent, keys, running, flat):
    """The actions to take, from what is wanted and what runs. Pure: everything it needs is passed in.
    running: {uid: {strategy}} services enabled now; flat(uid, strategy) -> bool."""
    actions, wanted = [], {}
    # who gets the places: users already running keep theirs (a newcomer never pushes out someone with open trades),
    # then the allow-list's order
    order = [u for u in allow if u in running] + [u for u in allow if u not in running]
    for uid in order:
        d = desired.get(uid)
        if d and d["enabled"] and d["strategies"] and consent_ok(consent, uid, d["env"]) and uid in keys and len(wanted) < MAX_USERS:
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
    for uid, d in desired.items():                           # each user's page says where they stand
        state = ("off" if not (d["enabled"] and d["strategies"]) else "waiting_approval" if uid not in allow
                 else "no_consent" if not consent_ok(consent, uid, d["env"]) else "no_keys" if uid not in keys
                 else "running" if uid in wanted else "no_place")
        actions.append(("answer", uid, {"state": state, "strategies": d["strategies"] if uid in wanted else []}))
    return actions


def dropin(uid, s, d):
    """The per-instance settings of raqm-user@.service."""
    data = DATA_ROOT / uid
    ipc = IPC_ROOT / uid / s
    # --amount is the bot's fallback only: with the capital plan in the ledger the margin comes from the plan
    args = f"--leverage {d['leverage']} --amount {d['capital_margin_override_usdt']:.2f} {EXTRA_ARGS.get(s, '')} --poll 60".split()
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
        # on an open handle of the folder itself: O_NOFOLLOW refuses a link, so nothing can be swapped in between
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fchown(fd, pwd.getpwnam(user).pw_uid, grp.getgrnam(group).gr_gid)
            os.fchmod(fd, mode)
        finally:
            os.close(fd)

    def root_dir(self, path):
        """A folder of root's (a user's folder parent): created if missing, refused if it is a link or someone else's."""
        path.mkdir(parents=True, exist_ok=True)
        if path.is_symlink() or os.lstat(path).st_uid != 0:
            raise RuntimeError(f"{path} is not root's")
        os.chmod(path, 0o755)

    def set_limits(self, uid, d):
        """The user's ledger and yes/no per strategy. Root makes the folders (their parents are root's); what is inside
        the ledger folder is written as the user, never by root."""
        name = os_user(uid)
        for parent in (DATA_ROOT / uid, IPC_ROOT / uid):          # root's, so the user can't swap what is below
            self.root_dir(parent)
        self.own_dir(DATA_ROOT / uid / "risk", name, name, 0o700)
        self.own_dir(DATA_ROOT / uid / "state", name, name, 0o700)
        # the strategy folder and its request folders: owner the user's bot, group the API, setgid — set by root on an
        # O_NOFOLLOW handle (a user can't set the API's group). The API writes requests readable by the bot (0644 in
        # a folder only the two can enter); the bot's status and results get the API's group from the setgid bit.
        for s in d["strategies"]:
            for p in (IPC_ROOT / uid / s, IPC_ROOT / uid / s / "commands", IPC_ROOT / uid / s / "results"):
                self.own_dir(p, name, "raqmapi", 0o2770)
        risk = DATA_ROOT / uid / "risk"
        # the ledger, capital plan and yes/no per strategy: inside the user's own folder, so written as the user
        code = ("import sys; sys.path.insert(0, 'backend'); from pathlib import Path; from app import risk_manager as r, live_activation as a;"
                f"p = Path({str(risk)!r}); r.update_limits(p / 'risk_state.json', {json.dumps(_limits(d))});"
                f"a.set_demo_strategies(p / 'live_activation.sqlite3', strategies={d['strategies']!r}, set_by='provisioner')")
        self.as_user(uid, code)

    def no_entries(self, uid):
        risk = DATA_ROOT / uid / "risk"
        code = (f"import sys; sys.path.insert(0, 'backend'); from pathlib import Path; from app import live_activation as a;"
                f"a.set_demo_strategies(Path({str(risk)!r}) / 'live_activation.sqlite3', strategies=[], set_by='provisioner')")
        self.as_user(uid, code)

    def as_user(self, uid, code):
        """Python code run as the user, with an empty environment: nothing of root's process reaches their account."""
        self.run("runuser", "-u", os_user(uid), "--", "/usr/bin/env", "-i", "PATH=/usr/bin:/bin", f"{CODE}/venv/bin/python",
                 "-E", "-s", "-c", f"import os; os.chdir({str(CODE)!r}); {code}")

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
    reload, failed = False, set()
    for a in actions:
        kind, uid = a[0], a[1]
        if uid in failed and kind in ("keys", "limits", "ensure"):
            continue                  # never start a bot whose user, keys or limits weren't set up this run
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
                # once per wind-down; and the applied record says so, so coming back with the same settings writes
                # the user's yes/no per strategy again (otherwise it stayed empty: running, never entering)
                applied = APPLIED / f"{uid}.json"
                if sys_.read(applied) != NO_ENTRIES:
                    sys_.no_entries(uid); sys_.write(applied, NO_ENTRIES, 0o600)
            elif kind == "stop":
                s = a[2]
                sys_.run("systemctl", "disable", "--now", unit(uid, s))
                sys_.remove(UNIT_DIR / f"raqm-user@{uid}--{s}.service.d" / "user.conf")
                reload = True
                log(f"stopped {unit(uid, s)} (flat)")
            elif kind == "wipe_keys":
                sys_.remove(CRED_ROOT / uid / "binance")
                log(f"keys wiped for {uid}")
            elif kind == "answer":       # root's file in root's folder; the API reads it for the user's page
                path, text = IPC_ROOT / uid / "provision.json", json.dumps(a[2], sort_keys=True)
                if sys_.read(path) != text:          # the API only (other users can list the folders, not read this)
                    sys_.root_dir(IPC_ROOT / uid); sys_.write(path, text, 0o640, owner="root:raqmapi")
        except Exception as e:                         # one user's failure never stops the others
            log(f"{kind} {uid}: {type(e).__name__}: {e}")
            if kind in ("user", "keys", "limits"):
                failed.add(uid)
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
    actions += [("answer", name[:-5], {"state": "refused", "why": why, "strategies": []})
                for name, why in bad.items() if UID_RE.match(name[:-5])]
    if dry:
        for a in actions: print(a[:3])
        return
    apply(actions, keys, sys_)


if __name__ == "__main__":
    main()
