#!/bin/sh
# Folder shared by the real-orders bot (user raqmlive, setup-live.sh) and the API (user raqmapi): nobody else can enter it.
# setgid keeps every file in group raqmrisk (the bot and the API only; setup-live.sh creates it); the bot owns the folders, so it can remove the requests it has run.
set -eu
for d in /opt/raqm-ipc /opt/raqm-ipc/commands /opt/raqm-ipc/results; do
    install -d -o raqmlive -g raqmrisk -m 2770 "$d"
done
