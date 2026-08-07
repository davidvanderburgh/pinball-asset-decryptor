#!/bin/bash
# runbridge.sh <log> <seconds> [gpu|soft] - run the game with rendering bridged
# to a native host process.
#
# The ring lives at spike2root/dump/padgl, which the chrooted guest sees as
# /dump/padgl, so no extra mount is needed. The host is started FIRST (it
# creates the ring and waits), and is killed with the guest afterwards - the
# same process-group discipline as runlim.sh, because nothing here exits on its
# own and orphans spin at full CPU.
. "$(dirname "$0")/padpath.sh"
set -u
cd $HOME
LOG=${1:-gzbridge.log}
SECS=${2:-30}
MODE=${3:-gpu}

RING_HOST=$ROOT/dump/padgl
RING_GUEST=/dump/padgl
HOSTLOG=$HOME/padglhost.log

# 1360x768 is the game's own UI size, not a guess: its post-boot screens set a
# scissor of exactly 0,312,1360,768 inside a 1920x1080 surface. At 1920x1080 the
# picture therefore filled the top-left corner and the other 63% stayed black,
# which is what "the picture goes black after the splash" actually was. At
# 1360x768 the frame is 100% lit and the splash still renders.
export PAD_GL_W=${PAD_GL_W:-1360}
export PAD_GL_H=${PAD_GL_H:-768}

rm -f "$RING_HOST"
if [ "$MODE" = gpu ]; then
    export GALLIUM_DRIVER=d3d12
    echo "renderer: d3d12 (GPU)"
else
    unset GALLIUM_DRIVER
    echo "renderer: llvmpipe (software)"
fi

setsid env PAD_GL_DUMP="${PAD_GL_DUMP:-}" \
           PAD_GL_FRAME_EVERY="${PAD_GL_FRAME_EVERY:-30}" \
           PAD_GL_MAX_FRAMES="${PAD_GL_MAX_FRAMES:-20}" \
           ./padglhost "$RING_HOST" > "$HOSTLOG" 2>&1 &
HOSTPG=$!

# wait for the host to create and publish the ring
for i in $(seq 1 100); do
    [ -s "$RING_HOST" ] && break
    sleep 0.1
done
sleep 0.3
grep -aE 'GL |ring |ready' "$HOSTLOG" | head -3

setsid env PAD_THREAD_ENTRY=1 PAD_AUDIO_UNGATE=1 PAD_GL_BRIDGE="$RING_GUEST" \
           bash "$RIG/run_game.sh" > "$LOG" 2>&1 &
GAMEPG=$!

# Ctrl-C used to leak BOTH processes: they are setsid'd into their own sessions
# so the terminal's SIGINT never reaches them, and the script died inside the
# sleep below before any kill ran. Trap it.
trap 'echo "[runbridge] interrupted, tearing down"; teardown; exit 130' INT TERM

teardown() {
    kill -9 -"$GAMEPG" 2>/dev/null
    # comm-based, which matches exactly one process and does not depend on how
    # the guest's path happened to be spelled on the exec. See alive.sh.
    pkill -9 -x game 2>/dev/null
    pkill -9 -f arm-binfmt 2>/dev/null
    kill -9 -"$HOSTPG" 2>/dev/null
    pkill -9 -x padglhost 2>/dev/null
}

sleep "$SECS"
kill -9 -"$GAMEPG" 2>/dev/null
pkill -9 -x game 2>/dev/null
pkill -9 -f arm-binfmt 2>/dev/null
sleep 1
# SIGINT first so it prints its totals, then make sure. Killing the process
# GROUP alone proved unreliable here, so sweep by name too - the same lesson as
# runlim.sh: verify what is left, never assume the kill landed.
kill -INT -"$HOSTPG" 2>/dev/null
pkill -INT -x padglhost 2>/dev/null
sleep 1
kill -9 -"$HOSTPG" 2>/dev/null
pkill -9 -x padglhost 2>/dev/null
sleep 1

echo "--- host ---"
grep -aE 'fps|UNKNOWN|FAILED|wrote|stopped' "$HOSTLOG" | tail -12
echo "--- guest ---"
grep -a '\[bridge\]' "$LOG" | head -4
# Count LIVE processes only, and give the just-killed ones a moment to be
# reaped. Two false alarms came from doing this the obvious way: counting
# zombies reported a survivor that had already exited, and an `ps | awk` count
# picked up WSL's "your 131072x1 screen size is bogus" warning as a match.
# pgrep counts processes and nothing else. A check that cries wolf is worse
# than no check, because you learn to ignore it.
#
# Counted by comm rather than by the old `-f 'godzilla_pro/game'`. That pattern
# does match the running guest, but it ALSO matches any shell whose command
# line contains the string, so it can cry wolf; `-x game` cannot. See alive.sh.
# `pgrep -c` prints 0 AND exits non-zero on no match, so `|| echo 0` would emit
# "0\n0" and break every arithmetic use downstream.
live() { local c; c=$(pgrep -c "$@" 2>/dev/null); echo "${c:-0}"; }
for i in 1 2 3 4 5; do
    G=$(live -x game); Q=$(live -f arm-binfmt); H=$(live -x padglhost)
    [ "$G" = 0 ] && [ "$Q" = 0 ] && [ "$H" = 0 ] && break
    sleep 0.5
done
printf 'leftover game processes: %s (MUST be 0)\n' "$G"
printf 'leftover qemu arm      : %s (MUST be 0)\n' "$Q"
printf 'leftover padglhost     : %s (MUST be 0)\n' "$H"
