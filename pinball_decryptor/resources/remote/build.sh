#!/bin/sh
# Build pad-buttons.so, the remote-buttons shim for a Spike 2 machine (PAD-1467), and prove its logic under qemu.
#
#   sh build.sh            (in a Linux with arm-linux-gnueabihf-gcc; qemu-user for the test)
#
# ARM hard-float, ARM mode, no library at all (-nostdlib): the machine's game runs glibc 2.21 and nothing here
# depends on it.  The test program is the same source with its files in the current folder.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
W=${TMPDIR:-/var/tmp}/pad-buttons-build
mkdir -p "$W"
cp "$HERE/pad-buttons.c" "$HERE/t_buttons.c" "$W/"
cd "$W"
FLAGS="-marm -march=armv7-a+fp -O2 -fno-builtin -fomit-frame-pointer -Wall -Wextra"
arm-linux-gnueabihf-gcc $FLAGS -fPIC -shared -nostdlib -Wl,--build-id=none -o pad-buttons.so pad-buttons.c
arm-linux-gnueabihf-readelf -d pad-buttons.so | grep NEEDED && { echo "it must need no library"; exit 1; } || echo "needs no library"
arm-linux-gnueabihf-nm -D --undefined-only pad-buttons.so
arm-linux-gnueabihf-gcc $FLAGS -static -DPADBTN_TEST -DCTL='"./ctl"' -DSTATE='"./state"' -Dioctl=shim_ioctl \
    -o t_buttons t_buttons.c pad-buttons.c
rm -f ctl state
if command -v qemu-arm >/dev/null 2>&1; then qemu-arm ./t_buttons
elif command -v qemu-arm-static >/dev/null 2>&1; then qemu-arm-static ./t_buttons
else echo "NO QEMU: the test was not run"; exit 1; fi
cp pad-buttons.so "$HERE/pad-buttons.so"
sha256sum "$HERE/pad-buttons.so"
