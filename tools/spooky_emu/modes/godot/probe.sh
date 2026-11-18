#!/bin/bash
# probe.sh <update .looney> - PAD-1387 proof: boot Looney Tunes on this slot's
# rig (hidden, muted) with pad_modes.gd injected as an extra autoload through
# override.cfg beside main.x86_64, play a ball, hit the spinner, show the log.
# Run as root in PAD-Runtime with PAD_SLOT=N PAD_LABEL=... PAD_HIDDEN=1 after
# taking the slot with riglock.  The update and the stock cache are only read.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
T=$(cd "$HERE/../.." && pwd)            # tools/spooky_emu
. "$T/spkpath.sh"
UPD=${1:?usage: probe.sh <update .looney>}
export PAD_VISIBLE=0 PAD_AUDIO=0
mkdir -p "$SPK_CACHE"
bash "$T/prepare.sh" "$UPD" > "$SPK_ROOT/prepare$SPK_SLOT.out" || exit 1
BUILD=$(sed -n 's/^build=//p' "$SPK_ROOT/prepare$SPK_SLOT.out" | tail -1)
[ -n "$BUILD" ] || exit 1
# A build of our own next to the cache: the stock one hard-linked, plus
# override.cfg and pad/ (the files an installable update would carry).
PB=$SPK_ROOT/padmodes$SPK_SLOT/$BUILD
rm -rf "$SPK_ROOT/padmodes$SPK_SLOT"; mkdir -p "$(dirname "$PB")"
cp -al "$SPK_CACHE/$BUILD" "$PB"
rm -f "$PB/used"
mkdir -p "$PB/pad"
cp "$HERE/pad_modes.gd" "$HERE/pad_probe_mode.gd" "$PB/pad/"
printf '[autoload]\n\nPadModes="*/game/code/uptest/pad/pad_modes.gd"\n' > "$PB/override.cfg"
chmod -R a+rX "$PB"
echo "build: $PB"
bash "$T/run_game.sh" "$PB" || { echo "run_game failed"; tail -30 "$SPK_RIG/player.log"; exit 1; }
LOG=$SPK_RIG/tmp/pad_modes.log
sleep 5
echo "--- after attract"; cat "$LOG" 2>/dev/null || echo "(no $LOG)"
cd "$T"
python3 sw.py coin; sleep 1; python3 sw.py start; sleep 8
python3 sw.py plunge; sleep 4
for i in 1 2 3; do python3 sw.py spinner pulse 150; sleep 1; done
sleep 3
echo "--- after play"; cat "$LOG" 2>/dev/null
echo "--- player.log tail"; tail -n 15 "$SPK_RIG/player.log"
bash "$T/shot.sh" /mnt/c/tmp/PAD-1387/godot/probe.png >/dev/null 2>&1 && echo "shot: C:\\tmp\\PAD-1387\\godot\\probe.png"
[ "${KEEP:-0}" = 1 ] || bash "$T/killgame.sh"
