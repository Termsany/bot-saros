#!/bin/sh
# Run deploy/vps/deploy.sh on the VPS from a laptop: moves root's clone /root/raqm-src to the commit and runs that
# commit's deploy.sh there, as root. Nothing is copied from this checkout (a Windows one writes CRLF): every file the
# server installs comes from git on the server. The install-*.sh scripts are this with their own target.
#   sh deploy/vps/remote-deploy.sh <commit> [ssh target, default root@148.230.113.18] -- <deploy.sh options and targets>
#   sh deploy/vps/remote-deploy.sh HEAD -- --dry-run all
set -eu
COMMIT=$(git rev-parse --verify "${1:?commit}^{commit}")
shift
HOST=root@148.230.113.18
if [ $# -gt 0 ] && [ "$1" != -- ]; then HOST=$1; shift; fi
[ "${1:-}" = -- ] && shift
[ $# -gt 0 ] || { echo "usage: $0 <commit> [ssh target] -- <targets>" >&2; exit 2; }
for a in "$@"; do
    case "$a" in *[!A-Za-z0-9_:,=-]*) echo "refusing argument '$a'" >&2; exit 2;; esac   # nothing for the remote shell to read
done
ssh -i "$HOME/.ssh/claude_vps" -o BatchMode=yes "$HOST" "set -eu
  SRC=/root/raqm-src
  [ -d \$SRC/.git ] || git clone -q https://github.com/Termsany/bot-saros.git \$SRC
  git -C \$SRC fetch -q origin
  git -C \$SRC checkout -q --detach $COMMIT
  sh \$SRC/deploy/vps/deploy.sh $COMMIT $*"
