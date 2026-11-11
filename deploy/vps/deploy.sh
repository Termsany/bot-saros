#!/bin/sh
# The one way code reaches the VPS. As root, on the server, from the root-owned clone at that exact commit:
#
#   git -C /root/raqm-src fetch -q origin && git -C /root/raqm-src checkout -q --detach <sha>
#   sh /root/raqm-src/deploy/vps/deploy.sh <full sha> [--dry-run] [--restart] [--restart-demo s1,s2] <target>...
#
# targets
#   live          setup-live.sh of that commit: /opt/raqm-live (real + Demo bots), /opt/raqm-users/code (users' bots),
#                 the tools, the units, realbot.da3m.io's page. Restarts nothing that trades real money, ever.
#   paper         every paper bot: each own-folder one (/opt/raqm-<bot>, raqm-<bot>.service) and /opt/raqm-bot
#   paper:<bot>   one of them: paper:ratio-nobtc, paper:momentum, ... or paper:shared (/opt/raqm-bot)
#   page          the paper page, deploy/vps/page/index.html -> /var/www/bot.da3m.io/index.html (raqm:www-data 644)
#   api           the API unit (backed up first when it changes) and raqm-api-update --manual <sha>
#   all           live paper page api
# options
#   --dry-run       the checks and each target's previous commit, then stop: nothing is written
#   --restart       enable + restart the deployed own-folder paper bots, try-restart /opt/raqm-bot's running ones
#   --restart-demo  with live: restart these Demo bots, by name (raqm-demo@<s>), never a pattern, never momentum_ls
#
# What it guarantees (backend/tests/test_deploy_safety.py pins each):
#   - the commit is a full sha on origin/main;
#   - every file comes from `git archive` of that commit in the root-owned clone — never from a working tree, so
#     never a Windows checkout's CRLF, never a file a bot or the API user could have changed;
#   - each target's previous commit is printed first (the rollback: deploy.sh <previous> <target>);
#   - every installed file is checked against git (blob sha) afterwards; any mismatch fails the run (exit 5);
#   - raqm-live@* and raqm-user@* are never started, stopped or restarted: the command is printed for the owner.
#     Demo bots restart only by name and only when asked; raqm-demo@momentum_ls stays masked (its unit Conflicts=
#     the real raqm-live@momentum_ls, so starting it would stop the real bot).
set -eu

SRC=${RAQM_SRC:-/root/raqm-src}
STATE=${RAQM_DEPLOY_STATE:-/var/lib/raqm-deploy}      # root's: each target's deployed commit + a history line
UNITS=/etc/systemd/system
L=/opt/raqm-live; U=/opt/raqm-users/code; B=/opt/raqm-bot
PAGE=/var/www/bot.da3m.io/index.html
PAGE_ASSETS=/var/www/bot.da3m.io/assets     # its stylesheet and scripts (deploy/vps/page/assets/, since 2026-11-11)
API=/opt/raqm-api/app
SELF=$SRC/deploy/vps/deploy.sh
# what every paper bot runs (the own-folder ones and /opt/raqm-bot): bot.py imports bots/, engine/ and backend/app
PAPER_FILES="bot.py bots engine strategies_advanced.py strategies_trend.py strategies_wave.py trade_card.py assets/fonts backend/app"
# the units setup-live.sh installs (raqm-live@.service is the owner's, by hand; the test keeps this list in step)
LIVE_UNITS="raqm-demo@.service raqm-demo-momwed.service raqm-watchdog.service raqm-watchdog.timer raqm-backup.service
 raqm-backup.timer raqm-realbot-export.service raqm-realbot-export.timer raqm-rebalance-check.service
 raqm-rebalance-check.timer raqm-demo-weekly.service raqm-demo-weekly.timer raqm-user@.service
 raqm-users-provision.service raqm-users-provision.timer raqm-watchdog-users.service raqm-watchdog-users.timer
 raqm-backup-users.service raqm-backup-users.timer"
FAILS=0; CHECKED=0

say() { printf '%s\n' "$*"; }
err() { printf '%s\n' "$*" >&2; }
usage() { sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }

# ---- the commit and the clone ------------------------------------------------------------------------------------
check_clone() {   # the clone root runs from: root's, nobody else can write it (or its git config and hooks)
    [ -d "$SRC/.git" ] || { err "no clone at $SRC: git clone https://github.com/Termsany/bot-saros.git $SRC"; return 2; }
    for p in "$SRC" "$SRC/.git" "$SRC/.git/config" "$SRC/.git/hooks"; do
        [ -e "$p" ] || continue
        if [ -L "$p" ]; then err "refusing: $p is a symlink"; return 2; fi
        [ "$(stat -c %u "$p")" = 0 ] || { err "refusing: $p is not root's"; return 2; }
        [ -z "$(find "$p" -maxdepth 0 -perm /022)" ] || { err "refusing: $p is writable by group or others"; return 2; }
    done
}

check_sha() {   # $1: a full 40-character sha of a commit on origin/main (reviewed means merged)
    echo "$1" | grep -qE '^[0-9a-f]{40}$' || { err "usage: deploy.sh <full 40-character commit sha> <target>..."; return 2; }
    git -C "$SRC" fetch -q origin || { err "git fetch failed in $SRC"; return 2; }
    git -C "$SRC" cat-file -e "$1^{commit}" 2>/dev/null || { err "commit $1 not found on GitHub"; return 2; }
    git -C "$SRC" merge-base --is-ancestor "$1" origin/main || { err "refusing: commit $1 is not on origin/main"; return 2; }
}

# ---- checking installed files against git ------------------------------------------------------------------------
check_file() {   # $1 path in git at $SHA, $2 the installed file: same blob, or a failure
    want=$(git -C "$SRC" rev-parse -q --verify "$SHA:$1" 2>/dev/null) || { err "  FAIL $1 is not in git at $SHA"; FAILS=$((FAILS+1)); return 0; }
    if [ -L "$2" ] || [ ! -f "$2" ]; then err "  FAIL $2: missing or a symlink"; FAILS=$((FAILS+1)); return 0; fi
    have=$(git -C "$SRC" hash-object --no-filters -- "$2")
    if [ "$have" = "$want" ]; then CHECKED=$((CHECKED+1)); else err "  FAIL $2 differs from $1 at $SHA"; FAILS=$((FAILS+1)); fi
}

check_git_files() {   # $1 installed root, $2 regex on the git path ('' = all), then git paths: each file of git there
    root=$1; re=${2:-.}; shift 2
    for p in $(git -C "$SRC" ls-tree -r --name-only "$SHA" -- "$@" | grep -E "$re"); do check_file "$p" "$root/$p"; done
}

check_present() {   # $1 installed root, $2 a folder in it: each file there that git has must match (others: warned)
    for f in "$1/$2"/*; do
        [ -f "$f" ] && [ ! -L "$f" ] || continue
        p=$2/${f##*/}
        if git -C "$SRC" cat-file -e "$SHA:$p" 2>/dev/null; then check_file "$p" "$f"; else err "  note: $f is not in git at $SHA (left from an older commit)"; fi
    done
}

# ---- services: one door, which real money never passes -----------------------------------------------------------
real_money_unit() {   # 0 when $1 trades real money: raqm-live@ / raqm-user@, or a unit run with --live and not pinned to Demo
    case "$1" in raqm-live@*|raqm-user@*) return 0;; esac
    line=$(systemctl cat "$1" 2>/dev/null | tr -d '\r' | grep -E '^ExecStart=.' | tail -1) || true
    if echo "$line" | grep -q -- '--live' && ! echo "$line" | grep -q -- '--expect-env demo'; then return 0; fi
    return 1
}

guarded() {   # $1 restart|try-restart|start|stop|enable, $2 one unit by its full name. Every service action goes here.
    case "$1" in restart|try-restart|start|stop|enable) ;; *) err "refusing: systemctl $1"; return 1;; esac
    case "$2" in ''|*'*'*|*'?'*|*'['*|*' '*) err "refusing: '$2': units by their full name only, never a pattern"; return 1;; esac
    case "${2%.service}" in raqm-demo@momentum_ls)
        err "refusing: raqm-demo@momentum_ls stays masked (it Conflicts= the real raqm-live@momentum_ls)"; return 1;; esac
    if real_money_unit "$2"; then
        err "not touching $2: real money. The owner's step, by hand:  systemctl $1 '$2'"; return 1
    fi
    systemctl "$1" "$2"
}

demo_ok() {   # $1 a strategy whose Demo bot may restart: by name, not masked, its real twin neither running nor enabled
    case "$1" in ''|*[!a-z0-9_]*) err "refusing Demo '$1': a strategy name only (raqm-demo@<name>)"; return 1;; esac
    [ "$1" != momentum_ls ] || { err "refusing: raqm-demo@momentum_ls stays masked"; return 1; }
    [ "$(systemctl is-enabled "raqm-demo@$1" 2>/dev/null || true)" != masked ] || { err "refusing: raqm-demo@$1 is masked"; return 1; }
    a=$(systemctl is-active "raqm-live@$1" 2>/dev/null || true)
    e=$(systemctl is-enabled "raqm-live@$1" 2>/dev/null || true)
    for s in "$a" "$e"; do
        case "$s" in active|activating|reloading|enabled|enabled-runtime|linked|alias)
            err "refusing: raqm-live@$1 is $s; its Demo twin would stop it (Conflicts=)"; return 1;; esac
    done
}

# ---- the paper bots, found from their units at that commit -------------------------------------------------------
paper_bots() {   # $1 a folder of unit files: "<unit> <working dir>" per paper bot (User=raqm, run with --paper)
    for f in "$1"/raqm-*.service; do
        [ -f "$f" ] || continue
        c=$(tr -d '\r' < "$f")
        printf '%s\n' "$c" | grep -qx 'User=raqm' || continue
        printf '%s\n' "$c" | grep -E '^ExecStart=' | grep -q -- ' --paper ' || continue
        d=$(printf '%s\n' "$c" | sed -n 's/^WorkingDirectory=//p' | tail -1)
        case "$d" in /opt/raqm-*) ;; *) continue;; esac
        n=${f##*/}; echo "${n%.service} $d"
    done
}

as_raqm() { runuser -u raqm -- "$@"; }   # copies into the bots' folders as their user: root never writes through them

file_commit() {   # a DEPLOYED_COMMIT-style file's sha, or nothing
    if [ -f "$1" ] && [ ! -L "$1" ]; then head -c 40 "$1" | grep -E '^[0-9a-f]{40}$' || true; fi
}
recorded() { file_commit "$STATE/$1.commit"; }
record() { echo "$SHA" > "$STATE/$1.commit"; echo "$(date -u +%FT%TZ) $SHA $1" >> "$STATE/history"; }

api_head() { (cd "$API" 2>/dev/null && sudo -u raqmapi git rev-parse HEAD 2>/dev/null) || true; }

previous() {   # $1 key, $2 what the server itself says: printed with the rollback command
    p=$(recorded "$1"); from="recorded by deploy.sh"
    [ -n "$p" ] || { p=$2; from=${3:-}; }
    if [ -n "$p" ]; then say "  $1: $p ${from:+($from)}"; say "      rollback: sh $SELF $p ${4:-$1}   (clone left at this commit)"
    else say "  $1: unknown${3:+ ($3)}"; fi
}

# ---- targets -------------------------------------------------------------------------------------------------------
deploy_live() {
    sh "$T/deploy/vps/setup-live.sh" "$SHA"    # that commit's own setup; it never restarts a real-money bot
    say "checking /opt/raqm-live and /opt/raqm-users/code against git"
    for R in "$L" "$U"; do
        check_git_files "$R" '^[a-z_]+\.py$|^bots/[^/]+\.py$|^engine/[^/]+\.py$|^assets/fonts/' \
            bot.py strategies_trend.py strategies_advanced.py strategies_wave.py trade_card.py bots engine assets/fonts
        check_present "$R" backend/app; check_present "$R" scripts
        [ "$(file_commit "$R/DEPLOYED_COMMIT")" = "$SHA" ] || { err "  FAIL $R/DEPLOYED_COMMIT is not $SHA"; FAILS=$((FAILS+1)); }
    done
    for t in set_demo_keys.sh set_reviewers.py live_account.py; do check_file "deploy/vps/tools/$t" "/usr/local/lib/raqm/$t"; done
    check_file scripts/rebalance_costs.py /usr/local/lib/raqm/rebalance_costs.py
    check_file deploy/vps/realbot/index.html /var/www/realbot.da3m.io/index.html
    for u in $LIVE_UNITS; do check_file "deploy/vps/$u" "$UNITS/$u"; done
}

restart_demo() {
    for s in $DEMO; do guarded restart "raqm-demo@$s" && say "  raqm-demo@$s: $(systemctl is-active "raqm-demo@$s" || true)"; done
}

real_money_note() {
    say "Not restarted — real money is the owner's step: one bot at a time, by its full name, between cycles, away"
    say "from 00:00 UTC and never on its rebalance day (docs/after-rebalance-1.md, steps 7 and 7b):"
    running=$(systemctl list-units --type=service --state=running --no-legend --plain 'raqm-live@*' 'raqm-user@*' 2>/dev/null | awk '{print $1}') || true
    for u in $running; do say "  systemctl restart '$u'"; done
    [ -n "$running" ] || say "  (no raqm-live@ or raqm-user@ unit is running)"
    say "  The users' bots have Restart=always: any restart of theirs loads the code just installed."
    [ -n "$DEMO" ] || say "  Demo bots, by name:  sh $SELF $SHA live --restart-demo trend_daily,ratio_trend,..."
}

deploy_paper_bot() {   # $1 unit, $2 its own folder
    u=$1; D=$2
    if [ -L "$D" ]; then err "refusing: $D is a symlink"; exit 3; fi
    install -d -o raqm -g raqm -m 750 "$D"
    if [ "$u" = raqm-momentum ]; then   # its first install moves its state over from /opt/raqm-bot, with the bot stopped
        move=0
        for f in state_momentum.json state_momentum.log; do [ -e "$D/$f" ] || [ ! -e "$B/$f" ] || move=1; done
        if [ $move = 1 ]; then
            [ "$RESTART" = 1 ] || { err "refusing: raqm-momentum's first install moves its state: run it with --restart"; exit 2; }
            guarded stop raqm-momentum
            for f in state_momentum.json state_momentum.log; do [ -e "$D/$f" ] || [ ! -e "$B/$f" ] || as_raqm cp -p "$B/$f" "$D/$f"; done
        fi
    fi
    as_raqm cp -R "$S/." "$D/"                 # the code only: state_*.json / .log are never in the archive
    echo "$SHA" | as_raqm tee "$D/DEPLOYED_COMMIT" >/dev/null
    install -m 644 -o root -g root "$T/deploy/vps/$u.service" "$UNITS/$u.service"
}

verify_paper_bot() {   # $1 unit, $2 folder
    check_git_files "$2" '' $PAPER_FILES
    [ "$2" = "$B" ] || check_file "deploy/vps/$1.service" "$UNITS/$1.service"
}

deploy_page() {
    if [ -L "${PAGE%/*}" ] || [ -L "$PAGE" ] || [ -L "$PAGE_ASSETS" ]; then err "refusing: ${PAGE%/*}, its index.html or assets/ is a symlink"; exit 3; fi
    # the assets first: index.html names them by content hash (deploy/vps/page/stamp.py), so the new page never goes
    # live before its files; the old ones stay until a later deploy (the old page may still be open in a browser)
    install -d -o raqm -g www-data -m 755 "$PAGE_ASSETS"
    for f in "$T"/deploy/vps/page/assets/*; do
        [ -L "$PAGE_ASSETS/${f##*/}" ] && { err "refusing: $PAGE_ASSETS/${f##*/} is a symlink"; exit 3; }
        install -o raqm -g www-data -m 644 "$f" "$PAGE_ASSETS/"
    done
    install -o raqm -g www-data -m 644 "$T/deploy/vps/page/index.html" "$PAGE"
}

verify_page() {
    check_file deploy/vps/page/index.html "$PAGE"
    m=$(stat -c '%U:%G %a' "$PAGE")
    [ "$m" = "raqm:www-data 644" ] || { err "  FAIL $PAGE is $m, not raqm:www-data 644"; FAILS=$((FAILS+1)); }
    for f in "$T"/deploy/vps/page/assets/*; do
        check_file "deploy/vps/page/assets/${f##*/}" "$PAGE_ASSETS/${f##*/}"
        m=$(stat -c '%U:%G %a' "$PAGE_ASSETS/${f##*/}" 2>/dev/null)
        [ "$m" = "raqm:www-data 644" ] || { err "  FAIL $PAGE_ASSETS/${f##*/} is $m, not raqm:www-data 644"; FAILS=$((FAILS+1)); }
    done
}

deploy_api() {
    [ -x /usr/local/sbin/raqm-api-update ] || { err "no updater: sh $SRC/deploy/vps/api/install-updater.sh first"; exit 2; }
    cmp -s "$T/deploy/vps/api/update.sh" /usr/local/sbin/raqm-api-update ||
        err "note: the installed raqm-api-update is not $SHA's; to update it: sh $SRC/deploy/vps/api/install-updater.sh"
    API_UNIT=0
    if ! cmp -s "$T/deploy/vps/api/raqm-api.service" "$UNITS/raqm-api.service"; then
        cp -p "$UNITS/raqm-api.service" "$STATE/raqm-api.service.$(date -u +%Y%m%d%H%M%S)"   # its rollback
        install -m 644 -o root -g root "$T/deploy/vps/api/raqm-api.service" "$UNITS/raqm-api.service"
        systemctl daemon-reload; API_UNIT=1
    fi
    /usr/local/sbin/raqm-api-update --manual "$SHA"   # moves the API's checkout to $SHA, restarts it when backend/ changed
    [ $API_UNIT = 0 ] || guarded try-restart raqm-api  # a new unit takes effect only at a restart
}

verify_api() {
    [ "$(api_head)" = "$SHA" ] || { err "  FAIL the API's checkout is not at $SHA"; FAILS=$((FAILS+1)); }
    check_git_files "$API" '' backend/app backend/requirements.txt
    check_file deploy/vps/api/raqm-api.service "$UNITS/raqm-api.service"
}

has() { case " $TARGETS " in *" $1 "*) return 0;; esac; return 1; }

main() {
    SHA=${1:-}
    [ "$(id -u)" = 0 ] || { err "run it as root, on the server"; exit 2; }
    check_clone || exit 2
    check_sha "$SHA" || exit 2
    # run that commit's own deploy.sh: the clone's working tree may be at another commit than $SHA
    # (a commit from before deploy.sh existed — a rollback — is deployed by this version, with that commit's files)
    want=$(git -C "$SRC" rev-parse -q --verify "$SHA:deploy/vps/deploy.sh") ||
        { want=""; err "note: $SHA predates deploy.sh; this version deploys that commit's files (its setup-live.sh for live)"; }
    if [ -n "$want" ] && [ "$(git -C "$SRC" hash-object --no-filters -- "$0")" != "$want" ]; then
        [ "${RAQM_DEPLOY_OF:-}" != "$SHA" ] || { err "refusing: the deploy.sh of $SHA is not itself"; exit 2; }
        X=$(mktemp); git -C "$SRC" cat-file blob "$want" > "$X"
        err "running deploy.sh of $SHA (this one is another version)"
        RAQM_DEPLOY_OF=$SHA RAQM_DEPLOY_SELF=$X exec sh "$X" "$@"
    fi
    [ -z "${RAQM_DEPLOY_SELF:-}" ] || rm -f "$RAQM_DEPLOY_SELF"
    shift
    DRY=0; RESTART=0; DEMO=""; TARGETS=""; ASKED=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --dry-run) DRY=1;;
            --restart) RESTART=1;;
            --restart-demo) [ $# -ge 2 ] || usage; DEMO=$(echo "$2" | tr ',' ' '); shift;;
            --restart-demo=*) DEMO=$(echo "${1#*=}" | tr ',' ' ');;
            live|paper|page|api) TARGETS="$TARGETS $1";;
            paper:*) ASKED="$ASKED ${1#paper:}"; TARGETS="$TARGETS paper:";;
            all) TARGETS="$TARGETS live paper page api";;
            *) usage;;
        esac
        shift
    done
    [ -n "$TARGETS" ] || usage
    if [ -n "$DEMO" ]; then
        has live || { err "refusing: --restart-demo goes with the live target (the Demo bots run /opt/raqm-live)"; exit 2; }
        for s in $DEMO; do demo_ok "$s" || exit 2; done
    fi

    T=$(mktemp -d); S=$(mktemp -d); trap 'rm -rf "$T" "$S"' EXIT
    git -C "$SRC" -c core.autocrlf=false -c tar.umask=022 archive "$SHA" | tar -x -C "$T"
    chmod 755 "$S"   # the paper code, read by the bots' user while it copies
    git -C "$SRC" -c core.autocrlf=false -c tar.umask=022 archive "$SHA" $PAPER_FILES | tar -x -C "$S"

    BOTS=""   # "<unit>=<folder>" for each paper bot this run deploys
    if has paper || has paper:; then
        all=$(paper_bots "$T/deploy/vps")
        for n in $ASKED; do
            [ "$n" = shared ] || echo "$all" | grep -q "^raqm-$n " ||
                { err "no paper bot '$n' at $SHA; there are: shared $(echo "$all" | grep -v " $B\$" | sed 's/^raqm-//; s/ .*//' | tr '\n' ' ')"; exit 2; }
        done
        BOTS=$(echo "$all" | while read -r u d; do
            [ -n "$u" ] || continue
            n=${u#raqm-}; [ "$d" = "$B" ] && n=shared
            if has paper || echo " $ASKED " | grep -q " $n "; then echo "$u=$d"; fi
        done)
    fi

    OPTS=""; [ $RESTART = 0 ] || OPTS=" --restart"; [ -z "$DEMO" ] || OPTS="$OPTS --restart-demo $DEMO"
    say "deploy.sh $SHA:$TARGETS$OPTS"
    say "previous commits:"
    if has live; then
        previous live "$(file_commit "$L/DEPLOYED_COMMIT")" "$L/DEPLOYED_COMMIT"
        say "  users' code: $(file_commit "$U/DEPLOYED_COMMIT") ($U/DEPLOYED_COMMIT; live's rollback restores it too)"
    fi
    shared_done=0
    for e in $BOTS; do
        u=${e%%=*}; d=${e#*=}
        if [ "$d" = "$B" ]; then [ $shared_done = 1 ] && continue; shared_done=1
            previous paper-shared "" "$B has no record" paper:shared
        else previous "paper-${u#raqm-}" "$(file_commit "$d/DEPLOYED_COMMIT")" "$d/DEPLOYED_COMMIT, written by the bot's user" "paper:${u#raqm-}"; fi
    done
    if has page; then
        blob=$( [ -f "$PAGE" ] && git -C "$SRC" hash-object --no-filters -- "$PAGE" || echo none)
        previous page "" "the page now is blob $blob: git -C $SRC log --format=%H --find-object=$blob origin/main"
    fi
    has api && previous api "$(api_head)" "the API's checkout"
    if [ $DRY = 1 ]; then say "dry run: nothing written"; exit 0; fi

    install -d -o root -g root -m 700 "$STATE"
    if has live; then
        say "== live"; f0=$FAILS; deploy_live
        if [ $FAILS = $f0 ]; then record live; restart_demo; else err "  live's files differ from git: no Demo bot restarted"; fi
        real_money_note
    fi
    if [ -n "$BOTS" ]; then
        say "== paper"
        for e in $BOTS; do
            u=${e%%=*}; d=${e#*=}
            if [ "$d" = "$B" ]; then
                [ "${shared_copied:-0}" = 1 ] || { as_raqm cp -R "$S/." "$B/"; shared_copied=1; }
            else deploy_paper_bot "$u" "$d"; fi
        done
        systemctl daemon-reload
        shared_checked=0
        for e in $BOTS; do
            u=${e%%=*}; d=${e#*=}; f0=$FAILS
            if [ "$d" = "$B" ]; then
                if [ $shared_checked = 0 ]; then verify_paper_bot "$u" "$d"; shared_checked=1; [ $FAILS = $f0 ] && record paper-shared; fi
                [ $FAILS = $f0 ] && [ $RESTART = 1 ] && guarded try-restart "$u"
            else
                verify_paper_bot "$u" "$d"
                if [ $FAILS = $f0 ]; then
                    record "paper-${u#raqm-}"
                    if [ $RESTART = 1 ]; then guarded enable "$u"; guarded restart "$u"; fi
                fi
            fi
            [ $RESTART = 1 ] && say "  $u: $(systemctl is-active "$u" || true)"
        done
        [ $RESTART = 1 ] || say "  paper bots not restarted (--restart restarts them); they run the new code from their next start"
    fi
    if has page; then say "== page"; f0=$FAILS; deploy_page; verify_page; [ $FAILS = $f0 ] && record page; fi
    if has api; then say "== api"; f0=$FAILS; deploy_api; verify_api; [ $FAILS = $f0 ] && record api; fi

    if [ $FAILS -gt 0 ]; then err "FAILED: $FAILS installed file(s) differ from git at $SHA ($CHECKED match); a target with a difference was neither recorded nor restarted."; exit 5; fi
    say "done: $SHA, $CHECKED installed files match git"
}

# tests source this file with RAQM_DEPLOY_LIB=1 to call its functions; on the server it runs main
[ "${RAQM_DEPLOY_LIB:-}" = 1 ] || main "$@"
