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
install -m 644 -o root -g root "$B/backend/app/oco.py" "$B/backend/app/__init__.py" "$L/backend/app/"
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
echo "raqm-live ready: $(ls "$L" | tr '\n' ' ')"
