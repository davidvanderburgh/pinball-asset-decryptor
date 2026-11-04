#!/bin/bash
# check_elf_spk.sh SPKSELECT SPKSW - what a Spooky Pinball machine (PAD-980) needs of the
# boot menu's two programs: x86-64 executables that are STATIC - no interpreter, no NEEDED
# library - because the cabinets' Debian (11 on the AK3V/GK3 PCs, 12 on the newer) is
# whatever its restore image carried, and nothing of it is read at build time.
set -e
for BIN in "$@"; do
    [ -f "$BIN" ] || { echo "check_elf_spk: no $BIN"; exit 1; }
    h=$(readelf -h "$BIN")
    echo "$h" | grep -q 'Machine:.*X86-64' || { echo "check_elf_spk: FAIL $BIN is not x86-64"; exit 1; }
    echo "$h" | grep -q 'Type:.*EXEC' || { echo "check_elf_spk: FAIL $BIN is not an executable"; exit 1; }
    if readelf -l "$BIN" | grep -q INTERP || readelf -d "$BIN" 2>/dev/null | grep -q NEEDED; then
        echo "check_elf_spk: FAIL $BIN is not static"; exit 1
    fi
    echo "check_elf_spk: OK $BIN (static x86-64)"
done
