#!/bin/bash
# REAL-GAME save-state acceptance, headless (no window). Proves the full chain
# on an actual title: boot under PAD_PIVOT -> savestate -> restorestate ->
# the game RESUMES (item 13). The offline sibling savetest.sh does the same
# with a stub; this uses a real game and so also exercises its 19 threads, its
# GBs of assets, and the whole device/pty external set for real.
#
#   wsl -u root -e env PAD_ROOT=/home/you/spike2root bash savetest_real.sh [title]
#
# ROOT, and PAD_ROOT matters: criu needs root, but the games live in the
# INVOKING user's rootfs, and as root $HOME is /root - so pass PAD_ROOT
# pointing at the real rootfs, or run it where padpath resolves it correctly.
# The guest itself is booted as root ON PURPOSE (option (a), item 13): a root
# PAD_PIVOT guest has NO user namespace, which is what makes restore work -
# an unprivileged userns forces setgroups off and criu cannot restore into it.
# It is also how the game runs on the real Spike machine.
#
# Continuity proxy = eglshim's frame count: it climbs while the game renders,
# so a restore RESUMES it high where a fresh boot would restart it low.
#
# NOT a windowed run and NOT a measurement run (no padglhost/video/audio), so
# it cannot collide with a real one - but it is still a real guest, so it
# refuses to start if one is already up.

set -u
RIG=$(cd "$(dirname "$0")" && pwd)
. "$RIG/padpath.sh"
GAME=${1:-godzilla_pro}
CRIU=${CRIU:-/var/tmp/criubuild/criu/criu/criu}
WORK=/var/tmp/savetest_real
DUMP=$WORK/dump

[ "$(id -u)" = 0 ] || { echo "savetest_real: needs root (criu does). Use: wsl -u root -e env PAD_ROOT=... bash $0"; exit 2; }
[ -x "$ROOT/games/$GAME/game" ] || {
    echo "savetest_real: no game ELF at $ROOT/games/$GAME/game"
    echo "  set PAD_ROOT to the rootfs that holds the games (as root, \$HOME is /root)."
    exit 2; }
if pgrep -x game >/dev/null; then echo "savetest_real: a guest is already running - refusing"; exit 1; fi

frames() { grep -aoE '\[eglshim\] [0-9]+ frames' "$ROOT/dump/game.out" 2>/dev/null | tail -1 | grep -oE '[0-9]+'; }

cleanup() {
    echo "=== teardown"
    pkill -9 -x game 2>/dev/null
    pkill -9 -f '\.padqemu/game' 2>/dev/null
    pkill -9 -f nodebus.py 2>/dev/null
    [ -s "$DUMP/restored.pid" ] && kill -9 "$(cat "$DUMP/restored.pid")" 2>/dev/null
    sleep 1
    bash "$RIG/alive.sh" | grep -E 'TOTAL|guest|node'
    rm -rf "$WORK"    # the dump is ~500 MB
}
trap cleanup EXIT

rm -rf "$WORK"; mkdir -p "$DUMP"
rm -f "$ROOT/dump/game.out"

echo "=== booting $GAME headless under PAD_PIVOT=1 (root, no userns)"
PAD_PIVOT=1 PAD_ROOT="$ROOT" PAD_GAME="$GAME" bash "$RIG/run_game.sh" \
    >"$WORK/boot.outer" 2>&1 &
for i in $(seq 1 300); do PID=$(pgrep -x game | head -1); [ -n "$PID" ] && break; sleep 0.1; done
[ -n "${PID:-}" ] || { echo "  game never came up:"; sed 's/^/    /' "$WORK/boot.outer"; exit 1; }
echo "  game pid $PID; booting ~30 s"
sleep 30
kill -0 "$PID" 2>/dev/null || { echo "  game died during boot:"; tail -20 "$ROOT/dump/game.out"; exit 1; }
V0=$(frames); echo "  running, eglshim frames=$V0"

# STOP at dump so the log fd stops growing (else criu's fd-size check fails on
# restore). A real save that must not interrupt play needs the log handled
# instead - see the handoff.
echo "=== savestate (stop at dump)"
CRIU="$CRIU" PAD_SAVE_STOP=1 bash "$RIG/savestate.sh" "$DUMP" "$PID" || { echo "  savestate FAILED"; exit 1; }

sleep 1
kill -9 "$PID" 2>/dev/null
pkill -9 -f nodebus.py 2>/dev/null
sleep 2
VF=$(frames); echo "  original killed, frozen frames=$VF"

echo "=== restorestate"
CRIU="$CRIU" bash "$RIG/restorestate.sh" "$DUMP" || { echo "  restorestate FAILED"; exit 1; }
sleep 6
V4=$(frames); sleep 3; V5=$(frames)
echo "  after restore: frames $V4 -> $V5 (frozen was $VF)"

RPID=$(cat "$DUMP/restored.pid" 2>/dev/null)
[ -n "$V4" ] && [ "$V4" != "$V5" ] || { echo "  FAIL  restored game not producing frames"; exit 1; }
[ "$V4" -gt "$VF" ] 2>/dev/null || { echo "  FAIL  frame count RESTARTED ($VF -> $V4) - a fresh boot, not a restore"; exit 1; }

echo
echo "  PASS  the REAL game RESUMED across save/restore: frozen $VF -> $V4 -> $V5"
echo "        (restored pid $RPID, still rendering)"
