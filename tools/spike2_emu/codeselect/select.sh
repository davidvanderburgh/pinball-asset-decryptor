#!/bin/sh
# select.sh - the codeselect hook for /etc/init.d/game on a multi-image card.
#
# Called right after the script's own 'pkill boot_display ' line and before
# 'if [ -f $GAMES_PATH/game ]; then'. Runs the selector, reads the index it
# wrote, looks the device up in images.conf and, unless it is image 0 (the
# primary, which fstab already mounted at /games), swaps the mount. Stern's
# own launch lines follow untouched.
#
# Device forms in images.conf:
#   <dev>         a whole games partition: umount /games; mount -o ro,relatime,exec <dev> /games
#   <dev>:<sub>   a partition holding several games trees (img1/, img2/ ...):
#                 umount /games; mount -o ro <dev> /mnt/multi; mount --bind /mnt/multi/<sub> /games
#                 (/mnt/multi is created when the rootfs allows it; on the
#                 stock read-only rootfs /var/volatile/multi (tmpfs) is used)
#
# Every failure boots the primary (/dev/mmcblk0p3 is mounted back on /games):
# the card degrades to a stock card, never to a brick. This script never
# touches /mnt/boot. Writing the last-choice file is the selector's job.
#
#   select.sh                     the hook (what /etc/init.d/game calls)
#   select.sh --lookup N [conf]   print image N's device (without :<sub>)
#   select.sh --lookup-sub N [conf]   print image N's subdirectory ("" when none)
#
# POSIX sh; needs only busybox sed/awk/grep/head/tr/mkdir/mount/umount + pidof.
# The CODESELECT_* variables exist for the tests (a fake selector, fake
# mount/umount, no block-device check); the hook runs with the defaults.

DIR=${CODESELECT_DIR:-/usr/local/codeselect}
CONF=${CODESELECT_CONF:-$DIR/images.conf}
BIN=${CODESELECT_BIN:-$DIR/codeselect}
OUT=${CODESELECT_OUT:-/var/volatile/codeselect.choice}
LOGDIR=${CODESELECT_LOGDIR:-/dump/log}
LOG="$LOGDIR/codeselect.log"
PRIMARY=/dev/mmcblk0p3
GAMES=${CODESELECT_GAMES:-/games}
MULTI=${CODESELECT_MULTI:-/mnt/multi}
MULTI_FALLBACK=${CODESELECT_MULTI_FALLBACK:-/var/volatile/multi}
MOUNT=${CODESELECT_MOUNT:-mount}
UMOUNT=${CODESELECT_UMOUNT:-umount}

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null) select.sh: $*" >> "$LOG" 2>/dev/null
    echo "select.sh: $*"
}

# AWK may name another awk (the tests run the card's busybox awk under qemu)
AWK=${AWK:-awk}

# image N's device field split at ':' - prints "<dev>" or "<dev> <sub>":
# the N-th (0-based) 'image=<device>|...' line of the conf
lookup() {
    $AWK -F'|' -v want="$1" '
        /^[ \t]*image[ \t]*=/ {
            if (i == want) {
                sub(/^[ \t]*image[ \t]*=[ \t]*/, "", $1)
                gsub(/[ \t]+$/, "", $1)
                n = split($1, a, ":")
                if (n > 1) print a[1] " " a[2]
                else print a[1]
                exit
            }
            i++
        }' "$2"
}

is_blockdev() {
    [ -n "${CODESELECT_NO_BLKCHECK:-}" ] || [ -b "$1" ]
}

has_game() {
    [ -e "$1/game" ] || [ -L "$1/game" ]
}

case "$1" in
    --lookup)
        [ -n "$2" ] || { echo "usage: select.sh --lookup N [conf]" >&2; exit 1; }
        set -- $(lookup "$2" "${3:-$CONF}")
        echo "$1"
        exit 0
        ;;
    --lookup-sub)
        [ -n "$2" ] || { echo "usage: select.sh --lookup-sub N [conf]" >&2; exit 1; }
        set -- $(lookup "$2" "${3:-$CONF}")
        echo "$2"
        exit 0
        ;;
esac

mkdir -p "$LOGDIR" 2>/dev/null

[ -x "$BIN" ] || { log "no $BIN: booting primary"; exit 0; }
[ -r "$CONF" ] || { log "no $CONF: booting primary"; exit 0; }

# boot_display was just pkill'ed; give it a moment to release the display
i=0
while [ "$i" -lt 30 ] && pidof boot_display >/dev/null 2>&1; do
    usleep 100000
    i=$((i + 1))
done

rm -f "$OUT"
"$BIN" --conf "$CONF" --out "$OUT" --log "$LOG"
rc=$?
[ "$rc" -eq 0 ] || { log "selector exit $rc: booting primary"; exit 0; }

idx=$(head -n 1 "$OUT" 2>/dev/null | tr -cd '0-9')
[ -n "$idx" ] || { log "no choice in $OUT: booting primary"; exit 0; }

if [ "$idx" -eq 0 ]; then
    log "image 0 is the primary, already mounted at $GAMES"
    exit 0
fi

set -- $(lookup "$idx" "$CONF")
dev=$1
sub=$2
[ -n "$dev" ] || { log "image $idx has no device in $CONF: booting primary"; exit 0; }
is_blockdev "$dev" || { log "$dev is not a block device: booting primary"; exit 0; }
case "$sub" in
    */*|.*) log "image $idx: bad subdirectory '$sub': booting primary"; exit 0 ;;
esac

if ! $UMOUNT "$GAMES"; then
    log "umount $GAMES failed: booting primary (still mounted)"
    exit 0
fi

if [ -z "$sub" ]; then
    if $MOUNT -t ext4 -o ro,relatime,exec "$dev" "$GAMES" && has_game "$GAMES"; then
        log "image $idx: mounted $dev at $GAMES"
        exit 0
    fi
    log "mount $dev failed or it has no $GAMES/game: remounting the primary $PRIMARY"
    $UMOUNT "$GAMES" 2>/dev/null
else
    mp=$MULTI
    if ! mkdir -p "$mp" 2>/dev/null; then
        mp=$MULTI_FALLBACK
        mkdir -p "$mp" 2>/dev/null
        log "$MULTI is not creatable (read-only rootfs), using $mp"
    fi
    if [ -d "$mp" ] && $MOUNT -t ext4 -o ro,relatime,exec "$dev" "$mp"; then
        if [ -d "$mp/$sub" ] && $MOUNT --bind "$mp/$sub" "$GAMES" && has_game "$GAMES"; then
            log "image $idx: mounted $dev at $mp, $sub bound over $GAMES"
            exit 0
        fi
        log "no $mp/$sub/game or the bind failed: remounting the primary $PRIMARY"
        $UMOUNT "$GAMES" 2>/dev/null
        $UMOUNT "$mp" 2>/dev/null
    else
        log "mount $dev at $mp failed: remounting the primary $PRIMARY"
    fi
fi

if $MOUNT -t ext4 -o ro,relatime,exec "$PRIMARY" "$GAMES"; then
    log "primary remounted"
else
    log "PRIMARY REMOUNT FAILED: $GAMES is empty"
fi
exit 0
