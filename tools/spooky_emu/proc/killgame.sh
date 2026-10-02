#!/bin/bash
# killgame.sh - stop this slot's game, Unity player, board and hidden
# display, and PROVE they stopped.  Exit 0 when nothing of the slot is left
# running.
. "$(dirname "$0")/sppath.sh"

stop_pid() {        # <pid>: TERM, wait up to 3 s, then KILL
    local p=$1
    [ -n "$p" ] && kill -0 "$p" 2>/dev/null || return 0
    kill -TERM "$p" 2>/dev/null
    for _ in $(seq 1 30); do kill -0 "$p" 2>/dev/null || return 0; sleep 0.1; done
    kill -KILL "$p" 2>/dev/null
}

# A paused game (the playfield's Pause: SIGSTOP) stopped its runuser too -
# su's job control - and a stopped runuser never reaps its game: all go on.
for f in game unity; do
    for p in $(spp_pid $f) $(cat "$SPP_RIG/$f.rpid" 2>/dev/null); do kill -CONT "$p" 2>/dev/null; done
done
# The game first, then the player, then the namespace's shell (its exit
# drops the /game bind and the private loopback), then the display, then
# whatever the game forked.
for f in game unity ns xvfb; do stop_pid "$(spp_pid $f)"; done
for p in $(spp_mark_pids); do stop_pid "$p"; done
PAD_SLOT=$SPP_SLOT bash "$SPP_PROC/killgame.sh" >/dev/null 2>&1

left=0
for f in game unity ns xvfb; do
    p=$(spp_pid $f)
    if [ -n "$p" ] && kill -0 "$p" 2>/dev/null; then
        echo "killgame.sh: $f ($p) still running" >&2
        left=1
    else
        rm -f "$SPP_RIG/$f.pid" "$SPP_RIG/$f.rpid"
    fi
done
left_marked=$(spp_mark_pids)
if [ -n "$left_marked" ]; then
    echo "killgame.sh: still running:" $left_marked >&2
    left=1
fi
if (PAD_SLOT=$SPP_SLOT; . "$SPP_PROC/procpath.sh"; proc_hw_alive); then
    echo "killgame.sh: the board is still running" >&2
    left=1
fi
[ $left = 0 ] && { rigboard_clear spooky-proc "$SPP_SLOT"; echo stopped; }
exit $left
