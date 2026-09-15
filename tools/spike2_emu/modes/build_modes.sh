#!/bin/bash
# Build item 125's preloaded objects: padmode.so (the probe) and mode.so (KAIJU RUSH).
# Same recipe as build_padtrace.sh: armhf, -nostdlib, linked against the card
# rootfs's own libc so its glibc-2.21 symbol versions match what the game loads.
#
# It builds into the STAGE, never into the rootfs: copying to $ROOT/lib is a rootfs
# mutation and belongs under the rig lock, with the run it is for.
#   modes/build_modes.sh              both, into $PAD_STAGE
#   PAD_MODE_ELF=<game ELF>           default $ROOT/games/godzilla_pro/game
. "$(dirname "$0")/../padpath.sh"
set -e
ELF=${PAD_MODE_ELF:-$ROOT/games/godzilla_pro/game}
pad_stage || exit 1
python3 "$RIG/modes/gen_sites.py" "$ELF" > "$PAD_STAGE/padmode_sites.h"
cp "$RIG/modes/hook.h" "$RIG/modes/padmode.c" "$RIG/modes/mode.c" "$PAD_STAGE/"
for so in padmode mode; do
  arm-linux-gnueabihf-gcc -std=gnu17 -marm -fno-stack-protector -shared -fPIC -O2 -nostdlib \
    -Wall -Werror=implicit-function-declaration -I"$PAD_STAGE" \
    -Wl,-soname,$so.so -o "$PAD_STAGE/$so.so" \
    "$PAD_STAGE/$so.c" \
    -L"$ROOT/lib" -l:libc.so.6 -lgcc
  echo "built ok: $(stat -c %s "$PAD_STAGE/$so.so") bytes -> $PAD_STAGE/$so.so"
  arm-linux-gnueabihf-objdump -p "$PAD_STAGE/$so.so" | grep -aE "NEEDED|GLIBC_2\.[0-9]+" | sort -u
done
