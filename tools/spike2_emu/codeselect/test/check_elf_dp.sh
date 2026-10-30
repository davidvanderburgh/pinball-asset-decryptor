#!/bin/bash
# check_elf_dp.sh DPSELECT DPPROCSW - what a Dutch Pinball machine (The Big Lebowski, PAD-853)
# needs of the boot menu's two programs.  The machine is an Arch Linux PC with whatever glibc
# its last system image carried, and nothing of it is read at build time:
#
#   dpselect   an x86-64 executable that is STATIC - no interpreter, no NEEDED library
#   dpprocsw   an x86-64 executable needing ONLY libpinproc.so.2.0 (the game's own, found
#              through LD_LIBRARY_PATH at run time) and libc.so.6, and no glibc symbol
#              version newer than GLIBC_2.2.5 (-nostartfiles: no __libc_start_main@2.34)
set -e
SEL=$1; SW=$2
for BIN in "$SEL" "$SW"; do
    [ -f "$BIN" ] || { echo "check_elf_dp: no $BIN"; exit 1; }
    h=$(readelf -h "$BIN")
    echo "$h" | grep -q 'Machine:.*X86-64' || { echo "check_elf_dp: FAIL $BIN is not x86-64"; exit 1; }
    echo "$h" | grep -q 'Type:.*EXEC' || { echo "check_elf_dp: FAIL $BIN is not an executable"; exit 1; }
done
if readelf -l "$SEL" | grep -q INTERP || readelf -d "$SEL" 2>/dev/null | grep -q NEEDED; then
    echo "check_elf_dp: FAIL $SEL is not static"; exit 1
fi
echo "check_elf_dp: OK $SEL (static x86-64)"
need=$(readelf -d "$SW" | sed -n 's/.*NEEDED.*\[\(.*\)\]/\1/p' | sort | tr '\n' ' ')
if [ "$need" != "libc.so.6 libpinproc.so.2.0 " ]; then
    echo "check_elf_dp: FAIL $SW needs: $need(want libc.so.6 libpinproc.so.2.0)"; exit 1
fi
top=$(readelf -V "$SW" | grep -o 'GLIBC_[0-9.]*' | sort -uV | tail -1)
if [ "$top" != "GLIBC_2.2.5" ]; then
    echo "check_elf_dp: FAIL $SW asks for $top (the ceiling is GLIBC_2.2.5)"; exit 1
fi
echo "check_elf_dp: OK $SW (libpinproc.so.2.0 + libc.so.6, $top)"
