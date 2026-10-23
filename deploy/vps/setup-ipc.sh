#!/bin/sh
# Folder shared by the real-orders bot (user raqm) and the API (user raqmapi): nobody else can enter it.
# setgid keeps every file in group raqmapi; the bot owns the folders, so it can remove the requests it has run.
set -eu
for d in /opt/raqm-ipc /opt/raqm-ipc/commands /opt/raqm-ipc/results; do
    install -d -o raqm -g raqmapi -m 2770 "$d"
done
