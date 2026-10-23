#!/bin/sh
# Pull main from GitHub; when the backend (or the root .py files it imports) changed, reinstall deps if needed
# and restart the API. Run by raqm-api-update.timer every 5 minutes — replaces Render's deploy hook.
set -eu
APP=/opt/raqm-api/app
cd "$APP"
# With real money (ALLOW_LIVE_TRADING=true) nothing from GitHub reaches the server on its own: a push to main —
# or a stolen GitHub token — would otherwise run next to the exchange keys within 5 minutes.
# Deploy by hand after reviewing:  sudo sh /opt/raqm-api/update.sh --manual
if [ "${1:-}" != "--manual" ] && grep -qiE '^ALLOW_LIVE_TRADING=["'"'"']?true' /opt/raqm-api/.env 2>/dev/null; then
    sudo -u raqmapi git fetch -q origin main
    [ "$(sudo -u raqmapi git rev-parse HEAD)" = "$(sudo -u raqmapi git rev-parse origin/main)" ] ||         echo "live trading on: update available on main, not deployed automatically (run update.sh --manual after review)"
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
