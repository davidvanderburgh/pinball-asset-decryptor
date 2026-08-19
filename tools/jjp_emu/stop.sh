#!/bin/bash
# Take the whole rig down and PROVE it went.
#
# Order is the reverse of watch.sh, and the game goes first: a live game holds
# the CUSE devices open, and tearing those out from under it is how you get a
# process stuck in D-state that no signal will touch.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/padpath.sh"
[ "$(id -u)" = "0" ] || { echo "stop.sh: must run as root" >&2; exit 2; }

bash "$HERE/killgame.sh" || echo "stop.sh: game processes survived"
bash "$HERE/jjpcuse.sh" stop 2>/dev/null
bash "$HERE/display.sh" --stop 2>/dev/null

# The Sentinel daemons stay up by default: they are tiny, they hold the key
# registration, and restarting them costs ~15 s of re-poll on the next start.
if [ "${1:-}" = "--all" ]; then
    bash "$HERE/killgame.sh" --all
    bash "$HERE/unjail.sh"
fi

# jjp_game_count, not pgrep: a stopped game leaves zombies that pgrep counts
# and jjp_game_count does not (see padpath.sh).  Without this the teardown
# reports "game=3" over three corpses and exits non-zero, which reads as a
# failed stop when the stop in fact succeeded.
G=$(jjp_game_count)
C=$(pgrep -fc "${JJP_CUSE_BIN:-/var/tmp/jjpcuse}" 2>/dev/null); C=${C:-0}
echo "game=$G cuse=$C"
[ "$G" = "0" ] || exit 1
