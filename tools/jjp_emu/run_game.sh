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
# 68 IS NORMAL ON A FIRST RUN, and this script now handles it.  The golden disk
# ships a Guns N' Roses hostname; on first boot the game renames itself
# (WONKA-<n>) and asks to be restarted.  A FRESH JAIL IS A FIRST BOOT EVERY
# TIME, because the overlay's upper layer starts empty - so without the restart
# loop below the game appears to die instantly with an empty log, which is
# exactly how this presented.  Restarts are bounded (JJP_MAX_RESTARTS) so a
# genuine crash loop cannot spin forever.
#
# We deliberately do NOT use the image's own scripts/rungame.sh, which answers
# 42/68/69 by rebooting the machine - here that would mean the WSL distro.
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

# The hardware shim is opt-in.  Set JJP_SHIM=1 (build it first with build.sh)
# to give the game a fake set of playfield boards it can read switches from.
# Without it the game still runs - missing boards are non-fatal - it just never
# sees a switch close.
SHIM_ENV=""
if [ "${JJP_SHIM:-0}" = "1" ]; then
    SO=${JJP_SHIM_SO:-/var/tmp/jjphwshim.so}
    if [ ! -f "$SO" ]; then
        echo "run_game.sh: JJP_SHIM=1 but $SO is missing; run build.sh" >&2
        exit 5
    fi
    # The .so must be reachable from INSIDE the jail.
    cp -f "$SO" "$JJP_JAIL/tmp/jjphwshim.so"
    SHIM_ENV='export LD_PRELOAD=/tmp/jjphwshim.so'
    [ -n "${JJP_SHIM_DEBUG:-}" ] && SHIM_ENV="$SHIM_ENV; export JJP_SHIM_DEBUG=1"
fi

RUN='
  export JJPEDIR='"$JJPEDIR"'
  . $JJPEDIR/setenv.sh
  export GAMEDIR=$JJPEDIR/$GAMENAME
  export DISPLAY='"$JJP_DISPLAY"'
  export PULSE_SERVER='"$JJP_PULSE"'
  export HOME=/root
  '"$SHIM_ENV"'
  cd $GAMEDIR
  n=0
  while [ $n -lt '"${JJP_MAX_RESTARTS:-6}"' ]; do
    ./game
    rc=$?
    case "$rc" in
      # 43/44/68 are "exit and be restarted" - a settings restore, a changed
      # setting, or the once-per-fresh-jail hostname reboot.  Restart, bounded.
      #
      # We do NOT try to detect a closed window and skip the restart here.  An
      # earlier attempt checked for the display socket inside the chroot and got
      # it wrong - the Xephyr :1 socket is not where the check looked, so a
      # perfectly normal exit-68 was read as "window closed" and the game was
      # never restarted, leaving a black screen.  It is also unnecessary:
      # closing the window makes the game lose its X server and exit 1 (an X I/O
      # error), which falls through to the "*" case and stops - and even a true
      # loop is capped by JJP_MAX_RESTARTS.
      43|44|68) n=$((n+1)); echo "[rig] game exit $rc - restarting ($n)" ;;
      *) exit $rc ;;
    esac
  done
  echo "[rig] too many restarts; giving up"
  exit 1
'

# The plugged-in key does not unlock this title.  JJP keys are per-title: the
# Sentinel envelope's AES key is different for every game, and a key carries
# only its own title's crypto - so a key that runs Wonka H0007s on Godfather
# even though both present the same vendor code and Feature 0.  Called after a
# launch to turn a bare H0007 into a message that says what is actually wrong.
report_wrong_key() {
    if grep -q 'H0007\|Sentinel key not found' "$JJP_GAME_LOG" 2>/dev/null; then
        echo "WRONG KEY: the plugged-in Sentinel key does not unlock $(jjp_title)."
        echo "  JJP keys are PER-TITLE - each unlocks only its own game.  Plug in"
        echo "  the $(jjp_title) key (this one runs a different title)."
        return 0
    fi
    return 1
}

: > "$JJP_GAME_LOG"
if [ "$DETACH" = "1" ]; then
    setsid chroot "$JJP_JAIL" /bin/bash -c "$RUN" >>"$JJP_GAME_LOG" 2>&1 &
    echo $! > "$JJP_PID_FILE"

    # WATCH the first few seconds instead of a flat `sleep 3` then one check.
    # Two things end this wait early, and both matter to the GUI:
    #
    #   * an H0007 - the plugged-in key does not decrypt THIS title.  A Sentinel
    #     key is per-title, so a Wonka key on Guns N' Roses prints H0007 at the
    #     very first envelope call (before the game touches boards or a display)
    #     and exits.  We fail fast with exit 7 and the WRONG KEY message the
    #     instant it appears - typically ~1 s - instead of waiting a flat 3 and
    #     then only noticing if the process already happened to be gone.
    #   * the game actually coming up - reported the moment it is up rather than
    #     after a fixed delay.
    #
    # "Up for two consecutive checks" avoids a race: a wrong-key game exists for
    # a heartbeat before it H0007s, and we must not read that heartbeat as a
    # healthy launch.  The window is bounded (JJP_LAUNCH_WAIT) so a genuine wedge
    # still returns.
    up=0
    for _ in $(seq 1 "${JJP_LAUNCH_WAIT:-12}"); do
        sleep 1
        if report_wrong_key; then
            exit 7
        fi
        if [ "$(jjp_game_count)" != "0" ]; then
            up=$((up + 1))
            [ "$up" -ge 2 ] && break
        else
            up=0
        fi
    done
    if [ "$up" -lt 2 ]; then
        # No H0007, but the game is not staying up either - it exited for some
        # other reason (see the exit-code table above).  Surface the log tail
        # rather than claiming a launch that did not happen.
        echo "run_game.sh: the game did not stay up and did not report a key error."
        tail -n 6 "$JJP_GAME_LOG" 2>/dev/null | sed 's/^/  game: /'
        exit 8
    fi
    echo "launched detached; pid=$(cat "$JJP_PID_FILE") procs=$(jjp_game_count)"
    echo "log: $JJP_GAME_LOG"
else
    if [ -n "$CAP" ]; then
        setsid timeout -s KILL "$CAP" chroot "$JJP_JAIL" /bin/bash -c "$RUN" >>"$JJP_GAME_LOG" 2>&1
    else
        setsid chroot "$JJP_JAIL" /bin/bash -c "$RUN" >>"$JJP_GAME_LOG" 2>&1
    fi
    rc=$?
    report_wrong_key || true
    echo "EXIT CODE: $rc"
fi
