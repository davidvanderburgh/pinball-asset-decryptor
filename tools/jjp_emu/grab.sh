#!/bin/bash
# Capture the running game's window to a PNG.
#
# Two things here are non-obvious and both are load-bearing:
#   * the window id must come from `xwininfo -root -tree`, NOT `-children` -
#     the game window is nested one level below the root under Weston;
#   * x11grab on :0 is useless under WSLg (see shot.py's docstring).
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/padpath.sh"
[ "$(id -u)" = "0" ] || { echo "grab.sh: must run as root" >&2; exit 2; }

OUT=${1:-/var/tmp/jjp_shot.png}
STEP=${2:-4}

WID=$(chroot "$JJP_JAIL" /bin/bash -c "export DISPLAY=$JJP_DISPLAY; xwininfo -root -tree" 2>/dev/null \
      | grep -o '0x[0-9a-f]* "MAIN[^"]*"' | head -1 | cut -d' ' -f1)
if [ -z "$WID" ]; then
    echo "grab.sh: no game window found (is the game running? try alive.sh)" >&2
    exit 3
fi
echo "window: $WID"
chroot "$JJP_JAIL" /bin/bash -c "export DISPLAY=$JJP_DISPLAY; xwd -id $WID -out /tmp/shot.xwd" || exit 4
python3 "$HERE/shot.py" "$JJP_JAIL/tmp/shot.xwd" "$OUT" "$STEP"
