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
STEP=${2:-1}
DPY=${JJP_DISPLAY}

# On a NESTED server (display.sh's Xephyr) the root really IS the game's screen,
# so grabbing the root is both correct and simpler.  On WSLg's :0 it is not -
# RAIL never composites the X root, see shot.py - so there we must hunt down the
# game's own window id, and via -tree, because the window is a grandchild.
if [ "$DPY" != ":0" ]; then
    WID=root
else
    WID=$(chroot "$JJP_JAIL" /bin/bash -c "export DISPLAY=$DPY; xwininfo -root -tree" 2>/dev/null \
          | grep -o '0x[0-9a-f]* "MAIN[^"]*"' | head -1 | cut -d' ' -f1)
fi
if [ -z "$WID" ]; then
    echo "grab.sh: no game window found (is the game running? try alive.sh)" >&2
    exit 3
fi
echo "display=$DPY window=$WID"
# Always use the IMAGE's xwd, never the host's: the host may not have x11-apps
# installed, and the image ships xwd already.  The jail has /tmp/.X11-unix
# bind-mounted, so it can reach both :0 and a nested Xephyr.
if [ "$WID" = "root" ]; then
    chroot "$JJP_JAIL" /bin/bash -c "export DISPLAY=$DPY; xwd -root -out /tmp/shot.xwd" || exit 4
else
    chroot "$JJP_JAIL" /bin/bash -c "export DISPLAY=$DPY; xwd -id $WID -out /tmp/shot.xwd" || exit 4
fi
python3 "$HERE/shot.py" "$JJP_JAIL/tmp/shot.xwd" "$OUT" "$STEP"
