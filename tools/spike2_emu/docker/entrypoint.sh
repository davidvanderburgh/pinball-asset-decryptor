#!/bin/bash
# Bring up the display, then run whatever the caller asked for.
#
#   entrypoint.sh watch.sh 30      # the usual: run the emulator
#   entrypoint.sh alive.sh         # any other rig script, same container
#   entrypoint.sh bash             # a shell, for working out what went wrong
#
# THE DISPLAY IS STARTED HERE AND NOT IN watch.sh, because every rig script that
# needs one needs the same one, and because watch.sh's job is the emulator. It
# already refuses to run with no DISPLAY, which is the check that catches this
# going wrong.
set -u

RIG=${PAD_RIG:-/pad/rig}
XDISPLAY=${DISPLAY:-:99}
# 1920x1080, NOT the game window's 1360x768: the run opens THREE windows (the
# game, the virtual playfield, the Controls list) on this one desktop, and a
# screen the exact size of the first leaves the other two nowhere to be except
# on top of it. Screen Sharing scales the desktop to its own window, so a
# bigger screen costs nothing on the Mac side.
GEOM=${PAD_VNC_GEOMETRY:-1920x1080x24}
PORT=${PAD_VNC_PORT:-5900}

[ -x "$RIG/watch.sh" ] || {
    echo "[box] no rig at $RIG - mount the checkout's tools/spike2_emu there" >&2
    exit 1
}

# Scripts that need no display at all. Starting Xvfb for `alive.sh` would make
# the cheapest, most-run command in the rig pay two seconds and leave an X
# server behind it.
case "${1:-}" in
    alive.sh|killgame.sh|status.sh|gameinfo.py|mktables.py|parts.py)
        exec bash "$RIG/$1" "${@:2}" ;;
esac

echo "[box] starting Xvfb on $XDISPLAY at $GEOM"
Xvfb "$XDISPLAY" -screen 0 "$GEOM" -nolisten tcp >/tmp/xvfb.log 2>&1 &
XVFB_PID=$!
for _ in $(seq 1 40); do
    xdpyinfo -display "$XDISPLAY" >/dev/null 2>&1 && break
    sleep 0.25
done
xdpyinfo -display "$XDISPLAY" >/dev/null 2>&1 || {
    echo "[box] Xvfb did not come up:" >&2; cat /tmp/xvfb.log >&2; exit 1; }

# A WINDOW MANAGER, and it is load-bearing: with none, X focus stays at
# PointerRoot, so the keyboard follows the mouse - hover the playfield and the
# game stops hearing keys, which read as "inputs register inconsistently" on
# the first Mac run. openbox gives click-to-focus (click the game window once,
# keys stay with it) and title bars, so the three windows can be dragged into
# an arrangement instead of landing in a pile.
if command -v openbox >/dev/null 2>&1; then
    openbox >/tmp/openbox.log 2>&1 &
fi

# -forever   the viewer may disconnect and come back without ending the run
# -shared    more than one viewer at a time, which is how you show someone
# -nopw      the port is published to localhost only (see padbox.sh); a
#            password here would be security theatre over a loopback socket,
#            and PAD_VNC_PASSWD is there for anyone who disagrees.
VNC_AUTH=(-nopw)
if [ -n "${PAD_VNC_PASSWD:-}" ]; then
    x11vnc -storepasswd "$PAD_VNC_PASSWD" "$HOME/.vncpw" >/dev/null 2>&1 \
        && VNC_AUTH=(-rfbauth "$HOME/.vncpw")
fi
# -threads   INPUT IS READ ON ITS OWN THREAD, and without it the run is
#            unplayable from a Mac (PAD-805: "I press Start and it takes 2
#            minutes"). Unthreaded, x11vnc reads the viewer's messages in the
#            same loop that encodes and sends the picture, and the picture here
#            is ~1.5 MB a frame (the game and the playfield repaint all the
#            time). A viewer that asks for frames as fast as the mouse moves
#            then piles clicks and keys up behind the frames: measured in this
#            container on one CPU, a pointer move landed 13-16 s late after
#            4 s of moving, and the lag only grows while the mouse keeps
#            moving. The picture never lags, so it looks smooth. Threaded:
#            0.02-0.3 s under the same load, and Start 0.1 s after 60 s of
#            mouse movement (unthreaded: still not there 4 minutes later).
#            x11vnc's own docs warn that -threads can be unstable, hence the loop:
#            a crashed x11vnc comes back in a second, the viewer reconnects,
#            and the run carries on.
echo "[box] VNC on port $PORT - open vnc://localhost:$PORT"
(
    while :; do
        x11vnc -display "$XDISPLAY" -rfbport "$PORT" -forever -shared -quiet \
               -threads "${VNC_AUTH[@]}"
        echo "[box] x11vnc exited ($?); starting it again"
        sleep 1
    done
) >/tmp/x11vnc.log 2>&1 &
VNC_PID=$!

cleanup() {
    # The rig's own teardown first, then ours. killgame.sh is the only thing
    # that knows what a run started, and it SIGKILLs: the guest ignores polite
    # signals and spins at ~140% CPU forever if merely asked to stop.
    bash "$RIG/killgame.sh" >/dev/null 2>&1
    kill -9 "$VNC_PID" "$XVFB_PID" 2>/dev/null
    pkill -9 -x x11vnc 2>/dev/null      # the loop's child outlives the loop
}
trap cleanup EXIT INT TERM

cmd=${1:-watch.sh}
shift || true
case "$cmd" in
    bash|sh) exec "$cmd" "$@" ;;
    *.py)    exec python3 "$RIG/$cmd" "$@" ;;
    *)       exec bash "$RIG/$cmd" "$@" ;;
esac
