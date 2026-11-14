#!/bin/sh
# padselect.sh - the boot menu's hook on a Stern Spike 3 multi-boot card
# (PAD-1263). On such a card this file IS the game: /games/game points here.
#
# A Spike 3 machine starts its game from the games partition alone:
# /etc/init.d/S95game starts conagent_monitor (a loop over /games/conagent)
# and game_monitor, which stops the boot splash and runs /games/game in a
# restart loop, reading its exit code. Nothing outside /games is changed by a
# multi-boot card: the signed boot partition and the rootfs stay Stern's.
#
# The card's games partition holds every image's games tree WHOLE, as it was
# on that image's own card, under /games/pad/img0, img1, ... (their own
# `game`, `conagent`, `data`, `spike3` links, their `<title>/` and `spk/`).
# The top level keeps only this hook, the menu and links into img0, so the
# boot splash and conagent find what they look for before the menu runs.
#
#   1. s3select draws the menu on the backbox LCD and reads the coin door's
#      buttons; it writes the chosen index to /tmp/padselect.choice;
#   2. the chosen image's tree is bind-mounted over /games, so the game sees
#      exactly the tree it shipped in, at the path it expects;
#   3. conagent is restarted (its monitor loop runs the chosen tree's own);
#   4. /games/game - now the chosen image's own link - is exec'd: the game
#      process replaces this shell, so game_monitor reads the game's own exit
#      code, and every restart after that runs the game directly.
#
# Any failure (no menu, no choice, no such image, the bind refused) boots
# image 0 the same way, and if even that bind fails, image 0's game straight
# from its directory: the card degrades to a stock card, never to a brick.
#
# PADSELECT_NOEXEC=1 (PAD's emulator only): steps 1-3 and stop - exit 0 once
# the chosen tree is bound, 3 when no bind could be made - and the caller
# starts the game itself. A checkpointable emulator run starts the game under
# an explicit qemu, which runs programs, not this script (s3run.sh).
P=${PADSELECT_DIR:-/games/pad}
GAMES=${PADSELECT_GAMES:-/games}
CONF=${PADSELECT_CONF:-$P/images.conf}
BIN=${PADSELECT_BIN:-$P/s3select}
OUT=${PADSELECT_OUT:-/tmp/padselect.choice}
MOUNT=${PADSELECT_MOUNTCMD:-mount}
PKILL=${PADSELECT_PKILL:-pkill}
LOG=${PADSELECT_LOG-/tmp/padselect.log}

log() {
    [ -n "$LOG" ] && echo "$(date '+%H:%M:%S' 2>/dev/null) padselect: $*" >> "$LOG" 2>/dev/null
    echo "padselect: $*" >&2
}

# image=<dir>|<title>|... -> <dir> of the Nth image line (0-based)
lookup() {
    awk -F'|' -v want="$1" '
        /^[ \t]*image[ \t]*=/ {
            if (i == want) {
                sub(/^[ \t]*image[ \t]*=[ \t]*/, "", $1)
                gsub(/[ \t]+$/, "", $1)
                print $1
                exit
            }
            i++
        }' "$2" 2>/dev/null
}

good_dir() {
    case "$1" in ""|.*|*/*|*[!A-Za-z0-9._-]*) return 1 ;; esac
    [ -e "$P/$1/game" ] || [ -L "$P/$1/game" ]
}

# boot image directory $1 over /games, then become its game
boot() {
    d=$1; shift
    if $MOUNT --bind "$P/$d" "$GAMES" 2>/dev/null || $MOUNT -o bind "$P/$d" "$GAMES" 2>/dev/null; then
        log "$d bound over $GAMES"
        # conagent started from img0's tree before the menu: its monitor
        # restarts it within a second, from the tree the game now sees
        $PKILL -x conagent 2>/dev/null
        cd /
        # PADSELECT_NOEXEC=1 (PAD's emulator, a checkpointable run): the
        # caller starts /games/game itself once the bind is in place
        [ "${PADSELECT_NOEXEC:-0}" = 1 ] && exit 0
        exec "$GAMES/game" "$@"
    fi
    log "binding $P/$d over $GAMES failed"
    return 1
}

cd /
idx=""
if [ ! -f "$CONF" ]; then
    log "no $CONF: booting img0"
elif [ ! -x "$BIN" ]; then
    log "no $BIN: booting img0"
else
    rm -f "$OUT"
    "$BIN" --conf "$CONF" --out "$OUT" --input hw --audio none ${LOG:+--log "$LOG"} </dev/null
    rc=$?
    idx=$(head -n 1 "$OUT" 2>/dev/null | tr -cd '0-9')
    [ -n "$idx" ] || log "the menu left no choice (exit $rc): booting img0"
fi
dir=""
if [ -n "$idx" ]; then
    dir=$(lookup "$idx" "$CONF")
    if good_dir "$dir"; then
        log "image $idx: $dir"
    else
        log "image $idx: '$dir' is not an image directory with a game: booting img0"
        dir=""
    fi
fi
[ -n "$dir" ] && boot "$dir" "$@"
[ "$dir" = img0 ] || boot img0 "$@"
# the last resort: img0's game from its own directory, without the bind
log "starting $P/img0/game without a bind"
[ "${PADSELECT_NOEXEC:-0}" = 1 ] && exit 3       # the caller starts img0's game
exec "$P/img0/game" "$@"
