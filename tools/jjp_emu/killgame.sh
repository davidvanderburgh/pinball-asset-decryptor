#!/bin/bash
# Stop a JJP run and PROVE it stopped.  Never assume - re-read until zero.
#
# A normal JJP launch is THREE processes sharing a process group (the game, a
# small helper, and a worker).  Killing the leader is not enough, so we kill by
# name and then verify.  See alive.sh for why the name (not a path) is matched.
set -u
if [ ! -r /proc/1/stat ]; then
    echo "killgame.sh: no readable /proc - this is not a WSL/Linux shell." >&2
    echo "Run it as:  wsl -u root -- bash tools/jjp_emu/killgame.sh" >&2
    exit 2
fi

BEFORE=$(pgrep -c -x game 2>/dev/null); BEFORE=${BEFORE:-0}
pkill -9 -x game 2>/dev/null
sleep 1
AFTER=$(pgrep -c -x game 2>/dev/null); AFTER=${AFTER:-0}

# Second pass for anything that was mid-fork on the first sweep.
if [ "$AFTER" != "0" ]; then
    pkill -9 -x game 2>/dev/null
    sleep 1
    AFTER=$(pgrep -c -x game 2>/dev/null); AFTER=${AFTER:-0}
fi

echo "killed $(( BEFORE - AFTER )); still running: $AFTER"
[ "$AFTER" = "0" ] || { echo "REFUSING TO REPORT CLEAN - $AFTER game process(es) survived." >&2; exit 1; }

# The Sentinel daemons are deliberately LEFT UP: they are tiny, they hold the
# dongle registration, and tearing them down costs ~15 s of re-poll on the next
# start.  Pass --all to take them down too.
if [ "${1:-}" = "--all" ]; then
    pkill -9 -x hasplmd_x86_64 2>/dev/null
    pkill -9 -x aksusbd_x86_64 2>/dev/null
    echo "sentinel daemons stopped"
fi
