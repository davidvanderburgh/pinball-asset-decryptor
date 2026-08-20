#!/bin/bash
# Bring up the fake playfield boards as REAL character devices via CUSE.
#
# Why CUSE and not the LD_PRELOAD shim: the game's Sentinel envelope resolves
# libc for itself (it imports dl_iterate_phdr / dladdr / dlsym / dlvsym) instead
# of going through the PLT, so an LD_PRELOAD interposer is never called - proven
# by a control run where the shim was mapped into the game with LD_PRELOAD set
# and still logged zero open() and zero fopen() calls.  A CUSE device is served
# by the kernel, so it does not matter how the game calls open().
#
# One CUSE session = one device, so this starts one daemon per board.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/padpath.sh"
[ "$(id -u)" = "0" ] || { echo "jjpcuse.sh: must run as root" >&2; exit 2; }

BIN=${JJP_CUSE_BIN:-/var/tmp/jjpcuse}
[ -x "$BIN" ] || { echo "jjpcuse.sh: $BIN missing; run build.sh" >&2; exit 3; }
[ -e /dev/cuse ] || { echo "jjpcuse.sh: no /dev/cuse (modprobe cuse)" >&2; exit 4; }

# name:board, matching the enum in jjpshm.h
BOARDS="jjpio100:0 jjpled100:1 jjpacc100:2 jjpcab100:3 jjptop100:4"

case "${1:-start}" in
stop)
    pkill -f "$BIN" 2>/dev/null
    sleep 1
    echo "cuse daemons left: $(pgrep -fc "$BIN" 2>/dev/null || true)"
    exit 0 ;;
esac

modprobe cuse 2>/dev/null
for spec in $BOARDS; do
    name=${spec%%:*}; board=${spec##*:}
    if [ -e "/dev/$name" ]; then
        echo "/dev/$name already present - skipping"
        continue
    fi
    setsid "$BIN" --name="$name" --board="$board" -f \
        >>/var/tmp/jjpcuse_$name.log 2>&1 &
done

for i in $(seq 1 15); do
    sleep 1
    missing=0
    for spec in $BOARDS; do
        [ -e "/dev/${spec%%:*}" ] || missing=1
    done
    [ "$missing" = "0" ] && break
done

echo "--- devices ---"
for spec in $BOARDS; do
    name=${spec%%:*}
    if [ -e "/dev/$name" ]; then
        # The game runs as root here, but keep it permissive so a non-root
        # run works too.
        chmod 666 "/dev/$name" 2>/dev/null
        ls -l "/dev/$name"
    else
        echo "MISSING /dev/$name  (see /var/tmp/jjpcuse_$name.log)"
    fi
done
