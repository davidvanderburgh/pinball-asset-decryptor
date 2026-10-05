#!/bin/bash
# check_elf_bof.sh BIN [BIN...] - what a Barrels of Fun machine needs of bofselect and
# paddelta (PAD-342): x86-64 ELF executables that are STATIC - no interpreter, no NEEDED
# library - because the machine is an Arch Linux PC with whatever glibc its last system
# image carried, and nothing of it is read at build time.
set -e
for BIN in "$@"; do
    [ -f "$BIN" ] || { echo "check_elf_bof: no $BIN"; exit 1; }
    h=$(readelf -h "$BIN")
    echo "$h" | grep -q 'Machine:.*X86-64' || { echo "check_elf_bof: FAIL $BIN is not x86-64"; exit 1; }
    echo "$h" | grep -q 'Type:.*EXEC' || { echo "check_elf_bof: FAIL $BIN is not an executable"; exit 1; }
    if readelf -l "$BIN" | grep -q INTERP; then
        echo "check_elf_bof: FAIL $BIN asks for a program interpreter (it must be static)"; exit 1
    fi
    if readelf -d "$BIN" 2>/dev/null | grep -q NEEDED; then
        echo "check_elf_bof: FAIL $BIN needs shared libraries:"; readelf -d "$BIN" | grep NEEDED; exit 1
    fi
    echo "check_elf_bof: OK $BIN (static x86-64)"
done
