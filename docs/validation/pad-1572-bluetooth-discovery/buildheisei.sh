#!/bin/bash
# PAD-1572: the Heisei card's 14 code modes compiled with this branch's runtime (plus mode_file.c, as the card's own has)
set -eu
SDK=/mnt/c/Users/david/Documents/development/pad-triage/work/tickets/PAD-1572/tools/spike2_emu/modes/sdk
SRC="/mnt/c/Users/david/OneDrive/Desktop/HEISEI v1.99D + daveyvandy modes/modes"
W=$(mktemp -d); cp -r "$SRC"/*/ "$W"/ 2>/dev/null || true
find "$W" -name '*.c' -o -name '*.h' | while read -r f; do sed -i 's/\r$//' "$f"; done
cs=$(find "$W" -maxdepth 2 -name '*.c' | sort)
echo "$(echo "$cs" | wc -l) mode sources"
cd "$W"
bash "$SDK/build_mode.sh" -o /mnt/c/tmp/PAD-1572/heisei_new_mode.so "$SDK/mode_file.c" $cs 2>&1 | tail -3
