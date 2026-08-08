#!/bin/bash
# OFFLINE acceptance for the save-state path (item 13). No real game, no GL,
# no video, no audio - so it is NOT a measurement run and cannot collide with
# one. It boots a STUB "game" through the REAL run_game.sh under PAD_PIVOT=1,
# then drives savestate.sh + restorestate.sh and checks the guest RESUMED
# rather than restarted.
#
#   wsl -u root -e bash savetest.sh
#
# WHY A STUB. The criuladder.sh rungs proved criu can restore each shape in
# isolation. This proves the RIG'S OWN run_game.sh produces a checkpointable
# guest and that savestate/restorestate drive it - the two scripts wired
# together, on the actual boot script, without needing a real game (which
# would pull in padglhost, the video ring, audio, and a multi-minute boot).
# The stub stands in for the game: it sets comm=game (so pgrep finds it like
# the real one), opens /dev/ttymxc1 (the node bus, rung F's shape), and counts
# to /data/count so continuity can be judged the ladder's way.

set -u
CRIU=${CRIU:-/var/tmp/criubuild/criu/criu/criu}
. "$(dirname "$0")/padpath.sh"
R=$ROOT
WORK=/var/tmp/savetest
DUMP=$WORK/dump

[ "$(id -u)" = 0 ] || { echo "savetest: needs root. Use: wsl -u root -e bash $0"; exit 2; }

# clean any leftover of a previous run before touching anything
pkill -9 -x game 2>/dev/null
pkill -9 -f 'nodebus.py' 2>/dev/null
rm -rf "$WORK"; mkdir -p "$DUMP"

# --- the stub game -------------------------------------------------------
cat > "$WORK/stub.c" <<'EOF'
#include <stdio.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/prctl.h>
int main(void)
{
    long i = 0;
    prctl(PR_SET_NAME, "game", 0, 0, 0);      /* so pgrep -x game finds it */
    int t = open("/dev/ttymxc1", O_RDWR | O_NOCTTY);  /* the node bus */
    for (;;) {
        FILE *f = fopen("/data/count", "w");
        if (f) { fprintf(f, "%ld\n", ++i); fclose(f); }
        if (t >= 0) { if (write(t, ".", 1) < 0) {} }
        usleep(200000);
    }
    return 0;
}
EOF
if ! arm-linux-gnueabihf-gcc -O0 -static -o "$WORK/game" "$WORK/stub.c" 2>/dev/null; then
    echo "savetest: could not build the static ARM stub (arm-linux-gnueabihf-gcc?)"; exit 2
fi

# Install it as a rootfs title so run_game.sh's ordinary PAD_GAME path runs it
# (no card, no PAD_GAME_DIR - so no external bind for the title, keeping this
# test to the /dev + pty externals). game/conagent/data are what run_game.sh
# symlinks; a data dir is enough for the stub.
TITLE=$R/games/savetest_stub
mkdir -p "$TITLE"
cp "$WORK/game" "$TITLE/game"
: > "$TITLE/conagent"
mkdir -p "$TITLE/data"

cleanup() {
    pkill -9 -x game 2>/dev/null
    pkill -9 -f 'nodebus.py' 2>/dev/null
    [ -s "$DUMP/restored.pid" ] && kill -9 "$(cat "$DUMP/restored.pid")" 2>/dev/null
    rm -rf "$TITLE"
}
trap cleanup EXIT

# --- boot the stub through the REAL run_game.sh, PAD_PIVOT on ------------
echo "=== booting the stub via run_game.sh PAD_PIVOT=1"
PAD_PIVOT=1 PAD_GAME=savetest_stub bash "$RIG/run_game.sh" \
    >"$WORK/boot.log" 2>&1 &
for _ in $(seq 1 100); do
    PID=$(pgrep -x game | head -1); [ -n "$PID" ] && break; sleep 0.1
done
if [ -z "${PID:-}" ]; then
    echo "  FAIL  the stub never came up under PAD_PIVOT. boot.log:"
    sed 's/^/    /' "$WORK/boot.log" | tail -20
    exit 1
fi
# The stub counts to /data/count, which is the rootfs /data mount = $R/data on
# the host (NOT games/<title>/data - that is a separate symlink).
COUNT=$R/data/count
# run it a good while so a fresh restart could not reach the frozen value in
# the observation window (the ladder's margin rule).
sleep 12
V0=$(cat "$COUNT" 2>/dev/null)
echo "  stub up (pid $PID), counter at $V0"
[ -n "$V0" ] || { echo "  FAIL  stub wrote no counter (looked at $COUNT)"; exit 1; }

# --- SAVE ----------------------------------------------------------------
echo "=== savestate (leave-running)"
bash "$RIG/savestate.sh" "$DUMP" "$PID" || { echo "  FAIL  savestate failed"; exit 1; }

# the guest kept running (leave-running); kill it so the restore is not
# confused with the original, and freeze the value it reached.
sleep 1
kill -9 "$PID" 2>/dev/null
pkill -9 -f 'nodebus.py' 2>/dev/null
sleep 1
VF=$(cat "$COUNT" 2>/dev/null)
sleep 1
VF2=$(cat "$COUNT" 2>/dev/null)
[ -n "$VF" ] || { echo "  FAIL  no counter at $COUNT after kill"; exit 1; }
[ "$VF" = "$VF2" ] || { echo "  FAIL  counter still moving after kill ($VF->$VF2)"; exit 1; }
echo "  original dead, counter frozen at $VF"

# --- RESTORE -------------------------------------------------------------
echo "=== restorestate"
if ! bash "$RIG/restorestate.sh" "$DUMP"; then
    echo "  FAIL  restorestate failed"; exit 1
fi
sleep 3
V4=$(cat "$COUNT" 2>/dev/null)
sleep 1
V5=$(cat "$COUNT" 2>/dev/null)

CEIL=$((VF < 25 ? 25 : VF))   # a fresh restart in ~4s reaches ~25
echo "  after restore: $V4 -> $V5 (frozen was $VF)"
if [ -z "$V4" ] || [ "$V4" = "$V5" ]; then
    echo "  FAIL  restored guest is not advancing"; exit 1
fi
if [ "$V4" -le "$VF" ] 2>/dev/null; then
    echo "  FAIL  counter RESTARTED ($VF -> $V4) - a new process, not a restore"; exit 1
fi

echo
echo "  PASS  the stub RESUMED across save/restore: $VF (frozen) -> $V4 -> $V5"
echo "        run_game.sh PAD_PIVOT + savestate.sh + restorestate.sh work end to end"
