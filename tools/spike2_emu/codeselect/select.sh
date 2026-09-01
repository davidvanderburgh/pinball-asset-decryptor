#!/bin/sh
# select.sh - the codeselect hook for /etc/init.d/game on a multi-image card.
#
# Called right after the script's own 'pkill boot_display ' line and before
# 'if [ -f $GAMES_PATH/game ]; then'. Runs the selector, reads the index it
# wrote, looks the device up in images.conf and, if it is not what fstab
# already mounted at /games (p3, the primary), swaps the mount. Stern's own
# launch lines follow untouched.
#
# Every failure boots the primary: the card degrades to a stock card, never
# to a brick. This script never touches /mnt/boot. Writing the last-choice
# file is the selector's job, not this script's.
#
#   select.sh                 the hook (what /etc/init.d/game calls)
#   select.sh --lookup N [conf]   print image N's device and exit (for tests)
#
# POSIX sh; needs only busybox sed/awk/grep/head/tr/mount/umount + pidof.

DIR=/usr/local/codeselect
CONF="$DIR/images.conf"
BIN="$DIR/codeselect"
OUT=/var/volatile/codeselect.choice
LOGDIR=/dump/log
LOG="$LOGDIR/codeselect.log"
PRIMARY=/dev/mmcblk0p3
GAMES=/games

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null) select.sh: $*" >> "$LOG" 2>/dev/null
    echo "select.sh: $*"
}

# AWK may name another awk (the tests run the card's busybox awk under qemu)
AWK=${AWK:-awk}

# image N's device: the N-th (0-based) 'image=<device>|...' line of the conf
lookup() {
    $AWK -F'|' -v want="$1" '
        /^[ \t]*image[ \t]*=/ {
            if (i == want) {
                sub(/^[ \t]*image[ \t]*=[ \t]*/, "", $1)
                gsub(/[ \t]+$/, "", $1)
                print $1
                exit
            }
            i++
        }' "$2"
}

if [ "$1" = "--lookup" ]; then
    [ -n "$2" ] || { echo "usage: select.sh --lookup N [conf]" >&2; exit 1; }
    lookup "$2" "${3:-$CONF}"
    exit 0
fi

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

dev=$(lookup "$idx" "$CONF")
[ -n "$dev" ] || { log "image $idx has no device in $CONF: booting primary"; exit 0; }

cur=$($AWK -v m="$GAMES" '$2 == m { d = $1 } END { print d }' /proc/mounts)
if [ "$dev" = "$cur" ]; then
    log "image $idx ($dev) is already mounted at $GAMES"
    exit 0
fi
[ -b "$dev" ] || { log "$dev is not a block device: booting primary"; exit 0; }

if ! umount "$GAMES"; then
    log "umount $GAMES failed: booting primary (still mounted)"
    exit 0
fi
if mount -t ext4 -o ro,relatime,exec "$dev" "$GAMES" && { [ -e "$GAMES/game" ] || [ -L "$GAMES/game" ]; }; then
    log "image $idx: mounted $dev at $GAMES"
    exit 0
fi

log "mount $dev failed or it has no $GAMES/game: remounting the primary $PRIMARY"
umount "$GAMES" 2>/dev/null
if mount -t ext4 -o ro,relatime,exec "$PRIMARY" "$GAMES"; then
    log "primary remounted"
else
    log "PRIMARY REMOUNT FAILED: $GAMES is empty"
fi
exit 0
