#!/bin/bash
# Save the running game to a named slot - and KEEP PLAYING. (item 13)
#
#   wsl -u root -e bash savegame.sh [slot]
#
# Needs root (criu does). The game must have been started with PAD_PIVOT=1 (a
# chroot guest cannot be checkpointed). Default slot is "quicksave". The game
# is left RUNNING - saving does not interrupt play - so pair this with
# loadgame.sh to jump back later.
#
# Slots live in <rootfs>/saves/<slot>, and the rootfs is read from the running
# guest's own environment, so you never have to tell it where anything is.

set -u
RIG=$(cd "$(dirname "$0")" && pwd)
SLOT=${1:-quicksave}
CRIU=${CRIU:-/var/tmp/criubuild/criu/criu/criu}

[ "$(id -u)" = 0 ] || { echo "savegame: needs root. Use: wsl -u root -e bash $0 [slot]"; exit 2; }
PID=$(pgrep -x game | head -1)
[ -n "$PID" ] || { echo "savegame: no game is running. Start one with PAD_PIVOT=1 first."; exit 1; }

# The rootfs and title straight from the guest's environment - no guessing, and
# correct even though this runs as root (whose \$HOME is /root, not the games').
envval() { tr '\0' '\n' < "/proc/$PID/environ" 2>/dev/null | sed -n "s/^$1=//p" | head -1; }
ROOT=$(envval PAD_ROOT)
GAME=$(envval PAD_GAME)
[ -n "$ROOT" ] || { echo "savegame: the guest has no PAD_ROOT - was it started with PAD_PIVOT=1?"; exit 1; }

DIR=$ROOT/saves/$SLOT
rm -rf "$DIR"; mkdir -p "$DIR"

echo "[savegame] slot '$SLOT'  <-  $GAME (pid $PID)"
CRIU="$CRIU" bash "$RIG/savestate.sh" "$DIR" "$PID" || { echo "[savegame] FAILED"; exit 1; }

# Record what loadgame.sh needs: the rootfs, the title, and the guest log's
# size at this instant. leave-running keeps appending to that log, so a later
# restore would fail criu's "file changed size" check - loadgame truncates it
# back to exactly here, which is harmless (only post-save log lines are lost).
{
    echo "root=$ROOT"
    echo "game=$GAME"
    echo "logsize=$(stat -c %s "$ROOT/dump/game.out" 2>/dev/null || echo 0)"
} > "$DIR/slot.meta"

echo "[savegame] saved to slot '$SLOT'. Keep playing; loadgame.sh $SLOT jumps back here."
