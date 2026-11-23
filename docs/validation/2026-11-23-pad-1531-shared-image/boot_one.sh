#!/bin/bash
# PAD-1531 stand-in, one card: run inside `unshare -n -m` (private network + mounts, nothing reaches off the PC).
# The card's own system partition (read-only) as / under qemu-arm, its own boot hook started, then a login tried
# with the builder's and the recipient's PAD keys against 127.0.0.1 of this private network.
X=$1; OFF=$2; SIZE=$3; W=/var/tmp/pad1531
R=$W/root_$X
mkdir -p "$R"
mount --make-rprivate /
ip link set lo up
L=$(losetup -r -o "$OFF" --sizelimit "$SIZE" -f --show "$W/$X.raw")
mount -o ro "$L" "$R"
for d in data run tmp var/volatile; do if [ -d "$R/$d" ] && [ ! -L "$R/$d" ]; then mount -t tmpfs t "$R/$d"; fi; done; for d in tmp var/run var/tmp var; do [ -L "$R/$d" ] && echo "  /$d -> $(readlink "$R/$d")"; done
mount -t proc p "$R/proc"
mount -t tmpfs t "$R/dev"
mknod -m 666 "$R/dev/null" c 1 3; mknod -m 666 "$R/dev/zero" c 1 5
mknod -m 666 "$R/dev/random" c 1 8; mknod -m 666 "$R/dev/urandom" c 1 9


HOOK=$R/etc/rc5.d/S30sshd
if [ -L "$HOOK" ] || [ -e "$HOOK" ]; then
  echo "  boot hook on the card: /etc/rc5.d/S30sshd -> $(readlink "$HOOK"); starting it"
  chroot "$R" /etc/rc5.d/S30sshd start 2>&1 | sed 's/^/  hook: /' | tail -3
  sleep 4
else
  echo "  no boot hook on the card: nothing starts a server at boot"
fi
echo "  authorized_keys on the card: $(cat "$R/home/root/.ssh/authorized_keys" 2>/dev/null | awk '{print $NF}' | tr '\n' ' ' || true)"
[ -e "$R/home/root/.ssh/authorized_keys" ] || echo "  (no authorized_keys file)"
for who in ${4:-builder recipient}; do
  cp "$W/$who/pad_ed25519" "/tmp/k1531_$who"; chmod 600 "/tmp/k1531_$who"
  out=$(timeout 90 ssh -T -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
        -o IdentitiesOnly=yes -o ConnectTimeout=30 -i "/tmp/k1531_$who" root@127.0.0.1 \
        'echo LOGGED-IN as uid $(id -u) on $(cat /etc/hostname)' 2>&1 | grep -v '^Warning' | tail -1)
  echo "  $who's key: ${out:-no answer}"
done
for p in "$R/run/pad-sshd.pid" "$R/var/volatile/run/pad-sshd.pid"; do [ -s "$p" ] && kill "$(cat "$p")" 2>/dev/null; done
sleep 1
umount -l "$R/dev" "$R/proc" 2>/dev/null
for d in var/volatile tmp run data; do umount -l "$R/$d" 2>/dev/null; done
umount -l "$R"; losetup -d "$L"
