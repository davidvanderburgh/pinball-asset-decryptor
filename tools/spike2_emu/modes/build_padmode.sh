#!/bin/bash
# Build padmode.so - item 125's Phase 0 probe (see padmode.c).
# Same recipe as build_padtrace.sh: armhf, -nostdlib, linked against the card
# rootfs's own libc so its glibc-2.21 symbol versions match what the game loads.
#
# It builds into the STAGE, never into the rootfs: copying it to $ROOT/lib is a
# rootfs mutation and belongs under the rig lock, with the run it is for.
#   modes/build_padmode.sh [out]     default $PAD_STAGE/padmode.so
#   PAD_MODE_ELF=<game ELF>          default $ROOT/games/godzilla_pro/game
. "$(dirname "$0")/../padpath.sh"
set -e
ELF=${PAD_MODE_ELF:-$ROOT/games/godzilla_pro/game}
pad_stage || exit 1
OUT="${1:-$PAD_STAGE/padmode.so}"
python3 "$RIG/modes/gen_sites.py" "$ELF" > "$PAD_STAGE/padmode_sites.h"
cp "$RIG/modes/padmode.c" "$PAD_STAGE/padmode.c"
arm-linux-gnueabihf-gcc -std=gnu17 -marm -fno-stack-protector -shared -fPIC -O2 -nostdlib \
  -Wall -Werror=implicit-function-declaration -I"$PAD_STAGE" \
  -Wl,-soname,padmode.so -o "$OUT" \
  "$PAD_STAGE/padmode.c" \
  -L"$ROOT/lib" -l:libc.so.6 -lgcc
echo "built ok: $(stat -c %s "$OUT") bytes -> $OUT"
echo "=== NEEDED (must all resolve on the card's glibc 2.21) ==="
arm-linux-gnueabihf-objdump -p "$OUT" | grep -aE "NEEDED|GLIBC_2\.[0-9]+" | sort -u
