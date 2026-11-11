#!/bin/bash
# s3build.sh - build the Spike 3 shims and their own host renderer (PAD-1090).
#
#   bash s3build.sh [OUT]          # default $PAD_S3_HOME/build (/var/lib/pad-s3)
#
# Guest (aarch64, xgcc.sh, -nostdlib against the CARD's own libc - any card's
# rootfs in the store will do; they are one OS build):
#   libGLESv2.so.2   s3gl.c  (#includes ../spike2_emu/glbridge.c)
#   libEGL.so.1      s3egl.c
#   s3kms.so         s3kms.c (LD_PRELOAD: fake KMS + GBM)
#   s3alsa.so        s3alsa.c (LD_PRELOAD: the sound cards, paced and muted)
#   s3dev.so         s3dev.c (LD_PRELOAD: the SPI chain and amp bus, in the game)
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
OUT=${1:-${PAD_S3_BUILD:-${PAD_S3_HOME:-/var/lib/pad-s3}/build}}
mkdir -p "$OUT"
CC=$(bash "$S/xgcc.sh")
STORE=${PAD_SPIKE3_STORE:-$(python3 "$S/s3store.py" where)}
ROOTFS=$(ls -d "$STORE"/cards/*/rootfs 2>/dev/null | head -1)
[ -n "$ROOTFS" ] || { echo "s3build: no card in the Spike 3 store to link against (s3store.py build)" >&2; exit 1; }
LIBC=$ROOTFS/lib

# the video ring's slot: Spike 3 clips run to 1940x1100 (padvid.h; s3vidhost.py matches)
# and 16 slots a stream, not 4: the game keeps several decoded frames queued
# ahead of display (a V4L2 decoder has a deep pool), and with 4 it held every
# slot, the host could not write the next frame and send_packet went "busy"
VIDMAX="-DPADVID_MAX_W=2048 -DPADVID_MAX_H=1152 -DPADVID_SLOTS=16"
# GL programs: Godot 4 builds well past the Spike 2 bridge's 128 (glbridge.c/padglhost.c must agree)
GLMAX="-DMAXPROG=1024"
CF="-std=gnu17 -fno-stack-protector -shared -fPIC -O2 -Wall -Werror=implicit-function-declaration"
"$CC" $CF $GLMAX -nostdlib -I"$S2" -Wl,-soname,libGLESv2.so.2 -o "$OUT/libGLESv2.so.2" \
    "$S/s3gl.c" -L"$LIBC" -l:libc.so.6
"$CC" $CF -nostdlib -Wl,-soname,libEGL.so.1 -o "$OUT/libEGL.so.1" \
    "$S/s3egl.c" -L"$LIBC" -l:libc.so.6 "$OUT/libGLESv2.so.2"
"$CC" $CF -Wl,-soname,s3kms.so -o "$OUT/s3kms.so" "$S/s3kms.c" -ldl -lpthread
"$CC" $CF -Wl,-soname,s3alsa.so -o "$OUT/s3alsa.so" "$S/s3alsa.c"
"$CC" $CF -Wl,-soname,s3dev.so -o "$OUT/s3dev.so" "$S/s3dev.c" -ldl
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
# s3spid: only the old CUSE path (PAD_S3_DEV=0) uses it, so no fuse3 = no s3spid
if pkg-config --exists fuse3 2>/dev/null; then
    gcc -std=gnu17 -O2 -Wall -o "$OUT/s3spid" "$S/s3spid.c" $(pkg-config --cflags --libs fuse3)
fi

gcc -std=gnu17 -O2 -Wall -Werror=implicit-function-declaration $VIDMAX $GLMAX -I"$S2" \
    -o "$OUT/padglhost" "$S2/padglhost.c" -l:libEGL.so.1 -l:libX11.so.6

for f in libGLESv2.so.2 libEGL.so.1 s3kms.so s3alsa.so s3dev.so s3vid.so s3spid padglhost; do
    [ -e "$OUT/$f" ] || continue
    printf 's3build: %-15s %8d bytes\n' "$f" "$(stat -c%s "$OUT/$f")"
done
