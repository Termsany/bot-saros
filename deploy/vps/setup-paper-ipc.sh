#!/bin/sh
# Admin close requests from the site to the 7 paper bots: /opt/raqm-ipc-paper/<bot>/{commands,results}.
# Shared through group raqmpaper (the paper user raqm and the API user raqmapi only). Not raqmapi's group: that one
# owns the API's code and venv, so membership let the paper user rewrite the API.
# Root owns the tree down to <bot>/, so the paper user can't swap commands/ for a link into the real-money bot's
# /opt/raqm-ipc (an admin's paper close would then land there as a real close). commands/ belongs to the API,
# which writes the requests; results/ to the bot, which answers them. Idempotent.
set -eu
getent group raqmpaper >/dev/null || groupadd --system raqmpaper
usermod -aG raqmpaper raqm; usermod -aG raqmpaper raqmapi
gpasswd -d raqm raqmapi >/dev/null 2>&1 || true
P=/opt/raqm-ipc-paper
own_dir() {   # $1 path, $2 owner:group, $3 mode — refuses links, never follows one
    if [ -L "$1" ]; then echo "refusing: $1 is a symlink" >&2; exit 3; fi
    [ -d "$1" ] || mkdir "$1"
    chown -h "$2" "$1"
    python3 -I -c 'import os,sys; fd=os.open(sys.argv[1], os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW); os.fchmod(fd, int(sys.argv[2], 8)); os.close(fd)' "$1" "$3"
    find "$1" -maxdepth 1 -type f -exec chown -h ":${2#*:}" {} +
}
own_dir $P root:raqmpaper 0750
for b in status momentum listing ratio breakout rsi2 tbreak; do
    own_dir "$P/$b" root:raqmpaper 0750
    own_dir "$P/$b/commands" raqmapi:raqmpaper 02770     # the bot deletes requests it ran (group write)
    own_dir "$P/$b/results" raqm:raqmpaper 02770
done
# new group lists reach a process only when it starts (try-restart: only services already running)
systemctl try-restart raqm-api raqm-bot raqm-listing raqm-momentum raqm-ratio raqm-breakout raqm-rsi2 raqm-tbreak 2>/dev/null || true
