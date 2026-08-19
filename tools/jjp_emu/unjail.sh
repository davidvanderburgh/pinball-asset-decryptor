#!/bin/bash
# Tear the jail down, innermost mount first.  Lazy unmounts because a wedged
# game can pin a bind mount, and a pinned mount is how the Spike 2 rig once
# needed a full `wsl --shutdown` to recover.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/padpath.sh"
[ "$(id -u)" = "0" ] || { echo "unjail.sh: must run as root" >&2; exit 2; }

bash "$HERE/killgame.sh" || echo "warning: game processes survived; unmounting anyway"

for m in /tmp/.X11-unix /mnt/wslg /dev/bus/usb /dev/shm /dev/pts /dev /sys /proc; do
    umount -l "$JJP_JAIL$m" 2>/dev/null
done
umount -l "$JJP_JAIL" 2>/dev/null
umount -l "$JJP_OVL"  2>/dev/null
echo "remaining jail mounts: $(mount | grep -c "$JJP_JAIL")"
