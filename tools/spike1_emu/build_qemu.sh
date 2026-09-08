#!/bin/bash
# Build a patched qemu-user (arm) for the Spike 1 rig: generic ioctl
# passthrough so CUSE device models receive the game's device ioctls
# (see patch_qemu.py).  Run in WSL/Linux.  Build deps are NOT listed here any
# more: prereqs.sh is the one list, it probes for them, and it names the ones
# THIS machine is missing in its own package manager's spelling.  (The list
# that used to sit here named meson, which qemu installs itself from a bundled
# wheel, and not python3-venv, without which it cannot - see prereqs.sh.)
# Output: $OUT/qemu-arm  (static; point S1_QEMU at it).
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/prereqs.sh"
s1_prereq_report qemu || exit 2
VER="${QEMU_VER:-8.2.2}"
WORK="${QEMU_WORK:-$HOME/qemubuild}"
OUT="${QEMU_OUT:-$WORK}"
mkdir -p "$WORK"; cd "$WORK"

#: THE SOURCE IS PINNED TOO, and it is the last link in the chain.  Everything
#: downstream of this script is verified by SHA-256 - the payload the app
#: installs, the image that bakes it in - but the tarball those are built FROM
#: was fetched over the wire and unpacked unchecked, so one changed or
#: substituted file on download.qemu.org would have flowed all the way to a
#: user's machine wearing our hashes.  qemu publishes no SHA512SUMS file
#: (only a detached .sig), so this is OUR verified value: the same digest on a
#: copy downloaded in October 2024 and on a fresh fetch on 2026-09-08.
QEMU_SHA512_8_2_2=dfd2e1305f9e51bfbc90a7738c69336d5f805481a626ea527b971bdfb6dbe6867e5df7461d48d1c22b79be2dc18e057ea9fa36ef593127cd8b262a5c33f1aa41

if [ ! -d "qemu-$VER" ]; then
  echo "fetching qemu-$VER ..."
  if command -v wget >/dev/null; then wget -q "https://download.qemu.org/qemu-$VER.tar.xz"
  else curl -sL -o "qemu-$VER.tar.xz" "https://download.qemu.org/qemu-$VER.tar.xz"; fi
  # Only 8.2.2 has a pinned digest here.  A QEMU_VER override is a developer
  # asking for a different source on purpose, and it is told that it is
  # unverified rather than quietly treated as if it were.
  if [ "$VER" = 8.2.2 ]; then
    GOT=$(sha512sum "qemu-$VER.tar.xz" | cut -d" " -f1)
    if [ "$GOT" != "$QEMU_SHA512_8_2_2" ]; then
      rm -f "qemu-$VER.tar.xz"
      echo "ERROR: the qemu $VER tarball is not the one this emulator is built" >&2
      echo "       from (its checksum does not match). Nothing was unpacked." >&2
      exit 1
    fi
    echo "qemu-$VER.tar.xz verified"
  else
    echo "WARNING: qemu $VER is not the pinned version; its source is unverified" >&2
  fi
  tar xf "qemu-$VER.tar.xz"
fi

python3 "$HERE/patch_qemu.py" "qemu-$VER/linux-user/syscall.c"
python3 "$HERE/patch_qemu.py" "qemu-$VER/linux-user/signal.c"

cd "qemu-$VER"
# --python: the interpreter that CAN make configure's private venv, which on a
# machine with several is not always the default one - a distro that splits
# ensurepip out has usually split it out of the newest interpreter only, and
# the older one beside it still builds this today.  prereqs.sh already refused
# to get here if none of them can.
if [ ! -f build/build.ninja ]; then
  # A build dir with no build.ninja is the WRECKAGE of a configure that died -
  # which is how every machine that hits a missing build tool is left, half a
  # python venv and all.  Clear it rather than configure on top of it, so that
  # installing the package the preflight named is the whole of the fix.
  rm -rf build
  ./configure --target-list=arm-linux-user --static --disable-system \
    --disable-tools --disable-docs --disable-guest-agent \
    --without-default-features --enable-linux-user \
    --python="$(s1_python)"
fi
ninja -C build qemu-arm
cp -f build/qemu-arm "$OUT/qemu-arm"
echo "built patched qemu -> $OUT/qemu-arm"
