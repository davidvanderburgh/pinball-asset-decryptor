#!/bin/bash
# s3_stublibs.sh CC OUTDIR OBJ... - the four libraries the Spike 3 menu links
# against (PAD-1263), as stubs: libEGL.so.1, libGLESv2.so.2, libgbm.so.1 and
# libdrm.so.2, each exporting the symbols the objects import from it and
# nothing else. The menu is LINKED against these and RUNS against the card's
# own (Mesa, libdrm - or PAD's emulator shims), so a build needs no card. The
# names and the unversioned symbols are all the dynamic linker matches on:
# none of the four libraries versions its symbols. `make check S3ROOT=<card
# rootfs>` (test/check_elf_s3.sh) proves every import resolves in a card's real
# libraries.
set -eu
CC=$1; OUT=$2; shift 2
mkdir -p "$OUT"
NM=${NM:-$(dirname "$(readlink -f "$(command -v "${CC%% *}" 2>/dev/null || echo "$CC")")")/aarch64-linux-gnu-nm}
[ -x "$NM" ] || NM=$(command -v aarch64-linux-gnu-nm || command -v nm)
syms=$("$NM" -u "$@" | awk '{print $NF}' | sort -u)
lib() {   # lib SONAME REGEX
    local so=$1 re=$2 c=$OUT/${1%%.so*}.c
    : > "$c"
    for s in $syms; do
        if [[ $s =~ $re ]]; then echo "void $s(void) {}" >> "$c"; fi
    done
    $CC -shared -fPIC -nostdlib -Wl,-soname,"$so" -o "$OUT/$so" "$c"
}
lib libEGL.so.1    '^egl[A-Z]'
lib libGLESv2.so.2 '^gl[A-Z]'
lib libgbm.so.1    '^gbm_'
lib libdrm.so.2    '^drm[A-Z]'
echo "stub libraries in $OUT"
