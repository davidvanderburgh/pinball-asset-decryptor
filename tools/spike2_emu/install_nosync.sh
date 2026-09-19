#!/bin/bash
# install_nosync.sh [ROOT] - put pad_nosync.so (a no-op sync) in the guest rootfs and preload it for
# every guest process through $ROOT/etc/ld.so.preload. Idempotent. Take the rig lock first.
#
# WHY (2026-09-17). Godzilla's NVRAM thread calls libc sync() after writing a new NVM generation (a
# changed adjustment default, a wiped NVRAM, Guided Setup, an operator-menu save). qemu-user hands it
# to the host kernel, where sync(2) is GLOBAL: under WSL2 it also flushes the WSLg virtiofs superblock
# and never returns. The guest thread sits in D state, SIGKILL cannot finish it, alive.sh counts the
# dead guest for ever, and only `wsl --shutdown` clears the rig. The no-op interposes on the game's
# sync@GLIBC_2.4 (proven: LD_DEBUG=bindings binds busybox's sync to it, `busybox sync` returns at
# once, and a Godzilla Pro 1.15 boot maps it and renders with 0 segv). syncfs() is left alone.
#
# Build (PAD-Runtime distro has the compiler): see pad_nosync.c's header.
set -eu
ROOT=${1:-${PAD_ROOT:-$HOME/spike2root}}
HERE=$(cd "$(dirname "$0")" && pwd)
SO=$HERE/pad_nosync.so
if [ ! -f "$SO" ] || [ "$HERE/pad_nosync.c" -nt "$SO" ]; then
    arm-linux-gnueabihf-gcc -std=gnu17 -marm -mfloat-abi=hard -fno-stack-protector -fPIC -shared -O2 \
        -nostdlib -Wl,-soname,pad_nosync.so -o "$SO" "$HERE/pad_nosync.c"
fi
install -m 0755 "$SO" "$ROOT/lib/pad_nosync.so"
touch "$ROOT/etc/ld.so.preload"
grep -qx "/lib/pad_nosync.so" "$ROOT/etc/ld.so.preload" || echo "/lib/pad_nosync.so" >> "$ROOT/etc/ld.so.preload"
echo "pad_nosync.so installed in $ROOT/lib and preloaded ($ROOT/etc/ld.so.preload)"
