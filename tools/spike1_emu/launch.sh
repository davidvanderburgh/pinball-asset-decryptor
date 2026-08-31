#!/bin/bash
# Spike 1 emulation launcher — run the static ARM game binary under qemu-user
# in an unprivileged user+mount+pid namespace assembled from the card's OS
# rootfs + game dir.  No root, no LD_PRELOAD (the game is statically linked).
#
# Env:
#   S1_ROOT     OS rootfs dir            (from build_rootfs.py)   [required]
#   S1_GAME     game dir (image.bin, ...) (from build_rootfs.py)  [required]
#   S1_CPUINFO  fake /proc/cpuinfo path  (default: this dir's cpuinfo)
#   S1_STRACE   1 = guest syscall trace via qemu -strace          (default 0)
#
# Boots the real firmware to hardware-initialization; it then needs a device
# model for the board peripherals (see README + docs/architecture/
# spike1_emulation.md).  Stand-in /dev nodes here are /dev/null (open OK,
# writes discarded, reads EOF) so the boot progresses to the device stage.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
: "${S1_CPUINFO:=$HERE/cpuinfo}"
: "${S1_STRACE:=0}"

if [ "${1:-}" != "--inner" ]; then
  [ -n "${S1_ROOT:-}" ] && [ -n "${S1_GAME:-}" ] || {
    echo "set S1_ROOT and S1_GAME (see build_rootfs.py)"; exit 2; }
  export S1_ROOT S1_GAME S1_CPUINFO S1_STRACE
  exec unshare -r -m -p -f "$0" --inner
fi

# ---- inner: root in a fresh user/mount/pid namespace ----
R="$S1_ROOT"
GAME_NAME="$(cat "$S1_GAME/.game_name" 2>/dev/null | tr -d '[:space:]')"
: "${GAME_NAME:=GAME}"

mount --make-rprivate / 2>/dev/null || true
mount -t proc proc "$R/proc" 2>/dev/null || true
mount --bind "$S1_CPUINFO" "$R/proc/cpuinfo" 2>/dev/null || true
mount -t sysfs sysfs "$R/sys" 2>/dev/null || true

mkdir -p "$R/data" "$R/dump/log" "$R/games/$GAME_NAME"
chmod -R 0777 "$R/data" "$R/dump" 2>/dev/null || true
mount --bind "$S1_GAME" "$R/games/$GAME_NAME"
ln -sf "/games/$GAME_NAME/game" "$R/games/game" 2>/dev/null || true

# real char devices we can borrow
for d in null zero full random urandom tty; do
  t="$R/dev/$d"; [ -e "$t" ] || : > "$t"
  mount --bind "/dev/$d" "$t" 2>/dev/null || true
done
# Stern peripherals -> /dev/null stand-ins until the device model lands
for d in dmd i2s amp adc gpio spi0 spi1 i2c-0 i2c-1 i2c-2 ttyS0 ttyS3 ttyS4 \
         rtc backlight egd watchdog mem; do
  t="$R/dev/$d"; [ -e "$t" ] || : > "$t"
  mount --bind /dev/null "$t" 2>/dev/null || true
done

if [ "$S1_STRACE" = "1" ]; then
  # needs an x86-64 qemu reachable inside the chroot (runs natively there)
  [ -x "$R/usr/bin/qemu-arm-static" ] || \
    cp /usr/bin/qemu-arm-static "$R/usr/bin/qemu-arm-static" 2>/dev/null || true
  exec chroot "$R" /bin/sh -c "cd /games/$GAME_NAME && exec qemu-arm-static -strace ./game"
else
  exec chroot "$R" /bin/sh -c "cd /games/$GAME_NAME && exec ./game"
fi
