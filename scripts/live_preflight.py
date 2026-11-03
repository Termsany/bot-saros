"""Real-money preflight: every check that must pass before a raqm-live@<strategy> unit is started.

Read only — it never sends an order, never changes a setting and never prints a key. Each line says what is wrong
and what to do; the exit code is 0 only when everything passes. The Binance checks use the real account's keys
(.env.real) on read-only endpoints: the key must have withdrawals off and be restricted to this server's IP, the
account must be in one-way mode (the bot's orders assume it), and the strategy's whole basket must fit root's risk
ceilings at the plan's margin.

  sudo /opt/raqm-live/venv/bin/python -I /opt/raqm-live/scripts/live_preflight.py --strategy momentum_ls
"""
import argparse, json, os, re, stat, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend.app import risk_manager as riskmgr
from backend.app import testnet_readiness

PATHS = {
    "live": Path("/opt/raqm-live"),
    "api_env": Path("/opt/raqm-api/.env"),
    "evidence": Path("/opt/raqm-api/app/readiness_evidence.json"),   # the API's BOT_DIR
    "ledger": Path("/opt/raqm-risk/risk_state.json"),
    "unit": Path("/etc/systemd/system/raqm-live@.service"),
}
# legs a strategy opens at once and its protective stop (bot.py: MOM, the single-leg adapters' 40% plan stop)
BASKET = {"momentum_ls": 10, "ratio_trend": 2}
STOP_DISTANCE = riskmgr.PLAN_STOP_LOSS
SHA40 = re.compile(r"^[0-9a-f]{40}$")


def parse_env(path):
    """KEY=VALUE lines of an EnvironmentFile (quotes stripped); {} when it can't be read."""
    out = {}
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line: continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip("'\"")
    except OSError:
        pass
    return out


def _owner(path):
    try:
        import pwd
        return pwd.getpwuid(os.stat(path).st_uid).pw_name
    except (ImportError, KeyError, OSError):
        return None


def _mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def file_ok(path, owner, mode=0o600):
    """(ok, why): a regular file, not a link, owned by `owner`, with exactly `mode`."""
    p = Path(path)
    if p.is_symlink(): return False, f"{p} is a symlink"
    if not p.is_file(): return False, f"{p} is missing"
    have = _mode(p)
    if have != mode: return False, f"{p} has mode {have:o}, needs {mode:o}"
    who = _owner(p)
    if who != owner: return False, f"{p} is owned by {who}, needs {owner}"
    return True, f"{p} ({owner}, {mode:o})"


def check_files(paths, strategy):
    live = paths["live"]; rows = []
    sha = (live / "DEPLOYED_COMMIT").read_text(encoding="utf-8").strip() if (live / "DEPLOYED_COMMIT").is_file() else ""
    rows.append(("deployed commit", bool(SHA40.match(sha)), sha or "no DEPLOYED_COMMIT: run setup-live.sh <sha>"))

    ok, why = file_ok(live / ".env.real", "raqmlive")
    keys = parse_env(live / ".env.real")
    if ok and not (keys.get("BINANCE_API_KEY") and keys.get("BINANCE_SECRET")):
        ok, why = False, ".env.real has no BINANCE_API_KEY / BINANCE_SECRET line"
    rows.append(("real account keys file", ok, why if not ok else "keys present (not shown)"))

    ok, why = file_ok(live / "allow-live.env", "root")
    allow = parse_env(live / "allow-live.env")
    rows.append(("allow-live.env (root, 600)", ok, why))
    rows.append(("ALLOW_LIVE_TRADING=true for the bot", allow.get("ALLOW_LIVE_TRADING", "").lower() == "true", "in allow-live.env"))
    rows.append(("BINANCE_LIVE_ACCOUNT", bool(allow.get("BINANCE_LIVE_ACCOUNT")), allow.get("BINANCE_LIVE_ACCOUNT") or "set a name in allow-live.env; the dashboard's activation uses the same"))
    caps = None
    saved = {k: os.environ.pop(k, None) for k in riskmgr.HARD_CAP_ENV.values()}
    try:
        os.environ.update({k: allow[k] for k in riskmgr.HARD_CAP_ENV.values() if k in allow})
        caps = riskmgr.hard_caps(required=True)
        rows.append(("risk ceilings (RAQM_CAP_*_PCT)", True, ", ".join(f"{k} {v:g}%" for k, v in caps.items())))
    except ValueError as e:
        rows.append(("risk ceilings (RAQM_CAP_*_PCT)", False, f"{e} — all five in allow-live.env (deploy/vps/README.md)"))
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None)
            if v is not None: os.environ[k] = v

    unit = paths["unit"].read_text(encoding="utf-8") if paths["unit"].is_file() else ""
    exec_line = next((l for l in unit.splitlines() if l.startswith("ExecStart=")), "")
    rows.append(("raqm-live@ unit installed", "--expect-env live" in exec_line,
                 "installed" if exec_line else "install deploy/vps/raqm-live@.service (README, Real money step 3)"))

    api = parse_env(paths["api_env"])
    rows.append(("ALLOW_LIVE_TRADING=true for the API", api.get("ALLOW_LIVE_TRADING", "").lower() == "true", "in /opt/raqm-api/.env (the dashboard's yes/no needs it)"))
    expected = api.get("READINESS_EXPECTED_COMMIT_SHA", "").lower()
    rows.append(("readiness bound to the deployed commit", bool(SHA40.match(expected)) and expected == sha,
                 f"READINESS_EXPECTED_COMMIT_SHA={expected or '(unset)'} vs deployed {sha or '(none)'}"))
    try:
        evidence = json.loads(paths["evidence"].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        evidence = None
    ready = testnet_readiness.build_live_activation_readiness(strategies=[strategy], evidence=evidence or {}, live_enabled=True,
                                                              expected_reviewed_commit_sha=expected or None)
    rows.append((f"readiness evidence for {strategy}", ready.get(strategy) is True,
                 "valid v2 evidence for this commit" if ready.get(strategy) else
                 f"{paths['evidence']} {'missing' if evidence is None else 'not valid for this strategy/commit'}: needs the Demo results and two independent reviewers"))
    return rows, caps


def check_ledger(paths):
    try:
        st = riskmgr.load_risk_state(paths["ledger"])
    except Exception as e:
        return [("real-money risk ledger", False, f"{paths['ledger']}: {e}")], None
    ks = st.get("kill_switch") or {}
    return [("real-money risk ledger", True, str(paths["ledger"])),
            ("kill switch clear", not ks.get("tripped"), ks.get("reason") or "clear")], st


def basket_fits(strategy, margin, leverage, equity, limits, caps):
    """(ok, why): the strategy's whole basket, every leg at its stop, inside the limits the gate applies — the lower of
    the dashboard's and root's ceiling. Half the legs share a side (momentum_ls: 5 longs, 5 shorts) and a correlation
    group (the picks are alts), so that half counts against the correlated limit."""
    legs = BASKET.get(strategy, 1)
    leg_pct = margin * leverage * STOP_DISTANCE / equity * 100.0
    total, side = leg_pct * legs, leg_pct * -(-legs // 2)
    why = f"{legs} leg(s) × {leg_pct:.2f}% = {total:.2f}% at margin ${margin:g} x{leverage} on ${equity:,.0f}"
    for value, key, what in ((leg_pct, "risk_per_trade_pct", "one leg"), (total, "max_aggregate_risk_pct", "the basket"),
                             (side, "max_correlated_risk_pct", "one side of the basket")):
        limit = float(limits[key])
        if value > limit + 1e-9:
            by = "root's ceiling" if limit >= float(caps[key]) else "the dashboard's limit (الإدارة ← المخاطر)"
            return False, why + f" — {what} ({value:.2f}%) is above {key} {limit:g}%, set by {by}"
    return True, why


def check_binance(keys, strategy, caps, ledger_state, args_line, clients=None):
    """The real account, on read-only endpoints. `clients` = (futures, spot) for tests; ccxt otherwise."""
    rows = []
    if not (keys.get("BINANCE_API_KEY") and keys.get("BINANCE_SECRET")):
        return [("Binance real account", False, "skipped: no keys in .env.real")]
    if clients is None:
        import ccxt
        conf = {"apiKey": keys["BINANCE_API_KEY"], "secret": keys["BINANCE_SECRET"], "enableRateLimit": True}
        clients = (ccxt.binanceusdm(dict(conf)), ccxt.binance(dict(conf)))
    fut, spot = clients
    try:
        r = spot.sapi_get_account_apirestrictions()
        rows.append(("key: withdrawals OFF", r.get("enableWithdrawals") is False, "enableWithdrawals=" + str(r.get("enableWithdrawals"))))
        rows.append(("key: restricted to this server's IP", r.get("ipRestrict") is True, "ipRestrict=" + str(r.get("ipRestrict"))))
        rows.append(("key: futures trading on", r.get("enableFutures") is True, "enableFutures=" + str(r.get("enableFutures"))))
    except Exception as e:
        rows.append(("key permissions readable", False, f"{type(e).__name__}: {str(e)[:160]}"))
    try:
        hedged = fut.fetch_position_mode().get("hedged")
        rows.append(("account in one-way mode", hedged is False, "hedge mode is ON: switch the futures account to one-way" if hedged else "one-way"))
    except Exception as e:
        rows.append(("account position mode readable", False, f"{type(e).__name__}: {str(e)[:160]}"))
    try:
        usdt = fut.fetch_balance().get("USDT") or {}
        equity = float(usdt.get("total") or 0)
        rows.append(("USDT on the futures account", equity > 0, f"${equity:,.2f}"))
    except Exception as e:
        rows.append(("futures balance readable", False, f"{type(e).__name__}: {str(e)[:160]}")); equity = 0.0
    if caps and equity > 0:
        # sized as the bot sizes it: the dashboard's capital plan under root's ceilings, else the unit's --amount
        limits = {**riskmgr.DEFAULT_LIMITS, **((ledger_state or {}).get("limits") or {})}
        for k, c in caps.items():
            limits[k] = min(float(limits.get(k) if limits.get(k) is not None else c), c)
        plan = riskmgr.capital_plan(limits, equity) if ledger_state else None
        margin = float(plan["margin"]) if plan else _arg(args_line, "--amount", 100.0)
        rows.append((f"{strategy} basket fits the risk limits", *basket_fits(strategy, margin, int(_arg(args_line, "--leverage", 2)), equity, limits, caps)))
    return rows


def _arg(line, name, default):
    m = re.search(re.escape(name) + r"\s+([0-9.]+)", line or "")
    return float(m.group(1)) if m else float(default)


def run(paths, strategy, clients=None):
    rows, caps = check_files(paths, strategy)
    ledger_rows, ledger_state = check_ledger(paths)
    rows += ledger_rows
    args_line = parse_env(paths["live"] / "strategies" / f"{strategy}.env").get("RAQM_ARGS", "--leverage 2 --amount 100")
    rows += check_binance(parse_env(paths["live"] / ".env.real"), strategy, caps, ledger_state, args_line, clients)
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--strategy", default="momentum_ls")
    a = ap.parse_args()
    rows = run(PATHS, a.strategy)
    for name, ok, why in rows:
        print(f"{'✅' if ok else '❌'} {name} — {why}")
    bad = sum(1 for _, ok, _ in rows if not ok)
    print(f"\n{len(rows) - bad}/{len(rows)} passed" + ("" if not bad else f" — {bad} to fix before real money"))
    sys.exit(0 if not bad else 1)


if __name__ == "__main__":
    main()
