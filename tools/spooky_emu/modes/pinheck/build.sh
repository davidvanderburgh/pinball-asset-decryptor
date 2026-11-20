#!/bin/bash
# build.sh - the pinHeck mode runtime, one per game build (PAD-1422).
# Run in WSL (Ubuntu): needs gcc-mipsel-linux-gnu.  Writes prebuilt/padheck_<STEM>.bin, the
# runtime linked at that build's free flash against its hook table (hooks.py), and .map beside it.
#   bash build.sh [STEM ...]      (default: every build in hooks.py)
set -euo pipefail
cd "$(dirname "$0")"
CC=${CC:-mipsel-linux-gnu-gcc}
OBJCOPY=${OBJCOPY:-mipsel-linux-gnu-objcopy}
STEMS=("$@")
if [ ${#STEMS[@]} -eq 0 ]; then
    mapfile -t STEMS < <(python3 -c 'import hooks; print("\n".join(sorted(hooks.HOOKS)))')
fi
mkdir -p prebuilt
for stem in "${STEMS[@]}"; do
    defs=$(python3 - "$stem" <<'PY'
import sys, hooks
t = hooks.HOOKS[sys.argv[1]]
out = ["--defsym=PAD_FLASH=0x%X" % t["free_flash"], "--defsym=PAD_RAM_AT=0x%X" % t["ram"][0]]
for k in hooks.LINK_KEYS:
    if k not in ("free_flash",) and t[k] is not None:      # None: not in this game (text_show on AMH)
        out.append("--defsym=GAME_%s=0x%X" % (k, t[k]))
flags = ["-DTEXT_ABI_AMH"] if t.get("text_abi") == "amh" else []
print(" ".join(flags + ["-Wl," + o for o in out]))
PY
)
    $CC -march=mips32r2 -EL -Os -G0 -mno-abicalls -fno-pic -mno-gpopt -msoft-float \
        -ffreestanding -fno-builtin -fno-tree-loop-distribute-patterns -fno-asynchronous-unwind-tables \
        -nostdlib -nostartfiles -Wl,--build-id=none -Wall -Werror -T padheck.ld $defs \
        -Wl,-Map=prebuilt/padheck_$stem.map -o /tmp/padheck_$stem.elf padheck.c
    $OBJCOPY -O binary /tmp/padheck_$stem.elf prebuilt/padheck_$stem.bin
    echo "padheck_$stem.bin: $(stat -c %s prebuilt/padheck_$stem.bin) bytes"
done
