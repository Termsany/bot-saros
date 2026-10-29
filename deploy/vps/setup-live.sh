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
# keys: moved out of the shared bot folder (never copied, never printed). Symlinks are refused: user raqm can
# write /opt/raqm-bot, and a planted link would make root move, chown or chmod a file of its choosing.
if [ -L "$B/.env.demo" ] || [ -L "$L/.env.live" ]; then echo "refusing: a key file is a symlink" >&2; exit 3; fi
if [ -f "$B/.env.demo" ] && [ ! -e "$L/.env.live" ]; then
    install -o raqmlive -g raqmlive -m 600 "$B/.env.demo" "$L/.env.live" && rm -f "$B/.env.demo"
fi
if [ -f "$L/.env.live" ]; then chown -h raqmlive:raqmlive "$L/.env.live"; chmod 600 "$L/.env.live"; fi
# Telegram alerts: only the two TELEGRAM_ lines of the paper bots' .env
if [ -f "$B/.env" ]; then
    umask 077; grep -E '^TELEGRAM_(BOT_TOKEN|CHAT_ID)=' "$B/.env" > "$L/.env.telegram" || true
    chown raqmlive:raqmlive "$L/.env.telegram"; chmod 600 "$L/.env.telegram"
fi
# the folder shared with the API now belongs to the live bot (it writes the status and removes the requests)
for d in /opt/raqm-ipc /opt/raqm-ipc/commands /opt/raqm-ipc/results; do
    [ -L "$d" ] && { echo "refusing: $d is a symlink" >&2; exit 3; }
    install -d -o raqmlive -g raqmapi -m 2770 "$d"
done
# risk ledger + live activation record shared with the API (RAQM_RISK_DIR in both units): the dashboard's kill switch,
# limits and revoke must reach the bot. The API's existing copies move here once (sqlite backup, safe while it runs).
install -d -o raqmlive -g raqmapi -m 2770 /opt/raqm-risk
for db in risk_state.sqlite3 live_activation.sqlite3; do
    SRCDB="/opt/raqm-api/app/$db"
    if [ ! -e "/opt/raqm-risk/$db" ] && [ -f "$SRCDB" ] && [ ! -L "$SRCDB" ]; then
        # the system python, not the API venv: that venv is writable by raqmapi and this runs as root
        python3 -I -c 'import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close()' "$SRCDB" "/opt/raqm-risk/$db"
    fi
    [ -L "/opt/raqm-risk/$db" ] && { echo "refusing: /opt/raqm-risk/$db is a symlink" >&2; exit 3; }
    if [ -f "/opt/raqm-risk/$db" ]; then chown raqmlive:raqmapi "/opt/raqm-risk/$db"; chmod 660 "/opt/raqm-risk/$db"; fi
done
echo "raqm-live ready: $(ls "$L" | tr '\n' ' ')"
