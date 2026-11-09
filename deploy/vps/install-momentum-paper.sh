#!/bin/sh
# Install or update the paper momentum bot (deploy/vps/raqm-momentum.service) from a commit, in its own folder
# /opt/raqm-momentum-paper. The first run moves its state (state_momentum.json / .log) over from /opt/raqm-bot, with
# the bot stopped, and keeps a copy in /opt/raqm-bot. Only this bot's folder and unit change: the other paper bots
# (/opt/raqm-bot) and every real-money or Demo bot are left alone.
# Run from a checkout of this repository (git archive with core.autocrlf off keeps LF line endings, even on Windows).
#   sh deploy/vps/install-momentum-paper.sh <commit> [ssh target, default root@148.230.113.18]
set -eu
COMMIT=$(git rev-parse --verify "${1:?commit}^{commit}")
HOST=${2:-root@148.230.113.18}
SSH="ssh -i $HOME/.ssh/claude_vps -o BatchMode=yes $HOST"
git -c core.autocrlf=false archive "$COMMIT" bot.py strategies_advanced.py strategies_trend.py strategies_wave.py trade_card.py \
    assets/fonts backend/app deploy/vps/raqm-momentum.service | $SSH "set -eu
  T=\$(mktemp -d); trap 'rm -rf \"\$T\"' EXIT
  tar -x -C \"\$T\"
  D=/opt/raqm-momentum-paper
  install -d -o raqm -g raqm -m 750 \$D
  systemctl stop raqm-momentum
  for f in state_momentum.json state_momentum.log; do
    [ -e \$D/\$f ] || [ ! -e /opt/raqm-bot/\$f ] || cp -a /opt/raqm-bot/\$f \$D/\$f
  done
  install -m 644 \"\$T/deploy/vps/raqm-momentum.service\" /etc/systemd/system/raqm-momentum.service
  rm -rf \"\$T/deploy\"
  cp -a \"\$T\"/. \$D/
  echo $COMMIT > \$D/DEPLOYED_COMMIT
  chown -R raqm:raqm \$D
  systemctl daemon-reload
  systemctl start raqm-momentum
  systemctl is-active raqm-momentum"
