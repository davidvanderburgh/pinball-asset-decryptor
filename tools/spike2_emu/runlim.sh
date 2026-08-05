#!/bin/bash
# runlim.sh <log> <seconds> [VAR=VAL ...] - run the game for a bounded time and
# guarantee nothing survives.
#
# DO NOT use `timeout N bash /mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu/run_game.sh`. timeout signals only its DIRECT child, so
# it kills the shell script while the game keeps running as a grandchild under
# qemu-binfmt - and the game installs its own SIGINT/SIGTERM handler (0x1b4f0),
# so even a delivered SIGTERM does not stop it. Every such run leaks a process
# that spins at ~140% CPU forever. Eleven of them once took the host to 90%.
#
# This starts the run in its own session so the whole process GROUP can be
# killed with SIGKILL, then sweeps by name as a belt-and-braces second pass.
set -u
cd /home/david
LOG=${1:-gzrun.log}
SECS=${2:-45}
shift 2 || true

setsid env "$@" bash /mnt/c/Users/david/Documents/development/pinball-asset-decryptor/tools/spike2_emu/run_game.sh > "$LOG" 2>&1 &
LEADER=$!

# setsid makes the child a session leader, so its pid is also its process
# group id, and a negative pid kills the entire group.
sleep "$SECS"
kill -9 -"$LEADER" 2>/dev/null
pkill -9 -f 'godzilla_pro/game' 2>/dev/null
sleep 1

LEFT=$(ps -eo args | grep -c '[g]odzilla_pro/game')
echo "runlim: ${SECS}s elapsed, log=$LOG, survivors=$LEFT"
if [ "$LEFT" -ne 0 ]; then
    echo "runlim: WARNING - $LEFT game process(es) still alive, run killgame.sh"
    exit 1
fi
