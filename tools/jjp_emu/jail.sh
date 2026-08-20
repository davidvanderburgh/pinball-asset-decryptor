#!/bin/bash
# Build the writable jail the game runs in, WITHOUT ever writing to the image.
#
# overlayfs: the restored ext4 is the read-only LOWER, a tmpfs is the UPPER.
# Everything the game writes - and it writes a lot on first boot: it renames the
# host, renders all 123 operator-manual pages to PNG, renders the T&C pages -
# lands in RAM and evaporates.  The image can be re-run from a known state any
# number of times, and a bad run can never corrupt it.
#
# The upper is also a free instrument: `find $JJP_OVL/up -newer <stamp>` is an
# exact list of everything a run touched.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/padpath.sh"

[ "$(id -u)" = "0" ] || { echo "jail.sh: must run as root (wsl -u root)" >&2; exit 2; }
mountpoint -q "$JJP_ROOT" || { echo "jail.sh: $JJP_ROOT is not mounted; run mount.sh first" >&2; exit 3; }

mkdir -p "$JJP_JAIL"
mountpoint -q "$JJP_OVL" || { mkdir -p "$JJP_OVL"; mount -t tmpfs -o "size=$JJP_OVL_SIZE" tmpfs "$JJP_OVL"; }
mkdir -p "$JJP_OVL/up" "$JJP_OVL/work"
mountpoint -q "$JJP_JAIL" || mount -t overlay overlay \
    -o "lowerdir=$JJP_ROOT,upperdir=$JJP_OVL/up,workdir=$JJP_OVL/work" "$JJP_JAIL"

# The same bind list PAD's decrypt pipeline uses, plus /dev/bus/usb for the
# dongle and the two WSLg surfaces the game needs to draw and speak.
for m in /proc /sys /dev /dev/pts /dev/shm /dev/bus/usb; do
    mkdir -p "$JJP_JAIL$m"
    mountpoint -q "$JJP_JAIL$m" || mount --bind "$m" "$JJP_JAIL$m"
done
# WSLg: X11 socket + PulseAudio socket both live under /mnt/wslg.
if [ -d /mnt/wslg ]; then
    mkdir -p "$JJP_JAIL/mnt/wslg"
    mountpoint -q "$JJP_JAIL/mnt/wslg" || mount --bind /mnt/wslg "$JJP_JAIL/mnt/wslg"
fi
mkdir -p "$JJP_JAIL/tmp/.X11-unix"
mountpoint -q "$JJP_JAIL/tmp/.X11-unix" || mount --bind /tmp/.X11-unix "$JJP_JAIL/tmp/.X11-unix" 2>/dev/null

# These are separate partitions on a real machine; plain directories here.
mkdir -p "$JJP_JAIL/tmp" "$JJP_JAIL/jjpe/temp" "$JJP_JAIL/jjpe/perm"
chmod 1777 "$JJP_JAIL/tmp"

# PulseAudio refuses a root client with "Access denied" unless it has the
# desktop user's cookie - the socket is theirs, not root's.
if [ -f "$JJP_PULSE_COOKIE" ]; then
    mkdir -p "$JJP_JAIL/root/.config/pulse"
    cp -f "$JJP_PULSE_COOKIE" "$JJP_JAIL/root/.config/pulse/cookie"
    chmod 600 "$JJP_JAIL/root/.config/pulse/cookie"
fi

echo "jail    : $JJP_JAIL ($(mountpoint -q "$JJP_JAIL" && echo mounted || echo FAILED))"
echo "binds   : $(mount | grep -c "$JJP_JAIL")"
echo "X socket: $(ls "$JJP_JAIL/tmp/.X11-unix" 2>/dev/null | tr '\n' ' ')"
