#!/bin/sh
# Pull main from GitHub; when the backend (or the root .py files it imports) changed, reinstall deps if needed
# and restart the API. Run by raqm-api-update.timer every 5 minutes — replaces Render's deploy hook.
set -eu
APP=/opt/raqm-api/app
cd "$APP"
sudo -u raqmapi git fetch -q origin main
OLD=$(sudo -u raqmapi git rev-parse HEAD)
NEW=$(sudo -u raqmapi git rev-parse origin/main)
[ "$OLD" = "$NEW" ] && exit 0
CHANGED=$(sudo -u raqmapi git diff --name-only "$OLD" "$NEW")
sudo -u raqmapi git merge -q --ff-only origin/main
if echo "$CHANGED" | grep -q '^backend/requirements.txt$'; then
    sudo -u raqmapi /opt/raqm-api/venv/bin/pip install -q -r backend/requirements.txt
fi
if echo "$CHANGED" | grep -qE '^backend/|^[^/]+\.py$'; then
    systemctl restart raqm-api
    echo "deployed $NEW (was $OLD)"
else
    echo "updated to $NEW, no backend change"
fi
