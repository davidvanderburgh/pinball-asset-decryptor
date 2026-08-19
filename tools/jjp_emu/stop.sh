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

G=$(pgrep -c -x game 2>/dev/null); G=${G:-0}
C=$(pgrep -fc "${JJP_CUSE_BIN:-/var/tmp/jjpcuse}" 2>/dev/null); C=${C:-0}
echo "game=$G cuse=$C"
[ "$G" = "0" ] || exit 1
