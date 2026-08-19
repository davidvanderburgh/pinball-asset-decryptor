#!/bin/bash
# Put the game in a real, resizable window at its NATIVE resolution.
#
# THE PROBLEM.  Pointed straight at WSLg's :0 the game fullscreens to whatever
# XWAYLAND0 is - here 3840x2160 - instead of Wonka's native 1360x768.  Mesa then
# falls back to llvmpipe and burns ~420% CPU software-rasterising 8.3 Mpixels,
# about 8x more work than the game was ever designed to do.  The window is also
# full-screen-shaped and cannot be resized.
#
# THE FIX is a nested X server.  Xephyr advertises exactly the screen size we
# choose, so the game fullscreens *into that*, and Xephyr's own window is an
# ordinary resizable window on the Windows desktop.  -resizeable lets the X
# screen follow the window as it is dragged.
#
# TWO DISPLAYS.  Wonka is a two-display title: 1360x768 main plus an 800x480
# "Wonkavision" apron (the image's setdisplayconf.sh says `*Wonka*) num_disp=2`).
# --dual gives both as one Xinerama screen pair; the default is main only, which
# is what the game opens first and all that is needed to see attract mode.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/padpath.sh"

: "${JJP_MAIN_MODE:=1360x768}"
: "${JJP_AUX_MODE:=800x480}"
: "${JJP_NESTED:=:1}"

DUAL=0
case "${1:-}" in
    --dual) DUAL=1 ;;
    --stop)
        pkill -f "Xephyr $JJP_NESTED" 2>/dev/null
        sleep 1
        # `pgrep -c` prints 0 AND exits 1, so the obvious `|| echo 0` prints
        # TWO zeros - the same trap status.sh and alive.sh already carry.
        LEFT=$(pgrep -fc "Xephyr $JJP_NESTED" 2>/dev/null)
        echo "Xephyr on $JJP_NESTED stopped (${LEFT:-0} left)"
        exit 0 ;;
esac

command -v Xephyr >/dev/null || {
    echo "display.sh: Xephyr missing.  apt-get install -y xserver-xephyr" >&2; exit 3; }

# One nested server at a time, or the game picks up a stale one.
pkill -f "Xephyr $JJP_NESTED" 2>/dev/null; sleep 1

TITLE="JJP $JJP_GAME - emulated"
if [ "$DUAL" = "1" ]; then
    setsid Xephyr "$JJP_NESTED" -title "$TITLE" -resizeable +xinerama \
        -screen "$JJP_MAIN_MODE" -screen "$JJP_AUX_MODE" \
        -no-host-grab -ac >/var/tmp/jjp_xephyr.log 2>&1 &
else
    setsid Xephyr "$JJP_NESTED" -title "$TITLE" -resizeable \
        -screen "$JJP_MAIN_MODE" \
        -no-host-grab -ac >/var/tmp/jjp_xephyr.log 2>&1 &
fi

for i in $(seq 1 15); do
    sleep 1
    if DISPLAY=$JJP_NESTED xdpyinfo >/dev/null 2>&1; then
        echo "Xephyr up on $JJP_NESTED after ${i}s"
        DISPLAY=$JJP_NESTED xdpyinfo 2>/dev/null | grep -E 'dimensions|number of screens'
        echo
        echo "Now launch the game against it:"
        echo "  JJP_DISPLAY=$JJP_NESTED bash $HERE/run_game.sh --detach"
        exit 0
    fi
done
echo "display.sh: Xephyr never came up; see /var/tmp/jjp_xephyr.log" >&2
tail -10 /var/tmp/jjp_xephyr.log >&2
exit 4
