#!/bin/bash
# Build a patched qemu-user (arm) for the Spike 1 rig: generic ioctl
# passthrough so CUSE device models receive the game's device ioctls
# (see patch_qemu.py).  Run in WSL/Linux.  Build deps (Debian/Ubuntu, as root):
#   apt-get install -y meson ninja-build libglib2.0-dev pkg-config flex bison gcc
# Output: $OUT/qemu-arm  (static; point S1_QEMU at it).
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
VER="${QEMU_VER:-8.2.2}"
WORK="${QEMU_WORK:-$HOME/qemubuild}"
OUT="${QEMU_OUT:-$WORK}"
mkdir -p "$WORK"; cd "$WORK"

if [ ! -d "qemu-$VER" ]; then
  echo "fetching qemu-$VER ..."
  if command -v wget >/dev/null; then wget -q "https://download.qemu.org/qemu-$VER.tar.xz"
  else curl -sL -o "qemu-$VER.tar.xz" "https://download.qemu.org/qemu-$VER.tar.xz"; fi
  tar xf "qemu-$VER.tar.xz"
fi

python3 "$HERE/patch_qemu.py" "qemu-$VER/linux-user/syscall.c"
python3 "$HERE/patch_qemu.py" "qemu-$VER/linux-user/signal.c"

cd "qemu-$VER"
if [ ! -f build/build.ninja ]; then
  ./configure --target-list=arm-linux-user --static --disable-system \
    --disable-tools --disable-docs --disable-guest-agent \
    --without-default-features --enable-linux-user
fi
ninja -C build qemu-arm
cp -f build/qemu-arm "$OUT/qemu-arm"
echo "built patched qemu -> $OUT/qemu-arm"
