#!/bin/sh
# The real-orders bot (raqm-trend-demo.service) runs apart from the 7 paper bots: its own user, its own copy of the
# code that only root can change, its keys readable by that user alone. A compromised paper bot (user raqm, which
# can write /opt/raqm-bot) can then neither read the exchange keys nor change the code that trades.
# Run as root after each deploy of bot.py (it refreshes the code copy). Idempotent.
set -eu
L=/opt/raqm-live; B=/opt/raqm-bot
id raqmlive >/dev/null 2>&1 || useradd --system --home-dir "$L" --no-create-home --shell /usr/sbin/nologin raqmlive
install -d -o root -g raqmlive -m 750 "$L"
install -d -o raqmlive -g raqmlive -m 700 "$L/state"
for f in bot.py strategies_trend.py strategies_advanced.py strategies_wave.py; do install -m 644 -o root -g root "$B/$f" "$L/$f"; done
install -d -o root -g root -m 755 "$L/backend" "$L/backend/app"
# every backend module bot.py imports (stdlib only): order placement, multi-leg engine, execution checks, risk ledger, activation
for m in __init__ oco multi_leg_execution execution_safety risk_manager live_activation; do
    install -m 644 -o root -g root "$B/backend/app/$m.py" "$L/backend/app/$m.py"
done
# Phase 1 harness (scripts/demo_e2e.py): runs as raqmlive from this root-owned copy, refuses anything but Demo
install -d -o root -g root -m 755 "$L/scripts"
install -m 644 -o root -g root /opt/raqm-api/app/scripts/demo_e2e.py "$L/scripts/demo_e2e.py"
if [ ! -x "$L/venv/bin/python" ]; then                  # same packages as the paper bots, owned by root
    python3 -m venv "$L/venv"
    "$B/venv/bin/pip" freeze > /tmp/raqm-live-req.txt
    "$L/venv/bin/pip" install -q -r /tmp/raqm-live-req.txt && rm -f /tmp/raqm-live-req.txt
fi
# keys: moved out of the shared bot folder (never copied, never printed)
if [ -f "$B/.env.demo" ] && [ ! -f "$L/.env.live" ]; then mv "$B/.env.demo" "$L/.env.live"; fi
if [ -f "$L/.env.live" ]; then chown raqmlive:raqmlive "$L/.env.live"; chmod 600 "$L/.env.live"; fi
# Telegram alerts: only the two TELEGRAM_ lines of the paper bots' .env
if [ -f "$B/.env" ]; then
    umask 077; grep -E '^TELEGRAM_(BOT_TOKEN|CHAT_ID)=' "$B/.env" > "$L/.env.telegram" || true
    chown raqmlive:raqmlive "$L/.env.telegram"; chmod 600 "$L/.env.telegram"
fi
# the folder shared with the API now belongs to the live bot (it writes the status and removes the requests)
for d in /opt/raqm-ipc /opt/raqm-ipc/commands /opt/raqm-ipc/results; do install -d -o raqmlive -g raqmapi -m 2770 "$d"; done
# risk ledger + live activation record shared with the API (RAQM_RISK_DIR in both units): the dashboard's kill switch,
# limits and revoke must reach the bot. The API's existing copies move here once (sqlite backup, safe while it runs).
install -d -o raqmlive -g raqmapi -m 2770 /opt/raqm-risk
for db in risk_state.sqlite3 live_activation.sqlite3; do
    if [ ! -f "/opt/raqm-risk/$db" ] && [ -f "/opt/raqm-api/app/$db" ]; then
        /opt/raqm-api/venv/bin/python -I -c 'import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close()'             "/opt/raqm-api/app/$db" "/opt/raqm-risk/$db"
    fi
    if [ -f "/opt/raqm-risk/$db" ]; then chown -h raqmlive:raqmapi "/opt/raqm-risk/$db"; chmod 660 "/opt/raqm-risk/$db"; fi
done
echo "raqm-live ready: $(ls "$L" | tr '\n' ' ')"
