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
# A jail left over another image's root is never reused (PAD-1350: two tickets'
# runs crossed while one ISO was still restoring; mount.sh switched the image, but
# the jail kept the other image's root as its lower, and the run booted the wrong
# game with no error).  Rebuilt when the rig is idle; refused while a game runs in
# it, which is somebody else's run.
if mountpoint -q "$JJP_JAIL"; then
    LOWER=$(findmnt -n -o OPTIONS "$JJP_JAIL" | tr ',' '\n' | sed -n 's/^lowerdir=//p')
    if [ -n "$LOWER" ] && [ "$LOWER" != "$JJP_ROOT" ]; then
        if pgrep -x game >/dev/null; then
            echo "jail.sh: the jail is over $LOWER (another image) and a game runs in it; stop that run first" >&2
            exit 4
        fi
        echo "jail.sh: the jail was over $LOWER, not $JJP_ROOT; rebuilding it"
        bash "$HERE/unjail.sh" >/dev/null 2>&1
    fi
fi
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
# desktop user's cookie - the socket is theirs, not root's.  Only for a run
# that asked for sound (PAD-1340): the cookie is what let a "muted" run reach
# the speakers.  audio.sh hands it in for PAD_AUDIO=1 as well.
if [ "${PAD_AUDIO:-0}" = "1" ] && [ -f "$JJP_PULSE_COOKIE" ]; then
    mkdir -p "$JJP_JAIL/root/.config/pulse"
    cp -f "$JJP_PULSE_COOKIE" "$JJP_JAIL/root/.config/pulse/cookie"
    chmod 600 "$JJP_JAIL/root/.config/pulse/cookie"
fi

# Root B of a multi-boot install ISO (item 117): its own overlay - the restored
# sda5 read-only below, a tmpfs above, because root B is mounted rw on the
# machine and the hook chowns and links inside it - at the path padselect.sh
# looks FIRST (/jjpe/multi/b), so the hook takes its "already there" branch and
# never touches /dev/disk/by-uuid.  One script, both worlds.
if mountpoint -q "$JJP_ROOTB" 2>/dev/null; then
    mountpoint -q "$JJP_OVLB" || { mkdir -p "$JJP_OVLB"; mount -t tmpfs -o "size=$JJP_OVL_SIZE" tmpfs "$JJP_OVLB"; }
    mkdir -p "$JJP_OVLB/up" "$JJP_OVLB/work" "$JJP_JAIL$JJP_MULTI_B"
    mountpoint -q "$JJP_JAIL$JJP_MULTI_B" || mount -t overlay overlay \
        -o "lowerdir=$JJP_ROOTB,upperdir=$JJP_OVLB/up,workdir=$JJP_OVLB/work" "$JJP_JAIL$JJP_MULTI_B"
fi

# A USB stick (PAD-1349).  The machine automounts a stick at /mnt/usb with
# umask=000 (70-usbautomount.rules), and the game's Update USB screen
# (checkusb.pl) tells "inserted" from "not" by that directory's mode alone:
# 0777 mounted, 0755 not.  JJP_USB=<dir> binds a folder there as the stick, so
# the screen, its hot fix and the full update path all run as on a cabinet.
# Without JJP_USB any stick a previous run left is taken out.
if [ -n "${JJP_USB:-}" ] && [ -d "$JJP_USB" ]; then
    chmod 0777 "$JJP_USB"
    mkdir -p "$JJP_JAIL/mnt/usb"
    mountpoint -q "$JJP_JAIL/mnt/usb" && umount -l "$JJP_JAIL/mnt/usb"
    mount --bind "$JJP_USB" "$JJP_JAIL/mnt/usb"
    echo "usb     : $JJP_USB at /mnt/usb"
elif mountpoint -q "$JJP_JAIL/mnt/usb" 2>/dev/null; then
    umount -l "$JJP_JAIL/mnt/usb"
fi

echo "jail    : $JJP_JAIL ($(mountpoint -q "$JJP_JAIL" && echo mounted || echo FAILED))"
echo "binds   : $(mount | grep -c "$JJP_JAIL")"
echo "X socket: $(ls "$JJP_JAIL/tmp/.X11-unix" 2>/dev/null | tr '\n' ' ')"
echo "root B  : $(mountpoint -q "$JJP_JAIL$JJP_MULTI_B" 2>/dev/null && echo "$JJP_JAIL$JJP_MULTI_B (overlay of $JJP_ROOTB)" || echo none)"
