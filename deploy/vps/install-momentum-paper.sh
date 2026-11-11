#!/bin/sh
# Install or update the paper momentum bot (deploy/vps/raqm-momentum.service): a thin wrapper of deploy.sh, kept so the old command still works.
# It runs on the server, as root, from root's clone at that commit:  deploy.sh <sha> paper:momentum --restart
# (refuses a commit that is not on origin/main, installs from git on the server, checks every file against git).
# Only this bot's own folder and its unit change: the other paper bots and every real-money or Demo bot are left alone.
#   sh deploy/vps/install-momentum-paper.sh <commit> [ssh target, default root@148.230.113.18]
set -eu
exec sh "$(dirname "$0")/remote-deploy.sh" "${1:?commit}" ${2:+"$2"} -- paper:momentum --restart
