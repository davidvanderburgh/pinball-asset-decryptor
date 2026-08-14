#!/bin/bash
# glshot.sh - the guest's own framebuffer, on demand, as a PNG.
#
#   wsl -e bash $RIG/glshot.sh [/mnt/c/tmp/somewhere/shot.png]
#
# padglhost has carried this oracle since the GL journal went in (jgl_poll,
# padglhost.c:2811) and NOTHING in the repo could reach it: touch
# $ROOT/dump/glshot.req and the next poll reads the screen FBO with
# glReadPixels and writes $ROOT/dump/glshot.png, restoring the guest's own FBO
# binding around it. Works on a LIVE run, needs no rebuild and no restart.
#
# WHY IT MATTERS AND WHEN TO PREFER IT TO shotwin.py: this is the only picture
# instrument that is not a WINDOW grab. shotwin.py's pixels have been through
# win_present()'s letterbox, the window chrome and whatever the WSLg RAIL proxy
# did on the way to the desktop - three transforms between the framebuffer and
# what you measure, and item 45 is a geometry item where every one of them is a
# candidate. This one is fb_w x fb_h exactly, straight off the FBO.
#
# ONE ORIENTATION FACT YOU MUST KNOW BEFORE JUDGING A SHOT, because it has
# already cost this rig a wrong conclusion once (handoff, "no Y flip is
# needed"): write_png flips rows itself (padglhost.c:1957), so a CORRECT
# framebuffer comes out of here the right way up. A shot that is upside down
# means the guest drew it upside down. Do not "correct" for the flip twice.
. "$(dirname "$0")/padpath.sh"

# Same /proc test as alive.sh and killgame.sh: from Git Bash on Windows the
# paths below silently resolve to nothing and this would report a cheerful
# failure. Refuse rather than reassure.
if [ ! -d /proc/1 ] || ! grep -qs . /proc/1/comm 2>/dev/null; then
    echo "glshot.sh: this must run INSIDE WSL (wsl -e bash \$RIG/glshot.sh)" >&2
    exit 2
fi

DUMP="$ROOT/dump"
REQ="$DUMP/glshot.req"
PNG="$DUMP/glshot.png"
DEST="${1:-}"

if [ ! -e "$DUMP/padgl" ]; then
    echo "glshot.sh: no $DUMP/padgl - is a run up?" >&2
    exit 1
fi

rm -f "$PNG"
: > "$REQ"

# padglhost answers from jgl_poll, which runs per frame and when idle, so this
# is normally one or two frames. Poll rather than sleep a flat interval: the
# request file being GONE is padglhost's own acknowledgement (it unlinks it
# after writing), which is a stronger signal than the png merely existing.
i=0
while [ "$i" -lt 60 ]; do
    if [ ! -e "$REQ" ] && [ -s "$PNG" ]; then break; fi
    sleep 0.25
    i=$((i + 1))
done

if [ -e "$REQ" ] || [ ! -s "$PNG" ]; then
    rm -f "$REQ"
    echo "glshot.sh: padglhost did not answer in 15 s (run wedged, or not windowed?)" >&2
    exit 1
fi

if [ -n "$DEST" ]; then
    mkdir -p "$(dirname "$DEST")"
    cp "$PNG" "$DEST" || exit 1
    echo "wrote $DEST"
else
    echo "wrote $PNG"
fi
ls -l "${DEST:-$PNG}"
