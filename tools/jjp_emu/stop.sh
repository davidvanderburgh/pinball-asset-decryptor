#!/bin/bash
# Take the whole rig down and PROVE it went.
#
# ORDER AND SIGNAL BOTH MATTER, and both were learned from ghost windows.
#
#  * The game goes first, by process GROUP, so its restart supervisor cannot
#    relaunch it after we kill it (killgame.sh).
#
#  * The WINDOWED helpers - the nested Xephyr and the matrix UI - are asked to
#    quit with SIGTERM and given a moment, NOT SIGKILL'd outright.  This is the
#    important part: a Wayland/X client that is SIGKILL'd never releases its
#    WSLg surface, so its frame lingers on the Windows desktop as an
#    unresponsive GHOST that no amount of process-killing can clear - only
#    `wsl --shutdown` does.  SIGTERM lets them close their own windows first,
#    which releases the surface.  (SIGKILL'ing them is exactly how the ghosts
#    got there.)
#
#  * Only then are survivors SIGKILL'd, and the boards taken down.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/padpath.sh"
[ "$(id -u)" = "0" ] || { echo "stop.sh: must run as root" >&2; exit 2; }

NEST=${JJP_NESTED:-:1}

# 0. Remember where BOTH windows are, FIRST - while there are still windows to
#    ask.  Neither can do it itself: Xephyr cannot place its own host window,
#    and the Tk matrix reads its own position as -32768 under WSLg (jjpsw.py
#    keeps the size; the position is ours).  Best-effort - a window position is
#    a convenience and must never hold up a teardown.
bash "$HERE/winpos.sh" save game || true
bash "$HERE/winpos.sh" save matrix || true

# 1. The game + its supervisor group.  SIGKILL is fine here: the game is a
#    client of Xephyr, not of WSLg directly, and Xephyr is closed cleanly next.
bash "$HERE/killgame.sh" || echo "stop.sh: game processes survived"

# 2. Ask the windowed helpers to close their OWN windows, so WSLg releases the
#    surfaces instead of leaving ghosts.
pkill -TERM -f 'jjpsw\.py' 2>/dev/null            # the matrix UI (Tk)
pkill -TERM -f "Xephyr $NEST" 2>/dev/null          # the nested display

# 3. Give them up to ~2 s to paint their close and drop the surface.
for _ in 1 2 3 4; do
    m=$(pgrep -fc 'jjpsw\.py' 2>/dev/null); m=${m:-0}
    x=$(pgrep -fc "Xephyr $NEST" 2>/dev/null); x=${x:-0}
    [ "$m" = "0" ] && [ "$x" = "0" ] && break
    sleep 0.5
done

# 4. SIGKILL whatever ignored SIGTERM (a hung client is worse than a ghost).
pkill -9 -f 'jjpsw\.py' 2>/dev/null
pkill -9 -f "Xephyr $NEST" 2>/dev/null

# 5. The boards.
bash "$HERE/jjpcuse.sh" stop 2>/dev/null

# The Sentinel daemons stay up by default (tiny, and they hold the key
# registration).  --all takes them and the jail down too.
if [ "${1:-}" = "--all" ]; then
    bash "$HERE/killgame.sh" --all
    bash "$HERE/unjail.sh"
fi

G=$(jjp_game_count)
M=$(pgrep -fc 'jjpsw\.py' 2>/dev/null); M=${M:-0}
X=$(pgrep -fc "Xephyr $NEST" 2>/dev/null); X=${X:-0}
C=$(pgrep -fc "${JJP_CUSE_BIN:-/var/tmp/jjpcuse}" 2>/dev/null); C=${C:-0}
echo "game=$G matrix=$M xephyr=$X cuse=$C"
{ [ "$G" = "0" ] && [ "$M" = "0" ] && [ "$X" = "0" ]; } || exit 1
