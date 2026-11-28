#!/bin/bash
# PAD-1643 Spike 3 stand-in proof (root, WSL Ubuntu): the real Fallout LE 0.82 system partition as a machine, and
# the app's own "put it on the machine" code against it over SSH.
set -u
export HOME=/home/david
W=/var/tmp/pad1643s3
REPO=/mnt/c/Users/david/Documents/development/pad-triage/work/tickets/PAD-1643
S=/mnt/c/tmp/PAD-1643/standin
mkdir -p "$W"
find "$W" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
cd "$W"
mkdir -p "$W/plugins"
cp -r "/mnt/c/Users/david/AppData/Roaming/pinball_decryptor/plugins/bluetooth" "$W/plugins/"
export PAD_PLUGIN_DIR=$W/plugins PAD_E2FSPROGS_DIR=/sbin
PY=/var/tmp/pad1643/py
PYTHONPATH=$PY:$REPO python3 "$S/make_s3.py" "$REPO" "$W" /mnt/c/tmp/PAD-1643/s3/rootfs.img 2>&1 | tee "$W/make.log"
[ -f "$W/twin.img" ] || { echo "make failed"; exit 1; }
if [ "${1:-}" = peek ]; then
    mkdir -p "$W/peek"; mount -o ro,noload,loop "$W/before.img" "$W/peek"; cd "$W/peek"
    ls -la . sbin/reboot sbin/halt bin/sh usr/bin/sha1sum usr/bin/readlink 2>&1 | head -60
    cat etc/issue; grep -n "KEYDIR\|PIDFILE\|mount\|mkdir" etc/init.d/sshd | head -20; cat etc/fstab
    cd /; umount "$W/peek"; exit 0
fi
unshare -n -m -p -f bash "$S/boot_s3.sh" "$REPO"
echo "proof_s3.py exit: $?"
e2fsck -fn "$W/machine.img" > "$W/fsck.log" 2>&1; echo "VERDICT the system partition is a clean filesystem afterwards: $([ $? = 0 ] && echo PASS || echo FAIL)  ($(tail -1 "$W/fsck.log"))"
