#!/bin/bash
# The SINGLE definition of "is a JJP game running".
#
# This script exists because the matching Spike 2 pair (alive.sh vs killgame.sh)
# once disagreed about what a running rig is, and a pair of confident zeros led
# to a second full run being started on top of a live one.
#
# TWO TRAPS, both paid for in this rig on 2026-08-19:
#
#  1. The game runs as `./game`, so its argv[0] is RELATIVE.  `pgrep -f
#     /jjpe/gen1/Wonka/game` matches NOTHING and reports a confident 0 over a
#     fully live game.  That mistake leaked twelve processes and ~4.8 GB before
#     it was caught.  Match on the process NAME with -x, never on a full path.
#
#  2. Run this from INSIDE WSL.  Git Bash's pgrep sees only Windows processes,
#     so every pattern misses.  We refuse rather than reassure.
set -u
if [ ! -r /proc/1/stat ]; then
    echo "alive.sh: no readable /proc - this is not a WSL/Linux shell." >&2
    echo "Run it as:  wsl -e bash tools/jjp_emu/alive.sh" >&2
    exit 2
fi

# `pgrep -c` prints 0 AND exits 1 when nothing matches - capture, then default.
GAMES=$(pgrep -c -x game 2>/dev/null); GAMES=${GAMES:-0}
HASPLMD=$(pgrep -c -x hasplmd_x86_64 2>/dev/null); HASPLMD=${HASPLMD:-0}
AKSUSBD=$(pgrep -c -x aksusbd_x86_64 2>/dev/null); AKSUSBD=${AKSUSBD:-0}

if [ "${1:-}" = "--total" ]; then
    echo $(( GAMES ))
    exit 0
fi

echo "game            : $GAMES"
echo "hasplmd         : $HASPLMD"
echo "aksusbd         : $AKSUSBD"
if [ "$GAMES" -gt 0 ]; then
    echo
    ps -o pid,pgid,rss,etime,comm -C game 2>/dev/null
fi
echo
echo "TOTAL GAME PROCS: $GAMES  $([ "$GAMES" = "0" ] && echo '(clean)' || echo '(LIVE)')"
