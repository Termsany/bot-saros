#!/bin/sh
# The real-orders bot (raqm-trend-demo.service) runs apart from the 7 paper bots: its own user, its own copy of the
# code that only root can change, its keys readable by that user alone. A compromised paper bot (user raqm, which
# can write /opt/raqm-bot) can then neither read the exchange keys nor change the code that trades.
#
# Usage (as root, after the commit was reviewed):  sh setup-live.sh <full 40-character commit sha>
# The code comes from a root-owned clone at that exact commit — never from /opt/raqm-bot or /opt/raqm-api, which the
# paper-bot and API users can write: copying from there handed them the real-money code at the next run (and
# running their venv's pip as root handed them root). Idempotent.
set -eu
SHA=${1:-}
echo "$SHA" | grep -qE '^[0-9a-f]{40}$' || { echo "usage: $0 <full commit sha of the reviewed head>" >&2; exit 2; }
L=/opt/raqm-live; B=/opt/raqm-bot; SRC=/root/raqm-src
[ -d "$SRC/.git" ] || git clone -q https://github.com/Termsany/bot-saros.git "$SRC"
git -C "$SRC" fetch -q origin
git -C "$SRC" cat-file -e "$SHA^{commit}" || { echo "commit $SHA not found on GitHub" >&2; exit 2; }
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
git -C "$SRC" archive "$SHA" | tar -x -C "$T"
id raqmlive >/dev/null 2>&1 || useradd --system --home-dir "$L" --no-create-home --shell /usr/sbin/nologin raqmlive
# group PERMISSION bits on the shared setgid dirs (/opt/raqm-risk, /opt/raqm-ipc) are useless without group
# MEMBERSHIP: raqmlive must also be in raqmapi's group, or whichever side didn't create a file first can't open it.
usermod -aG raqmapi raqmlive
install -d -o root -g raqmlive -m 750 "$L"
install -d -o raqmlive -g raqmlive -m 700 "$L/state"
for f in bot.py strategies_trend.py strategies_advanced.py strategies_wave.py; do install -m 644 -o root -g root "$T/$f" "$L/$f"; done
install -d -o root -g root -m 755 "$L/backend" "$L/backend/app"
# every backend module bot.py imports (stdlib only): order placement, multi-leg engine, execution checks, risk ledger, activation
for m in __init__ oco multi_leg_execution execution_safety risk_manager live_activation; do
    install -m 644 -o root -g root "$T/backend/app/$m.py" "$L/backend/app/$m.py"
done
# Phase 1 harness (scripts/demo_e2e.py): runs as raqmlive from this root-owned copy, refuses anything but Demo
install -d -o root -g root -m 755 "$L/scripts"
install -m 644 -o root -g root "$T/scripts/demo_e2e.py" "$L/scripts/demo_e2e.py"
echo "$SHA" > "$L/DEPLOYED_COMMIT"
# packages: only what the bot imports, pinned, from wheels (deploy/vps/live-requirements.txt)
[ -x "$L/venv/bin/python" ] || python3 -m venv "$L/venv"
"$L/venv/bin/pip" install -q --only-binary=:all: -r "$T/deploy/vps/live-requirements.txt"
# keys: only the key lines, never the whole file. /opt/raqm-bot is writable by the paper user: a whole-file copy
# carried any line it planted (PYTHONPATH=/opt/raqm-bot -> its ccxt.py runs with the keys). Symlinks are refused.
KEYS='^(BINANCE_API_KEY|BINANCE_SECRET|BINANCE_LIVE_ACCOUNT)='
if [ -L "$B/.env.demo" ] || [ -L "$L/.env.live" ]; then echo "refusing: a key file is a symlink" >&2; exit 3; fi
SRCENV="$L/.env.live"; [ -e "$SRCENV" ] || SRCENV="$B/.env.demo"
if [ -f "$SRCENV" ]; then
    umask 077; grep -E "$KEYS" "$SRCENV" > "$T/env.live" || true          # values are never printed
    install -o raqmlive -g raqmlive -m 600 "$T/env.live" "$L/.env.live"
    if [ "$SRCENV" = "$B/.env.demo" ]; then rm -f "$B/.env.demo"; fi
fi
# Telegram alerts: only the two TELEGRAM_ lines of the paper bots' .env
if [ -f "$B/.env" ]; then
    umask 077; grep -E '^TELEGRAM_(BOT_TOKEN|CHAT_ID)=' "$B/.env" > "$L/.env.telegram" || true
    chown raqmlive:raqmlive "$L/.env.telegram"; chmod 600 "$L/.env.telegram"
fi
# Folders shared with the API (raqmapi can write in them): root only creates what is missing — mkdir fails on
# anything already there, link or not — and changes ownership with chown -h. It never chmods, chowns or writes
# through a path inside them, so a link planted there can't send root's write elsewhere.
shared_dir() {   # $1 = path; its parent must be root's (/opt) or created by this function
    if [ -L "$1" ]; then echo "refusing: $1 is a symlink" >&2; exit 3; fi
    if [ ! -d "$1" ]; then mkdir -m 2770 "$1"; fi
    chown -h raqmlive:raqmapi "$1"
}
# manual close requests and the live status (the live bot writes the status and removes the requests)
shared_dir /opt/raqm-ipc; shared_dir /opt/raqm-ipc/commands; shared_dir /opt/raqm-ipc/results
# risk ledger + live activation record shared with the API (RAQM_RISK_DIR in both units): the dashboard's kill switch,
# limits and revoke must reach the bot. The bot and the API create the files themselves (mode 660).
shared_dir /opt/raqm-risk
echo "raqm-live ready: $(ls "$L" | tr '\n' ' ')"
