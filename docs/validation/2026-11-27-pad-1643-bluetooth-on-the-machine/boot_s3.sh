#!/bin/bash
# PAD-1643 Spike 3 stand-in machine: run inside `unshare -n -m -p -f`.  The real Fallout LE 0.82 system partition
# (unlocked, with remote access) as /, READ-ONLY, under qemu-aarch64; its own boot hook starting its own dropbear.
# busybox reboot there asks process 1 to end (SIGTERM): this script is process 1 and writes that down instead.
set -u
REPO=$1; W=/var/tmp/pad1643s3; S=/mnt/c/tmp/PAD-1643/standin
R=$W/root
mkdir -p "$R" "$W/twin" "$W/before"
mount --make-rprivate /
ip link set lo up
L=$(losetup -f --show "$W/machine.img")       # a writable device mounted read-only, as a machine's card is
mount -o ro "$L" "$R"
mount -o ro,noload,loop "$W/twin.img" "$W/twin"
mount -o ro,noload,loop "$W/before.img" "$W/before"
for d in data connectivity run tmp games; do mount -t tmpfs t "$R/$d"; done
mkdir -p "$R/connectivity/dump"
[ -d "$R/var/run" ] && [ ! -L "$R/var/run" ] && mount -t tmpfs t "$R/var/run"
mount -t proc p "$R/proc"
mount -t tmpfs t "$R/dev"
for n in "null c 1 3" "zero c 1 5" "random c 1 8" "urandom c 1 9" "tty c 5 0" "console c 5 1"; do set -- $n; mknod -m 666 "$R/dev/$1" $2 $3 $4; done
echo "  root: $(grep " $R " /proc/mounts | awk '{print $4}' | cut -d, -f1) (as mounted for the machine); $(chroot "$R" /bin/sh -c 'uname -m; cat /etc/issue' | tr '\n' ' ')"
chroot "$R" /etc/init.d/S60padsshd start 2>&1 | sed 's/^/  hook: /' | tail -3
sleep 5
trap 'echo asked >> "$W/reboot-asked"' TERM
export STANDIN_ROOT=$R PAD_PLUGIN_DIR=$W/plugins PAD_E2FSPROGS_DIR=/sbin
PYTHONPATH=/var/tmp/pad1643/py:$REPO python3 "$S/proof_s3.py" "$W" &
PID=$!
RC=1
while kill -0 "$PID" 2>/dev/null; do wait "$PID"; RC=$?; done
for p in "$R"/proc/[0-9]*; do n=${p#$R/proc/}; [ "$n" != 1 ] && [ "$n" != "$$" ] && kill -9 "$n" 2>/dev/null; done
sleep 1
umount -l "$R/etc/avahi/services" "$R/dev" "$R/proc" "$R/var/run" 2>/dev/null
for d in games tmp run connectivity data; do umount -l "$R/$d" 2>/dev/null; done
umount -l "$R" "$W/twin" "$W/before"; sync
losetup -d "$L"
exit $RC
