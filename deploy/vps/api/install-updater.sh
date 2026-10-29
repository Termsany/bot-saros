#!/bin/sh
# Install the API updater so the API user can't turn it into root. Run as root from a root-owned checkout:
#   sh /root/raqm-src/deploy/vps/api/install-updater.sh
# The timer runs the updater as root every 5 minutes. It used to be /opt/raqm-api/update.sh, inside a folder owned
# by raqmapi: that user could rename the file and put its own in place. Now the script is root's alone and
# /opt/raqm-api itself belongs to root (raqmapi keeps app/, venv/, .env and its dotfolders). Idempotent.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
case "$HERE" in /opt/raqm-api*|/opt/raqm-bot*) echo "refusing: run it from a root-owned checkout, not $HERE" >&2; exit 2;; esac
install -m 755 -o root -g root "$HERE/update.sh" /usr/local/sbin/raqm-api-update
install -m 644 -o root -g root "$HERE/raqm-api-update.service" /etc/systemd/system/raqm-api-update.service
install -m 644 -o root -g root "$HERE/raqm-api-update.timer" /etc/systemd/system/raqm-api-update.timer
# the folder: root-owned, readable by the API user; what it must write stays its own
[ -L /opt/raqm-api ] && { echo "refusing: /opt/raqm-api is a symlink" >&2; exit 3; }
chown root:raqmapi /opt/raqm-api && chmod 750 /opt/raqm-api
rm -f /opt/raqm-api/update.sh /opt/raqm-api/update.sh.bak       # nothing root runs may live in there
systemctl daemon-reload
systemctl restart raqm-api-update.timer
echo "updater: /usr/local/sbin/raqm-api-update ($(sha256sum /usr/local/sbin/raqm-api-update | cut -c1-12)), /opt/raqm-api $(stat -c '%U:%G %a' /opt/raqm-api)"
