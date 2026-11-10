#!/bin/bash
# s3build.sh - build the Spike 3 shims and their own host renderer (PAD-1090).
#
#   bash s3build.sh [OUT]          # default ~/.pad-s3/build
#
# Guest (aarch64, xgcc.sh, -nostdlib against the CARD's own libc - any card's
# rootfs in the store will do; they are one OS build):
#   libGLESv2.so.2   s3gl.c  (#includes ../spike2_emu/glbridge.c)
#   libEGL.so.1      s3egl.c
#   s3kms.so         s3kms.c (LD_PRELOAD: fake KMS + GBM)
# Host (x86-64): padglhost from ../spike2_emu/padglhost.c, built HERE rather
# than over the Spike 2 rig's own copy, so a Spike 3 bring-up never swaps the
# renderer under a Spike 2 run another ticket has going.
#
# s3run.sh --bridge puts the guest three into the slot's overlay (the store is
# never written) and starts this padglhost against the slot's ring.
set -eu
S=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
S2=$S/../spike2_emu
OUT=${1:-$HOME/.pad-s3/build}
mkdir -p "$OUT"
CC=$(bash "$S/xgcc.sh")
STORE=${PAD_SPIKE3_STORE:-/mnt/wsl/cards/spike3}
[ -d "$STORE/cards" ] || STORE=$HOME/cardcache/spike3
ROOTFS=$(ls -d "$STORE"/cards/*/rootfs 2>/dev/null | head -1)
[ -n "$ROOTFS" ] || { echo "s3build: no card in the Spike 3 store to link against (s3store.py build)" >&2; exit 1; }
LIBC=$ROOTFS/lib

CF="-std=gnu17 -fno-stack-protector -shared -fPIC -O2 -Wall -Werror=implicit-function-declaration"
"$CC" $CF -nostdlib -I"$S2" -Wl,-soname,libGLESv2.so.2 -o "$OUT/libGLESv2.so.2" \
    "$S/s3gl.c" -L"$LIBC" -l:libc.so.6
"$CC" $CF -nostdlib -Wl,-soname,libEGL.so.1 -o "$OUT/libEGL.so.1" \
    "$S/s3egl.c" -L"$LIBC" -l:libc.so.6 "$OUT/libGLESv2.so.2"
"$CC" $CF -Wl,-soname,s3kms.so -o "$OUT/s3kms.so" "$S/s3kms.c" -ldl -lpthread

gcc -std=gnu17 -O2 -Wall -Werror=implicit-function-declaration -I"$S2" \
    -o "$OUT/padglhost" "$S2/padglhost.c" -l:libEGL.so.1 -l:libX11.so.6

for f in libGLESv2.so.2 libEGL.so.1 s3kms.so padglhost; do
    printf 's3build: %-15s %8d bytes\n' "$f" "$(stat -c%s "$OUT/$f")"
done
