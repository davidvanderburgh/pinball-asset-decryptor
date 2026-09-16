#!/bin/bash
# grow_mode_sound.sh [seconds] [src_idx] - stage a sound bank carrying a mode's OWN
# audio: one record appended to the title's image.bin, playable, naming nothing.
#
# Item 130. Desk work, no run - but it WRITES into the rootfs, so it is a rig action
# and belongs under the rig lock like any other. It never overwrites image.bin:
# the grown bank is staged beside it as image.grown.bin, and install_mode_sound.sh
# swaps them by RENAME (the stock file's inode has other links).
#
# Prints the appended record's 8-byte key, which is a mode file's `sound_key`.
. "$(dirname "$0")/../padpath.sh"
set -e
SECS=${1:-4.0}
SRC=${2:--1}
GAME_DIR=$ROOT/games/${PAD_GAME:-godzilla_pro}
REPO=$(cd "$RIG/../.." && pwd)
[ -f "$GAME_DIR/image.bin" ] || { echo "no sound bank at $GAME_DIR/image.bin" >&2; exit 1; }
[ -f "$GAME_DIR/game" ] || { echo "no game ELF at $GAME_DIR/game" >&2; exit 1; }
echo "repo   $REPO"
echo "title  $GAME_DIR"
echo "clip   ${SECS}s, source record ${SRC} (-1 = pick a mono one)"
exec python3 "$RIG/modes/grow_mode_sound.py" \
    "$REPO" "$GAME_DIR/game" "$GAME_DIR/image.bin" "$GAME_DIR/image.grown.bin" \
    "$SRC" "$SECS"
