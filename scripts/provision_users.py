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
first) or approved by the owner on the site (approved.list in the request folder: the owner's invitation or the admin
page, plan 4.1), a key that is not one of the owner's own bots' keys, their audited consent (the API's user_live_activation record, enabled, exchange binance), keys in the vault.
Real money (owner, 2026-11-05 — docs/users-real-money-plan.md): an invited user, momentum_ls only, starts only while
root's switch LIVE_SWITCH exists, their real-money consent is for exactly the capital and margin they now ask for, and
their key passes the preflight's checks on Binance itself (withdrawals off, this server's IP only, futures on, one-way,
a balance, no position the bot didn't open). Their service then gets the server's live switch, their account name and
root's ceilings from the plan they accepted, and their ledger an activation record bound to the deployed commit's
readiness evidence. Without any of it nothing real starts. Capacity cap: MAX_USERS users × MAX_STRATEGIES strategies
(≈140 MB per bot process, measured 2026-11-01).

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
APPROVED = DESIRED / "approved.list"   # the owner's approvals from the site (backend/app/user_approvals.py)
OWNER_ENV_FILES = (Path("/opt/raqm-live/.env.live"), Path("/opt/raqm-live/.env.real"))
LIVE_SWITCH = CRED_ROOT / "live.enabled"        # root's: real money for users on; absent = every user Demo only
READINESS = Path("/opt/raqm-api/app/readiness_evidence.json")   # the owner's signed-off evidence (docs/live-small-size-plan.md §4)
USER_DAILY_LOSS_PCT, USER_DRAWDOWN_PCT = 20.0, 45.0              # each user's kill switch, the owner's own values

sys.path.insert(0, str(ROOT / "backend"))
# the rules shared with the API (the same checks on both sides): environments, the cap, the strategies, the bounds
from app.user_bots import ENVS_ALLOWED, MAX_USERS, MAX_STRATEGIES, STRATEGIES, UID_RE, BOUNDS, SITE_LIVE_SWITCH, validate, strategy_policy  # noqa: E402,F401

EXTRA_ARGS = {"trend_daily": "--universe 10"}      # as the owner's /opt/raqm-live/strategies/*.env
NO_ENTRIES = '"no entries"'   # the applied record while a user is wound down


def os_user(uid):
    return "ru" + uid.replace("-", "")[:20]


def unit(uid, strategy):
    return f"raqm-user@{uid}--{strategy}.service"


def ipc_instance(uid, strategy):
    return IPC_ROOT / f"{uid}--{strategy}"


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


def _uids(path):
    try:
        return [l.strip() for l in _read_small(path).splitlines() if UID_RE.match(l.strip())]
    except OSError:
        return []


def read_allow(path=ALLOW, approved=None):
    """Root's allow-list first, then the owner's approvals from the site (APPROVED, written by the API on the owner's
    invitation or the admin page's button — plan 4.1), each in its own order, no repeats."""
    out = []
    for uid in _uids(path) + _uids(APPROVED if approved is None else approved):
        if uid not in out: out.append(uid)
    return out


def owner_keys(files=OWNER_ENV_FILES):
    """The API keys the owner's own bots use (Demo and real). A user's bot on one of them would trade the owner's
    account next to the owner's bots — their trades would mix with the measurement and the real money."""
    out = set()
    for f in files:
        try:
            for l in _read_small(f).splitlines():
                if l.startswith("BINANCE_API_KEY="):
                    v = l.split("=", 1)[1].strip().strip('"').strip("'")
                    if v: out.add(v)
        except OSError:
            pass
    return out


def read_consent(path=CONSENT_DB):
    """{uid: {"env", "capital", "margin"}} for an enabled consent on binance (the existing audited record; records from
    before the environment was recorded are real-money ones; capital and margin are those of a real-money consent).
    No record yet = nobody. A record that can't be read now (locked while the API writes) raises: the run is skipped,
    never read as "nobody consents" — that winds everyone down."""
    if not path.exists():
        return {}
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=10)
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(user_live_activation)")}
        env = "environment" if "environment" in cols else "'live'"
        cap = "capital_usdt" if "capital_usdt" in cols else "NULL"
        mar = "margin_usdt" if "margin_usdt" in cols else "NULL"
        return {r[0]: {"env": r[1], "capital": r[2], "margin": r[3]} for r in
                con.execute(f"SELECT user_id, {env}, {cap}, {mar} FROM user_live_activation WHERE enabled=1 AND exchange='binance'")}
    finally:
        con.close()


def consent_ok(consent, uid, env, d=None):
    """A Demo bot needs a consent for Demo or real money. A real-money bot needs a real-money consent for exactly the
    capital and margin it now asks for (the risk the user saw and accepted); a change of either asks again."""
    c = consent.get(uid)
    c = {"env": c} if isinstance(c, str) else (c or {})
    if env == "demo":
        return c.get("env") in ("demo", "live")
    if c.get("env") != "live" or d is None:
        return False
    try:
        return (abs(float(c["capital"]) - float(d["capital_usdt"])) < 0.005
                and abs(float(c["margin"]) - float(d["capital_margin_override_usdt"])) < 0.005)
    except (KeyError, TypeError, ValueError):
        return False


def live_switch_on(path=LIVE_SWITCH):
    """Root's file, a regular one owned by root: anything else (missing, a link, someone else's) is off."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISREG(st.st_mode) and st.st_uid == 0


def site_switch_on(folder=DESIRED):
    """The owner's switch from the admin page (user_bots.write_site_live): on only if its small regular file says
    exactly true. Missing, unreadable, a link or anything else is off."""
    try:
        doc = json.loads(_read_small(Path(folder) / SITE_LIVE_SWITCH, 4096))
    except Exception:
        return False
    return isinstance(doc, dict) and doc.get("on") is True


def real_money_on(path=LIVE_SWITCH, folder=DESIRED):
    """Real money for users: root's main lock (out of the site's reach) and the owner's switch on the site."""
    return live_switch_on(path) and site_switch_on(folder)


def key_checks(keys):
    """(ok, why) for a user's real-money key, on Binance itself — the owner's preflight rows (scripts/live_preflight.py):
    withdrawals off, this server's IP only, futures on, one-way, a balance, no position the bot didn't open."""
    import live_preflight
    try:
        rows = live_preflight.check_binance({"BINANCE_API_KEY": keys[0], "BINANCE_SECRET": keys[1]}, "momentum_ls", None, None, "")
    except Exception as e:
        return False, f"key check failed: {type(e).__name__}"
    bad = [name for name, ok, _ in rows if not ok]
    return (not bad and bool(rows)), (", ".join(bad) if bad else None)


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


def plan(desired, allow, consent, keys, running, flat, owner_key=(), live_on=False, key_ok=None):
    """The actions to take, from what is wanted and what runs. Pure: everything it needs is passed in.
    running: {uid: {strategy}} services enabled now; flat(uid, strategy) -> bool; owner_key: users whose saved key
    is one of the owner's own (they get no bot and their page says so). Real money also needs live_on (root's switch)
    and key_ok[uid] = (True, None) from key_checks."""
    actions, wanted = [], {}
    keys = {u: k for u, k in keys.items() if u not in owner_key}
    key_ok = key_ok or {}

    def live_ready(uid, d):
        return d["env"] != "live" or (live_on and (key_ok.get(uid) or (False, None))[0])
    # who gets the places: users already running keep theirs (a newcomer never pushes out someone with open trades),
    # then the allow-list's order
    order = [u for u in allow if u in running] + [u for u in allow if u not in running]
    for uid in order:
        d = desired.get(uid)
        if (d and d["enabled"] and d["strategies"] and consent_ok(consent, uid, d["env"], d) and uid in keys
                and live_ready(uid, d) and len(wanted) < MAX_USERS):
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
        live = d["env"] == "live"
        state = ("off" if not (d["enabled"] and d["strategies"]) else "waiting_approval" if uid not in allow
                 else "no_consent" if not consent_ok(consent, uid, d["env"], d) else "owner_key" if uid in owner_key
                 else "no_keys" if uid not in keys
                 else "live_off" if live and not live_on
                 else "key_refused" if live and not (key_ok.get(uid) or (False, None))[0]
                 else "running" if uid in wanted else "no_place")
        answer = {"state": state, "strategies": d["strategies"] if uid in wanted else []}
        if state == "key_refused":
            answer["why"] = (key_ok.get(uid) or (False, "not checked yet"))[1] or "not checked yet"
        actions.append(("answer", uid, answer))
    return actions


def dropin(uid, s, d):
    """The per-instance settings of raqm-user@.service."""
    data = DATA_ROOT / uid
    ipc = ipc_instance(uid, s)
    # --amount is the bot's fallback only: with the capital plan in the ledger the margin comes from the plan
    args = f"--leverage {d['leverage']} --amount {d['capital_margin_override_usdt']:.2f} {EXTRA_ARGS.get(s, '')} --poll 60".split()
    live = []
    if d["env"] == "live":
        # the server's switch for this service, the account its activation record names, and root's ceilings — the
        # plan the user accepted (per trade = one stop, aggregate = the basket at its stops), never above it
        caps = {"RISK_PER_TRADE_PCT": d["risk_per_trade_pct"], "AGGREGATE_RISK_PCT": d["max_aggregate_risk_pct"],
                "CORRELATED_RISK_PCT": d["max_aggregate_risk_pct"], "DAILY_LOSS_PCT": USER_DAILY_LOSS_PCT,
                "DRAWDOWN_PCT": USER_DRAWDOWN_PCT}
        live = ["Environment=ALLOW_LIVE_TRADING=true", f"Environment=BINANCE_LIVE_ACCOUNT={uid}"] + \
               [f"Environment=RAQM_CAP_{k}={float(v):g}" for k, v in caps.items()]
    return "\n".join([
        "# written by scripts/provision_users.py — do not edit by hand",
        "[Service]",
        f"User={os_user(uid)}", f"Group={os_user(uid)}",
        f"Environment=BINANCE_ENV={d['env']}", *live,
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
        for parent in (DATA_ROOT / uid, IPC_ROOT):                 # root's, so the user can't swap what is below
            self.root_dir(parent)
        self.own_dir(DATA_ROOT / uid / "risk", name, name, 0o700)
        self.own_dir(DATA_ROOT / uid / "state", name, name, 0o700)
        # the strategy folder and its request folders: owner the user's bot, group the API, setgid — set by root on an
        # O_NOFOLLOW handle (a user can't set the API's group). The API writes requests readable by the bot (0644 in
        # a folder only the two can enter); the bot's status and results get the API's group from the setgid bit.
        for s in d["strategies"]:
            for p in (ipc_instance(uid, s), ipc_instance(uid, s) / "commands", ipc_instance(uid, s) / "results"):
                self.own_dir(p, name, "raqmapi", 0o2770)
        risk = DATA_ROOT / uid / "risk"
        # the ledger, capital plan and yes/no per strategy: inside the user's own folder, so written as the user
        code = ("import sys; sys.path.insert(0, 'backend'); from pathlib import Path; from app import risk_manager as r, live_activation as a;"
                f"p = Path({str(risk)!r}); r.update_limits(p / 'risk_state.json', {json.dumps(_limits(d))});"
                f"a.set_demo_strategies(p / 'live_activation.sqlite3', strategies={d['strategies']!r}, set_by='provisioner')")
        if d["env"] == "live":
            # the real-money activation record the bot checks before every entry (bot._live_activation_gate): this user's
            # account, momentum only, readiness derived from the owner's evidence for the deployed commit — a missing or
            # stale evidence makes activate() raise, so set_limits fails and nothing starts (fail closed)
            evidence, commit = self.readiness
            code += ("; import os, json; os.environ['ALLOW_LIVE_TRADING'] = 'true';"
                     f"a.activate(p / 'live_activation.sqlite3', environment='live', account={uid!r},"
                     f" approved_by='provisioner: the owner invitation', strategies={d['strategies']!r},"
                     f" risk_allocation={json.dumps({s: 1.0 / len(d['strategies']) for s in d['strategies']})},"
                     f" readiness_evidence=json.loads({json.dumps(evidence)!r}), expected_reviewed_commit_sha={commit!r})")
        self.as_user(uid, code)

    readiness = (None, None)        # (the owner's evidence as JSON text, the deployed commit): main() reads them as root

    def no_entries(self, uid):
        risk = DATA_ROOT / uid / "risk"
        code = (f"import sys; sys.path.insert(0, 'backend'); from pathlib import Path; from app import live_activation as a;"
                f"a.set_demo_strategies(Path({str(risk)!r}) / 'live_activation.sqlite3', strategies=[], set_by='provisioner');"
                f"a.revoke(Path({str(risk)!r}) / 'live_activation.sqlite3', reason='provisioner: switched off')")
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
    out = {"risk_per_trade_pct": d["risk_per_trade_pct"], "max_aggregate_risk_pct": d["max_aggregate_risk_pct"],
           "max_correlated_risk_pct": d["max_aggregate_risk_pct"], "capital_usdt": d["capital_usdt"],
           "capital_margin_override_usdt": d["capital_margin_override_usdt"]}
    if d.get("capital_reserve_pct") is not None:      # real money: the user's reserve (the whole basket fits after it)
        out["capital_reserve_pct"] = d["capital_reserve_pct"]
    return out


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
    mine = owner_keys()
    owner_key = {u for u, (k, _) in keys.items() if k in mine}
    sys_ = System()
    running = sys_.running()
    live_on = real_money_on()
    key_ok = {}
    if live_on:
        try:
            sys_.readiness = (json.loads(_read_small(READINESS, 1 << 20)), _read_small(CODE / "DEPLOYED_COMMIT", 128).strip())
        except Exception as e:
            print(f"real money: readiness evidence or deployed commit unreadable ({type(e).__name__}) — no real-money bot starts")
        for uid, d in desired.items():
            if d["env"] != "live" or uid not in keys or uid in owner_key or not consent_ok(consent, uid, "live", d):
                continue
            d["_commit"] = sys_.readiness[1]          # a new deployment writes the activation record again
            # a running bot was checked when it started; a new one is checked on Binance now, before anything is written
            key_ok[uid] = (True, None) if uid in running else key_checks(keys[uid])
    actions = plan(desired, allow, consent, keys, running, lambda u, s: is_flat(DATA_ROOT / u / "state" / f"{s}.json"), owner_key,
                   live_on=live_on, key_ok=key_ok)
    actions += [("answer", name[:-5], {"state": "refused", "why": why, "strategies": []})
                for name, why in bad.items() if UID_RE.match(name[:-5])]
    if dry:
        for a in actions: print(a[:3])
        return
    apply(actions, keys, sys_)


if __name__ == "__main__":
    main()
