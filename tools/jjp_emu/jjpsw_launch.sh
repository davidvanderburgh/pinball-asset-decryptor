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
# The playfield photo comes out of whichever game is MOUNTED, not from a
# checked-in file: a hard-coded wonka_pf_image.png drew a Wonka playfield for
# every title.  Cached per image so it is decrypted once.
PF=${JJP_PF_PNG:-$JJP_BASE/pf_image.png}
if [ ! -s "$PF" ]; then
    python3 "$HERE/pfimage.py" --root "$JJP_ROOT" --out "$PF" || {
        echo "jjpsw_launch.sh: no playfield image for this title - the matrix" >&2
        echo "  will still show the grid, just without the photo." >&2
        PF=""
    }
fi
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
    # Backgrounded, not exec'd: this is watch.sh's last step and must RETURN.
    # setsid so the window outlives the WSL session that started it.
    setsid sudo -u "$USER_NAME" env DISPLAY="${JJP_UI_DISPLAY:-:0}" \
        python3 "$HERE/jjpsw.py" --devices "$DUMP" ${PF:+--pf "$PF"} \
        >>/var/tmp/jjp_ui.log 2>&1 &
    sleep 2
    UI=$(pgrep -fc jjpsw.py 2>/dev/null)
    if [ "${UI:-0}" = "0" ]; then
        echo "jjpsw_launch.sh: the matrix exited immediately; see /var/tmp/jjp_ui.log" >&2
        tail -3 /var/tmp/jjp_ui.log >&2 2>/dev/null
        exit 5
    fi
    echo "switch matrix: ${UI} process(es) on ${JJP_UI_DISPLAY:-:0}"
    exit 0
fi

# Already the desktop user (a Linux desktop, or someone ran it by hand).
# NOTE reading the game's memory needs root, so this branch only works when the
# game is running as this same user - which is why the GUI calls the script as
# root and lets the root branch above drop privileges for the UI alone.
python3 "$HERE/swdump.py" --out "$DUMP" --quiet || {
    echo "jjpsw_launch.sh: cannot read the game's tables as $(id -un);" >&2
    echo "  run this as root - it drops to the desktop user for the UI." >&2
    exit 4; }
exec python3 "$HERE/jjpsw.py" --devices "$DUMP" ${PF:+--pf "$PF"}
