#!/bin/sh
# Admin close requests from the site to the 7 paper bots: /opt/raqm-ipc-paper/<bot>/{commands,results}.
# The bots (user raqm) own the folders and remove the requests they ran; the API (group raqmapi) drops them.
# Nobody else can enter. Idempotent.
set -eu
# raqm (the 7 paper bots) must also be in raqmapi's group: the setgid dirs below are useless without it.
usermod -aG raqmapi raqm
install -d -o raqm -g raqmapi -m 2770 /opt/raqm-ipc-paper
for b in status momentum listing ratio breakout rsi2 tbreak; do
    for d in "/opt/raqm-ipc-paper/$b" "/opt/raqm-ipc-paper/$b/commands" "/opt/raqm-ipc-paper/$b/results"; do
        install -d -o raqm -g raqmapi -m 2770 "$d"
    done
done
