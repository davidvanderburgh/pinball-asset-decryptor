#!/bin/bash
# Launch the JJP game in the jail.  This is the launch that WORKS as of
# 2026-08-19: it reaches a live, stable game process with the dongle attached.
#
# WHAT IT DELIBERATELY DOES NOT DO.  It does not use the image's own
# scripts/rungame.sh.  That script is a `while true` supervisor that reboots the
# machine on exit codes 42/68/69 - fine on a cabinet, wrong here, where "reboot"
# would mean the WSL distro.  We run the game directly and let watch.sh decide
# what an exit code means.  The environment below is exactly what rungame.sh
# exports, minus the reboots.
#
# EXIT CODES (from the image's own rungame.sh case table):
#     1 dongle missing   42 net/delta update   43 settings restore
#    44 setting changed  68 maintenance reboot (hostname set)
#    69 maintenance reboot  127 exe not found  254 escape pressed
#   255 unexpected exit   137 SIGKILL (ours - it was still running)
#
# 68 IS NORMAL ON A FIRST RUN.  The golden disk ships with a Guns N' Roses
# hostname; the game renames itself (WONKA-<n>) and asks for a reboot.  Just run
# it again - the jail's upper layer has kept the new name.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/padpath.sh"

[ "$(id -u)" = "0" ] || { echo "run_game.sh: must run as root" >&2; exit 2; }
mountpoint -q "$JJP_JAIL" || { echo "run_game.sh: jail not mounted; run jail.sh" >&2; exit 3; }

DETACH=0; CAP=""
while [ $# -gt 0 ]; do
    case "$1" in
        --detach) DETACH=1 ;;
        --cap) shift; CAP="$1" ;;      # seconds; SIGKILL after.  Native x86-64,
                                       # so a bounded run is safe here (unlike
                                       # the Spike 2 qemu rig, where `timeout`
                                       # leaks 140%-CPU processes forever).
        *) echo "unknown arg: $1" >&2; exit 64 ;;
    esac
    shift
done

RUN='
  export JJPEDIR='"$JJPEDIR"'
  . $JJPEDIR/setenv.sh
  export GAMEDIR=$JJPEDIR/$GAMENAME
  export DISPLAY='"$JJP_DISPLAY"'
  export PULSE_SERVER='"$JJP_PULSE"'
  export HOME=/root
  cd $GAMEDIR
  exec ./game
'

: > "$JJP_GAME_LOG"
if [ "$DETACH" = "1" ]; then
    setsid chroot "$JJP_JAIL" /bin/bash -c "$RUN" >>"$JJP_GAME_LOG" 2>&1 &
    echo $! > "$JJP_PID_FILE"
    sleep 2
    echo "launched detached; pid=$(cat "$JJP_PID_FILE") procs=$(pgrep -c -x game || echo 0)"
    echo "log: $JJP_GAME_LOG"
else
    if [ -n "$CAP" ]; then
        setsid timeout -s KILL "$CAP" chroot "$JJP_JAIL" /bin/bash -c "$RUN" >>"$JJP_GAME_LOG" 2>&1
    else
        setsid chroot "$JJP_JAIL" /bin/bash -c "$RUN" >>"$JJP_GAME_LOG" 2>&1
    fi
    echo "EXIT CODE: $?"
fi
