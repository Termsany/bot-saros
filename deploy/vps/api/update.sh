#!/bin/sh
# Pull main from GitHub; when the backend (or the root .py files it imports) changed, reinstall deps if needed
# and restart the API. Run by raqm-api-update.timer every 5 minutes — replaces Render's deploy hook.
# Runs as root, so it lives where only root can change it: /usr/local/sbin/raqm-api-update (api/install-updater.sh).
# From /opt/raqm-api — a folder the API user owns — that user could swap the file and be root within 5 minutes.
set -eu
APP=/opt/raqm-api/app
cd "$APP"
# With real money (ALLOW_LIVE_TRADING=true) nothing from GitHub reaches the server on its own: a push to main —
# or a stolen GitHub token — would otherwise run next to the exchange keys within 5 minutes.
# Same once a real-money bot is installed (a raqm unit started with --live and not pinned to Demo): the API's own
# flag can be switched back off while that bot keeps trading on its activation record.
# Deploy by hand after reviewing:  sudo raqm-api-update --manual
real_money_bot() {
    for f in /etc/systemd/system/raqm-*.service; do
        [ -f "$f" ] || continue
        # Scope BOTH checks to the ExecStart= line only: a whole-file grep for '--expect-env demo' also
        # matches the string anywhere else (e.g. a comment left over from copying raqm-trend-demo.service
        # to make a new real-money unit), wrongly treating a genuine real-money bot as not one.
        line=$(grep -E '^ExecStart=' "$f" | head -1)
        echo "$line" | grep -qE -- '--live' && ! echo "$line" | grep -qE -- '--expect-env demo' && return 0
    done
    return 1
}
if [ "${1:-}" != "--manual" ] && { grep -qiE '^ALLOW_LIVE_TRADING=["'"'"']?true' /opt/raqm-api/.env 2>/dev/null || real_money_bot; }; then
    sudo -u raqmapi git fetch -q origin main
    [ "$(sudo -u raqmapi git rev-parse HEAD)" = "$(sudo -u raqmapi git rev-parse origin/main)" ] ||         echo "live trading on: update available on main, not deployed automatically (run raqm-api-update --manual after review)"
    exit 0
fi
sudo -u raqmapi git fetch -q origin main
OLD=$(sudo -u raqmapi git rev-parse HEAD)
NEW=$(sudo -u raqmapi git rev-parse origin/main)
[ "$OLD" = "$NEW" ] && exit 0
CHANGED=$(sudo -u raqmapi git diff --name-only "$OLD" "$NEW")
sudo -u raqmapi git merge -q --ff-only origin/main
if echo "$CHANGED" | grep -q '^backend/requirements.txt$'; then
    sudo -u raqmapi /opt/raqm-api/venv/bin/pip install -q --only-binary=:all: -r backend/requirements.txt
fi
if echo "$CHANGED" | grep -qE '^backend/|^[^/]+\.py$'; then
    systemctl restart raqm-api
    echo "deployed $NEW (was $OLD)"
else
    echo "updated to $NEW, no backend change"
fi
