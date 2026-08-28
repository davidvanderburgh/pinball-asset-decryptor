#!/bin/bash
# runlim.sh <log> <seconds> [VAR=VAL ...] - run the game for a bounded time and
# guarantee nothing survives.
#
# DO NOT use `timeout N bash $RIG/run_game.sh`. timeout signals only its DIRECT child, so
# it kills the shell script while the game keeps running as a grandchild under
# qemu-binfmt - and the game installs its own SIGINT/SIGTERM handler (0x1b4f0),
# so even a delivered SIGTERM does not stop it. Every such run leaks a process
# that spins at ~140% CPU forever. Eleven of them once took the host to 90%.
#
# This starts the run in its own session so the whole process GROUP can be
# killed with SIGKILL, then sweeps by name as a belt-and-braces second pass.
. "$(dirname "$0")/padpath.sh"
set -u
cd $HOME
LOG=${1:-gzrun.log}
SECS=${2:-45}
shift 2 || true

# Item 74 made an uncached card COPY FIRST (~60-70 s) before the guest
# starts, which would eat this wrapper's whole budget inside the wait and
# SIGKILL a run in which the game never existed. A timed instrument wants the
# game up NOW, so it keeps the old boot-off-9p hybrid; pass PAD_CARD_PRECOPY=1
# to measure the pre-copy path itself.
export PAD_CARD_PRECOPY=${PAD_CARD_PRECOPY:-0}

setsid env "$@" bash "$RIG/run_game.sh" > "$LOG" 2>&1 &
LEADER=$!

# setsid makes the child a session leader, so its pid is also its process
# group id, and a negative pid kills the entire group.
sleep "$SECS"
kill -9 -"$LEADER" 2>/dev/null
# Two comm shapes for the guest: a plain run is <title>/game, but a
# PAD_PIVOT run re-roots and shows as /.padqemu/game — a pivoted guest
# dodged the old single-pattern sweep and spun at 140% CPU until a manual
# killgame.sh (2026-08-27).
pkill -9 -f 'godzilla_pro/game' 2>/dev/null
pkill -9 -f '\.padqemu/game' 2>/dev/null
sleep 1

LEFT=$(ps -eo args | grep -cE '[g]odzilla_pro/game|[.]padqemu/game')
echo "runlim: ${SECS}s elapsed, log=$LOG, survivors=$LEFT"
if [ "$LEFT" -ne 0 ]; then
    echo "runlim: WARNING - $LEFT game process(es) still alive, run killgame.sh"
    exit 1
fi
