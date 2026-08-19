#!/bin/bash
# Open the switch/LED matrix beside a running game.
#
# Runs as the DESKTOP USER, not root, even though the rest of the rig is root:
# the UI is a Tk window and needs that user's WSLg session.  The shared block
# is created by root (the CUSE daemons), so it is chmod'd 0666 for exactly this
# hand-off.
#
# Also refreshes the device dump first.  Every device object is zeroed in the
# ELF and filled by constructors, so names, positions and frame addressing only
# exist while a game is running - a stale dump from a previous title would
# draw the wrong playfield.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/padpath.sh"

DUMP=${JJP_DEVICES_JSON:-/var/tmp/jjp_devices.json}
PF=${JJP_PF_PNG:-$HERE/wonka_pf_image.png}
USER_NAME=${JJP_DESKTOP_USER:-$(getent passwd 1000 | cut -d: -f1)}

N=$(pgrep -c -x game 2>/dev/null); N=${N:-0}
if [ "$N" = "0" ]; then
    echo "jjpsw_launch.sh: no game running - start one first" >&2
    exit 3
fi

if [ "$(id -u)" = "0" ]; then
    python3 "$HERE/swdump.py" --out "$DUMP" --quiet || {
        echo "jjpsw_launch.sh: could not read the device tables" >&2; exit 4; }
    chmod 666 "$DUMP" 2>/dev/null
    chmod 666 /dev/shm${JJP_SHM_NAME:-/jjp_switches} 2>/dev/null
    exec setsid sudo -u "$USER_NAME" env DISPLAY="${JJP_UI_DISPLAY:-:0}" \
        python3 "$HERE/jjpsw.py" --devices "$DUMP" --pf "$PF"
fi

# Already the desktop user (a Linux desktop, or someone ran it by hand).
python3 "$HERE/swdump.py" --out "$DUMP" --quiet || exit 4
exec python3 "$HERE/jjpsw.py" --devices "$DUMP" --pf "$PF"
