#!/bin/sh
# Install or update the "ratio trend without BTC/ETH" paper bot (deploy/vps/raqm-ratio-nobtc.service) from a commit.
# Run from a checkout of this repository (git archive keeps LF line endings); it ssh-es to the VPS as root. Only this
# bot's own folder and its unit change: the other paper bots (/opt/raqm-bot) and every real-money or Demo bot are
# left alone.
#   sh deploy/vps/install-ratio-nobtc.sh <commit> [ssh target, default root@148.230.113.18]
set -eu
COMMIT=$(git rev-parse --verify "${1:?commit}^{commit}")
HOST=${2:-root@148.230.113.18}
SSH="ssh -i $HOME/.ssh/claude_vps -o BatchMode=yes $HOST"
git archive "$COMMIT" bot.py strategies_advanced.py strategies_trend.py strategies_wave.py trade_card.py \
    assets/fonts backend/app deploy/vps/raqm-ratio-nobtc.service | $SSH "set -eu
  T=\$(mktemp -d); trap 'rm -rf \"\$T\"' EXIT
  tar -x -C \"\$T\"
  install -m 644 \"\$T/deploy/vps/raqm-ratio-nobtc.service\" /etc/systemd/system/raqm-ratio-nobtc.service
  rm -rf \"\$T/deploy\"
  install -d -o raqm -g raqm -m 750 /opt/raqm-ratio-nobtc
  cp -a \"\$T\"/. /opt/raqm-ratio-nobtc/
  echo $COMMIT > /opt/raqm-ratio-nobtc/DEPLOYED_COMMIT
  chown -R raqm:raqm /opt/raqm-ratio-nobtc
  systemctl daemon-reload
  systemctl enable raqm-ratio-nobtc
  systemctl restart raqm-ratio-nobtc
  systemctl is-active raqm-ratio-nobtc"
