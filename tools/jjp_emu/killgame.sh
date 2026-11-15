#!/bin/bash
# Stop a JJP run and PROVE it stopped.  Never assume - re-read until zero.
#
# A normal JJP launch is THREE `game` processes sharing a process group, AND a
# supervising bash loop that restarts the game on a maintenance-reboot exit
# (run_game.sh).  That loop is the trap: `pkill -x game` kills the game but not
# the bash around it, which then immediately relaunches - so the run appears
# unkillable.  The PID file holds the loop's pid, which is the group LEADER, so
# we kill the whole process group first and only then sweep by name.
set -u
if [ ! -r /proc/1/stat ]; then
    echo "killgame.sh: no readable /proc - this is not a WSL/Linux shell." >&2
    echo "Run it as:  wsl -u root -- bash tools/jjp_emu/killgame.sh" >&2
    exit 2
fi

HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/padpath.sh"

BEFORE=$(jjp_game_count)

# 1. The supervising loop, by its process GROUP, so it cannot relaunch the game
#    after we kill it.  kill -PID sends to the whole group.
if [ -r "${JJP_PID_FILE:-/var/tmp/jjp_game.pid}" ]; then
    LEADER=$(cat "${JJP_PID_FILE:-/var/tmp/jjp_game.pid}" 2>/dev/null)
    if [ -n "$LEADER" ] && [ -d "/proc/$LEADER" ]; then
        PGID=$(awk '{print $5}' "/proc/$LEADER/stat" 2>/dev/null)
        [ -n "$PGID" ] && kill -9 -- "-$PGID" 2>/dev/null
    fi
fi
# 2. Any supervising bash that still holds a ./game loop, matched on its body -
#    only inside the JJP jail: other rigs share this WSL.
for p in $(pgrep -f 'while \[ \$n -lt' 2>/dev/null); do
    [ "$(readlink "/proc/$p/root" 2>/dev/null)" = "$JJP_JAIL" ] && kill -9 "$p" 2>/dev/null
done
# 3. The game processes themselves - and the boot menu, which on a multi-boot
#    image is what the run is sitting in before any game process exists (item
#    117).  It is a client of the nested Xephyr, not of WSLg, so SIGKILL leaves
#    no ghost.  NEVER `pkill -x game`: a Spike 2 rig's game has the same name
#    and was killed by it (PAD-1335); jjp_rig_pids keeps to the JJP jail.
sweep() { kill -9 $(jjp_rig_pids game) $(jjp_rig_pids jjpselect) 2>/dev/null; }
sweep
sleep 1
AFTER=$(( $(jjp_game_count) + $(jjp_select_count) ))

# Second pass for anything that was mid-fork on the first sweep.
if [ "$AFTER" != "0" ]; then
    sweep
    sleep 1
    AFTER=$(( $(jjp_game_count) + $(jjp_select_count) ))
fi

echo "killed $(( BEFORE - AFTER )); still running: $AFTER"
# A killed game whose thread is stuck in the kernel (D state) is a zombie that
# keeps ALL its memory; the jail check above cannot see it (its root is gone).
# PAD-1337: in a WSL whose sync() hangs (one superblock never answers; all
# distros share the kernel) the game's persistence thread blocks in sync(2) -
# called through an import the protected binary resolves itself, so no
# preload can catch it - and every killed game stays behind like this: ~20
# held 15 GB.  Say so instead of reporting clean.
STUCK=0; STUCK_KB=0
for p in $(ps -eo pid=,stat=,comm= | awk '$3=="game" && $2 ~ /^Z/ {print $1}'); do
    for t in /proc/$p/task/*; do
        if [ "$(cut -d' ' -f3 "$t/stat" 2>/dev/null)" = "D" ]; then
            STUCK=$((STUCK + 1))
            STUCK_KB=$((STUCK_KB + $(awk '/VmRSS/{print $2}' "$t/status" 2>/dev/null || echo 0)))
            break
        fi
    done
done
[ "$STUCK" = 0 ] || echo "WARNING: $STUCK killed game(s) stuck in the kernel still hold $((STUCK_KB / 1024)) MB; only restarting WSL (wsl --shutdown) frees it" >&2
[ "$AFTER" = "0" ] || { echo "REFUSING TO REPORT CLEAN - $AFTER game process(es) survived." >&2; exit 1; }
rigboard_clear jjp 0

# The Sentinel daemons are deliberately LEFT UP: they are tiny, they hold the
# dongle registration, and tearing them down costs ~15 s of re-poll on the next
# start.  Pass --all to take them down too.
if [ "${1:-}" = "--all" ]; then
    pkill -9 -x hasplmd_x86_64 2>/dev/null
    pkill -9 -x aksusbd_x86_64 2>/dev/null
    echo "sentinel daemons stopped"
fi
