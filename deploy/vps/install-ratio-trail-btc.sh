#!/bin/sh
# Install or update the "ratio trend with BTC/ETH, 20% trail" paper bot (deploy/vps/raqm-ratio-trail-btc.service) from a commit.
# Run from a checkout of this repository (git archive with core.autocrlf off keeps LF line endings, even on Windows); it ssh-es to the VPS as root. Only this
# bot's own folder and its unit change: the other paper bots (/opt/raqm-bot) and every real-money or Demo bot are
# left alone.
#   sh deploy/vps/install-ratio-trail-btc.sh <commit> [ssh target, default root@148.230.113.18]
set -eu
COMMIT=$(git rev-parse --verify "${1:?commit}^{commit}")
HOST=${2:-root@148.230.113.18}
SSH="ssh -i $HOME/.ssh/claude_vps -o BatchMode=yes $HOST"
git -c core.autocrlf=false archive "$COMMIT" bot.py bots strategies_advanced.py strategies_trend.py strategies_wave.py trade_card.py \
    assets/fonts backend/app deploy/vps/raqm-ratio-trail-btc.service | $SSH "set -eu
  T=\$(mktemp -d); trap 'rm -rf \"\$T\"' EXIT
  tar -x -C \"\$T\"
  install -m 644 \"\$T/deploy/vps/raqm-ratio-trail-btc.service\" /etc/systemd/system/raqm-ratio-trail-btc.service
  rm -rf \"\$T/deploy\"
  install -d -o raqm -g raqm -m 750 /opt/raqm-ratio-trail-btc
  cp -a \"\$T\"/. /opt/raqm-ratio-trail-btc/
  echo $COMMIT > /opt/raqm-ratio-trail-btc/DEPLOYED_COMMIT
  chown -R raqm:raqm /opt/raqm-ratio-trail-btc
  systemctl daemon-reload
  systemctl enable raqm-ratio-trail-btc
  systemctl restart raqm-ratio-trail-btc
  systemctl is-active raqm-ratio-trail-btc"
