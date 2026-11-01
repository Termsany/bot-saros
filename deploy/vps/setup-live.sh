#!/bin/sh
# The real-orders bots (raqm-demo@<strategy> / raqm-live@<strategy>) run apart from the 7 paper bots: its own user, its own copy of the
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
# The live bot and the API share the risk ledger and the IPC folder through their own group, raqmrisk, which holds
# those two users only. Not raqmapi's group: that one owns the API's code and venv (group-writable), so membership
# let the real-money user — and the paper user — rewrite the API. Leave it if an earlier run added us to it.
getent group raqmrisk >/dev/null || groupadd --system raqmrisk
usermod -aG raqmrisk raqmlive; usermod -aG raqmrisk raqmapi
gpasswd -d raqmlive raqmapi >/dev/null 2>&1 || true
install -d -o root -g raqmlive -m 750 "$L"
install -d -o raqmlive -g raqmlive -m 700 "$L/state"
for f in bot.py strategies_trend.py strategies_advanced.py strategies_wave.py trade_card.py; do install -m 644 -o root -g root "$T/$f" "$L/$f"; done
# the Telegram trade card's fonts (trade_card.py)
install -d -o root -g root -m 755 "$L/assets" "$L/assets/fonts"
for f in "$T"/assets/fonts/*; do install -m 644 -o root -g root "$f" "$L/assets/fonts/"; done
install -d -o root -g root -m 755 "$L/backend" "$L/backend/app"
# every backend module bot.py imports (stdlib only): order placement, multi-leg engine, execution checks, risk ledger, activation
# (+ user_bots: the users' rules the provisioner shares with the API)
for m in __init__ oco multi_leg_execution execution_safety risk_manager live_activation user_bots; do
    install -m 644 -o root -g root "$T/backend/app/$m.py" "$L/backend/app/$m.py"
done
# Phase 1 harness (scripts/demo_e2e.py): runs as raqmlive from this root-owned copy, refuses anything but Demo
install -d -o root -g root -m 755 "$L/scripts"
install -m 644 -o root -g root "$T/scripts/demo_e2e.py" "$L/scripts/demo_e2e.py"
install -m 644 -o root -g root "$T/scripts/live_report.py" "$L/scripts/live_report.py"   # the daily report (read only)
install -m 644 -o root -g root "$T/scripts/watchdog.py" "$L/scripts/watchdog.py"         # problem alerts (read only)
install -m 644 -o root -g root "$T/scripts/backup.py" "$L/scripts/backup.py"             # daily backup to Telegram (read only)
install -m 644 -o root -g root "$T/scripts/provision_users.py" "$L/scripts/provision_users.py"   # Phase 2 users' bots (root)
echo "$SHA" > "$L/DEPLOYED_COMMIT"
# packages: only what the bot imports, pinned, from wheels (deploy/vps/live-requirements.txt)
[ -x "$L/venv/bin/python" ] || python3 -m venv "$L/venv"
"$L/venv/bin/pip" install -q --only-binary=:all: -r "$T/deploy/vps/live-requirements.txt"
# Phase 2 (docs/phase2-design.md): the same code for users' bots, readable by every user's OS account — the owner's
# copy above is the owner's group only, and its state folder sits inside it. Root's, copied from the copy just made.
U=/opt/raqm-users/code
install -d -o root -g root -m 755 /opt/raqm-users "$U" "$U/backend" "$U/backend/app" "$U/assets" "$U/assets/fonts"
for f in bot.py strategies_trend.py strategies_advanced.py strategies_wave.py trade_card.py DEPLOYED_COMMIT; do install -m 644 -o root -g root "$L/$f" "$U/$f"; done
for f in "$L"/backend/app/*.py; do install -m 644 -o root -g root "$f" "$U/backend/app/"; done
for f in "$L"/assets/fonts/*; do install -m 644 -o root -g root "$f" "$U/assets/fonts/"; done
install -d -o root -g root -m 755 "$U/scripts"
install -m 644 -o root -g root "$L/scripts/backup.py" "$U/scripts/backup.py"   # each user's part of the users' backup, run as them
[ -x "$U/venv/bin/python" ] || python3 -m venv "$U/venv"
"$U/venv/bin/pip" install -q --only-binary=:all: -r "$T/deploy/vps/live-requirements.txt"
# keys: only the key lines, never the whole file. /opt/raqm-bot is writable by the paper user: a whole-file copy
# carried any line it planted (PYTHONPATH=/opt/raqm-bot -> its ccxt.py runs with the keys). Symlinks are refused.
KEYS='^(BINANCE_API_KEY|BINANCE_SECRET|BINANCE_LIVE_ACCOUNT)='
if [ -L "$B/.env.demo" ] || [ -L "$L/.env.live" ]; then echo "refusing: a key file is a symlink" >&2; exit 3; fi
SRCENV="$L/.env.live"; [ -e "$SRCENV" ] || SRCENV="$B/.env.demo"
if [ -f "$SRCENV" ]; then
    umask 077; grep -E "$KEYS" "$SRCENV" > "$T/env.live" || true          # values are never printed
    # A re-run whose source lines don't match $KEYS exactly (different quoting, leading whitespace, a
    # renamed variable, CRLF...) extracts nothing — "|| true" above swallows that. Installing an empty
    # extraction would silently destroy the existing, presumably-correct key file. First-time setup
    # ($L/.env.live not created yet) has nothing to destroy, so it's fine to proceed with an empty one.
    if [ -s "$L/.env.live" ]; then
        if ! grep -q '^BINANCE_API_KEY=' "$T/env.live" 2>/dev/null || ! grep -q '^BINANCE_SECRET=' "$T/env.live" 2>/dev/null; then
            echo "refusing: extracted key file from $SRCENV is empty or missing required keys — not overwriting the existing $L/.env.live" >&2
            exit 4
        fi
    fi
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
    chown -h raqmlive:raqmrisk "$1"
    # mode and the group of what is already inside, without following a link: fchmod on an O_NOFOLLOW handle,
    # chown -h on regular files only
    python3 -I -c 'import os,sys; fd=os.open(sys.argv[1], os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW); os.fchmod(fd, 0o2770); os.close(fd)' "$1"
    find "$1" -maxdepth 1 -type f -exec chown -h :raqmrisk {} +
}
# manual close requests and the live status (the live bot writes the status and removes the requests)
shared_dir /opt/raqm-ipc
for s in trend_daily vol_breakout rsi2_pullback trend_breakout listing_short momentum_ls ratio_trend; do   # one folder per live bot
    shared_dir "/opt/raqm-ipc/$s"; shared_dir "/opt/raqm-ipc/$s/commands"; shared_dir "/opt/raqm-ipc/$s/results"
done
# risk ledger + live activation record shared with the API (RAQM_RISK_DIR in both units): the dashboard's kill switch,
# limits and revoke must reach the bot. The bot and the API create the files themselves (mode 660).
shared_dir /opt/raqm-risk
# Demo has its own risk ledger, the bots' alone: play money never touches the real account's limits and kill switch
# shared with the API like /opt/raqm-risk: the dashboard's Demo yes/no is written there
shared_dir /opt/raqm-risk-demo
# per-strategy options (RAQM_ARGS), root's: the daily trend trades the top 10 by volume
install -d -o root -g root -m 755 "$L/strategies"
[ -e "$L/strategies/trend_daily.env" ] || echo 'RAQM_ARGS=--leverage 2 --amount 100 --universe 10 --poll 60' > "$L/strategies/trend_daily.env"
# the Demo unit template (raqm-demo@<strategy>); the real-money one (raqm-live@) is installed by hand when going live —
# installing it also freezes the API's automatic updates (api/update.sh)
install -m 644 -o root -g root "$T/deploy/vps/raqm-demo@.service" /etc/systemd/system/raqm-demo@.service
# problem alerts on Telegram every 5 minutes (raqmlive, read only)
install -m 644 -o root -g root "$T/deploy/vps/raqm-watchdog.service" /etc/systemd/system/raqm-watchdog.service
install -m 644 -o root -g root "$T/deploy/vps/raqm-watchdog.timer" /etc/systemd/system/raqm-watchdog.timer
# the daily backup of the bots' records to Telegram (raqmlive, read only)
install -m 644 -o root -g root "$T/deploy/vps/raqm-backup.service" /etc/systemd/system/raqm-backup.service
install -m 644 -o root -g root "$T/deploy/vps/raqm-backup.timer" /etc/systemd/system/raqm-backup.timer
# Phase 2 (docs/phase2-design.md): the users' bot template and the provisioner. The timer is NOT enabled here —
# switching users' bots on is a deliberate step: systemctl enable --now raqm-users-provision.timer
install -m 644 -o root -g root "$T/deploy/vps/raqm-user@.service" /etc/systemd/system/raqm-user@.service
install -m 644 -o root -g root "$T/deploy/vps/raqm-users-provision.service" /etc/systemd/system/raqm-users-provision.service
install -m 644 -o root -g root "$T/deploy/vps/raqm-users-provision.timer" /etc/systemd/system/raqm-users-provision.timer
install -d -o root -g root -m 755 /opt/raqm-users /opt/raqm-users/ipc /var/lib/raqm-users
install -d -o root -g root -m 700 /var/lib/raqm-users-applied
install -d -o root -g raqmapi -m 2770 /opt/raqm-users/desired      # the API writes users' desired state here
install -d -o root -g root -m 700 /etc/raqm-users                   # allow.list (the owner) and users' key credentials
# the users' bots' alerts and daily backup (P2.5): on from the start, they do nothing while there is no user
for u in raqm-watchdog-users.service raqm-watchdog-users.timer raqm-backup-users.service raqm-backup-users.timer; do
    install -m 644 -o root -g root "$T/deploy/vps/$u" "/etc/systemd/system/$u"
done
systemctl daemon-reload
systemctl enable --now raqm-watchdog.timer >/dev/null 2>&1 || echo "warning: raqm-watchdog.timer not enabled" >&2
systemctl enable --now raqm-backup.timer >/dev/null 2>&1 || echo "warning: raqm-backup.timer not enabled" >&2
systemctl enable --now raqm-watchdog-users.timer >/dev/null 2>&1 || echo "warning: raqm-watchdog-users.timer not enabled" >&2
systemctl enable --now raqm-backup-users.timer >/dev/null 2>&1 || echo "warning: raqm-backup-users.timer not enabled" >&2
# new group lists reach a process only when it starts: the API (try-restart: only if running). The live bots are not
# restarted here — one stopped in the middle of an order goes to review; restart them as a deliberate step:
#   systemctl restart 'raqm-demo@*' / 'raqm-live@*'
systemctl try-restart raqm-api 2>/dev/null || echo "warning: raqm-api restart failed" >&2
echo "raqm-live ready: $(ls "$L" | tr '\n' ' ')"
