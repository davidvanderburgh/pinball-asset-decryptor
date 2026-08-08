#!/bin/bash
# Jump the game back to a saved slot. (item 13)
#
#   wsl -u root -e bash loadgame.sh [slot]
#
# Needs root. Kills the currently running game (if any) and restores the one
# saved in the slot, which resumes at the exact ball, score and mode it was
# saved at. Default slot is "quicksave".

set -u
RIG=$(cd "$(dirname "$0")" && pwd)
SLOT=${1:-quicksave}
CRIU=${CRIU:-/var/tmp/criubuild/criu/criu/criu}

[ "$(id -u)" = 0 ] || { echo "loadgame: needs root. Use: wsl -u root -e bash $0 [slot]"; exit 2; }

# Find the slot. It lives under the running guest's rootfs if one is up, else
# read the rootfs from the slot meta of any guest - but the simplest robust
# path is the slot's own recorded rootfs, so try the common locations.
PID=$(pgrep -x game | head -1)
ROOT=""
[ -n "$PID" ] && ROOT=$(tr '\0' '\n' < "/proc/$PID/environ" 2>/dev/null | sed -n 's/^PAD_ROOT=//p' | head -1)
# If no guest is up, fall back to the rootfs padpath would pick, then to the
# slot meta once found.
[ -n "$ROOT" ] || { . "$RIG/padpath.sh"; ROOT=$PAD_ROOT; }

DIR=$ROOT/saves/$SLOT
[ -f "$DIR/slot.meta" ] || { echo "loadgame: no save in slot '$SLOT' (looked in $DIR)"; exit 1; }
# The slot's own recorded rootfs wins - it is where the guest really lived.
SROOT=$(sed -n 's/^root=//p' "$DIR/slot.meta")
[ -n "$SROOT" ] && ROOT=$SROOT

echo "[loadgame] slot '$SLOT'  ->  restoring the game"

# TELL A LIVE watch.sh SESSION THAT THE GUEST IS ABOUT TO VANISH ON PURPOSE.
# Restoring means killing the running guest and putting another in its place;
# watch.sh's poll loop would otherwise read that gap as "the game exited" and
# tear down the whole session - window, playfield and audio included, which is
# what you are playing in. The flag makes it wait instead. Always cleared, even
# if the restore fails, so a failed load cannot wedge the session.
RELOAD_FLAG=$ROOT/dump/reloading
: > "$RELOAD_FLAG" 2>/dev/null
trap 'rm -f "$RELOAD_FLAG" 2>/dev/null' EXIT

# The guest log grew while you kept playing after the save; restorestate.sh
# truncates it back to the size criu recorded and retries - see there.

# PAD_RESTORE_KILL clears the currently-running game (pid collision otherwise);
# PAD_ROOT points restorestate at the right rootfs.
PAD_ROOT="$ROOT" PAD_RESTORE_KILL=1 CRIU="$CRIU" bash "$RIG/restorestate.sh" "$DIR" \
    || { echo "[loadgame] FAILED"; exit 1; }
rm -f "$RELOAD_FLAG" 2>/dev/null
echo "[loadgame] restored slot '$SLOT'."
