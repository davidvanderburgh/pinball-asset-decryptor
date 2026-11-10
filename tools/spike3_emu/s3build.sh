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
#   s3alsa.so        s3alsa.c (LD_PRELOAD: the sound cards, paced and muted)
#   s3vid.so         s3vid.c  (LD_PRELOAD: video decoded on the host, s3vidhost.py)
# Host (x86-64): s3spid (s3spid.c, the CUSE stand-in for the CPU board's SPI
# I/O chain, s3run.sh --bus; needs libfuse3-dev), and padglhost from
# ../spike2_emu/padglhost.c, built HERE rather
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

# the video ring's slot: Spike 3 clips run to 1940x1100 (padvid.h; s3vidhost.py matches)
VIDMAX="-DPADVID_MAX_W=2048 -DPADVID_MAX_H=1152"
CF="-std=gnu17 -fno-stack-protector -shared -fPIC -O2 -Wall -Werror=implicit-function-declaration"
"$CC" $CF -nostdlib -I"$S2" -Wl,-soname,libGLESv2.so.2 -o "$OUT/libGLESv2.so.2" \
    "$S/s3gl.c" -L"$LIBC" -l:libc.so.6
"$CC" $CF -nostdlib -Wl,-soname,libEGL.so.1 -o "$OUT/libEGL.so.1" \
    "$S/s3egl.c" -L"$LIBC" -l:libc.so.6 "$OUT/libGLESv2.so.2"
"$CC" $CF -Wl,-soname,s3kms.so -o "$OUT/s3kms.so" "$S/s3kms.c" -ldl -lpthread
"$CC" $CF -Wl,-soname,s3alsa.so -o "$OUT/s3alsa.so" "$S/s3alsa.c"
# s3vid.so builds against the card's own FFmpeg (5.1.6-rpi: libavcodec
# 59.37.100) - its AVFrame/AVCodecContext layouts - so the headers of that
# exact release, fetched once beside the build
FFD=$(dirname "$OUT")/ffmpeg
FFINC=$FFD/inc/ffmpeg-5.1.6
if [ ! -e "$FFINC/libavutil/avconfig.h" ]; then
    mkdir -p "$FFD/inc"
    [ -f "$FFD/ffmpeg-5.1.6.tar.xz" ] || curl -sSL -o "$FFD/ffmpeg-5.1.6.tar.xz" https://ffmpeg.org/releases/ffmpeg-5.1.6.tar.xz
    tar -xJf "$FFD/ffmpeg-5.1.6.tar.xz" -C "$FFD/inc" --wildcards 'ffmpeg-5.1.6/libavutil/*.h' 'ffmpeg-5.1.6/libavcodec/*.h'
    printf '#ifndef AVUTIL_AVCONFIG_H
#define AVUTIL_AVCONFIG_H
#define AV_HAVE_BIG_ENDIAN 0
#define AV_HAVE_FAST_UNALIGNED 1
#endif
' > "$FFINC/libavutil/avconfig.h"
fi
"$CC" $CF $VIDMAX -I"$FFINC" -I"$S2" -Wl,-soname,s3vid.so -o "$OUT/s3vid.so" "$S/s3vid.c" -ldl -lpthread
gcc -std=gnu17 -O2 -Wall -o "$OUT/s3spid" "$S/s3spid.c" $(pkg-config --cflags --libs fuse3)

gcc -std=gnu17 -O2 -Wall -Werror=implicit-function-declaration $VIDMAX -I"$S2" \
    -o "$OUT/padglhost" "$S2/padglhost.c" -l:libEGL.so.1 -l:libX11.so.6

for f in libGLESv2.so.2 libEGL.so.1 s3kms.so s3alsa.so s3vid.so s3spid padglhost; do
    printf 's3build: %-15s %8d bytes\n' "$f" "$(stat -c%s "$OUT/$f")"
done
