#!/bin/bash
# PAD-1643 stand-in machine: run inside `unshare -n -m -p -f` (private network, mounts and processes; nothing reaches
# off the PC).  The card's own system partition as /, READ-ONLY as a machine has it, under qemu-arm; its own
# game_monitor (traced with sh -x) running a stand-in game; the real Godzilla Pro 1.16 game program where
# /games/game leads; its own boot hook starting its own dropbear.  Then the app's own code (proof.py) is run
# against 127.0.0.1.
set -u
OFF=$1; SIZE=$2; REPO=$3; W=/var/tmp/pad1643; S=/mnt/c/tmp/PAD-1643/standin
R=$W/root
mkdir -p "$R" "$W/twin" "$W/before"
mount --make-rprivate /
ip link set lo up
L=$(losetup -o "$OFF" --sizelimit "$SIZE" -f --show "$W/machine.raw")
LT=$(losetup -r -o "$OFF" --sizelimit "$SIZE" -f --show "$W/twin.raw")
LB=$(losetup -r -o "$OFF" --sizelimit "$SIZE" -f --show "$W/before.raw")
mount -o ro "$L" "$R"
mount -o ro,noload "$LT" "$W/twin"
mount -o ro,noload "$LB" "$W/before"
for d in data run tmp var/volatile dump; do if [ -d "$R/$d" ] && [ ! -L "$R/$d" ]; then mount -t tmpfs t "$R/$d"; fi; done
mkdir -p "$R/var/volatile/tmp" "$R/var/volatile/run"
mount -t proc p "$R/proc"
# the card's game_monitor sets the kernel's core pattern: not the PC's
mount --bind /dev/null "$R/proc/sys/kernel/core_pattern"
mount -t tmpfs t "$R/dev"
for n in "null c 1 3" "zero c 1 5" "random c 1 8" "urandom c 1 9" "tty c 5 0" "console c 5 1"; do set -- $n; mknod -m 666 "$R/dev/$1" $2 $3 $4; done
# the game partition: the real game program where the link leads, and a stand-in for game_monitor to run that
# writes down how it was started
mount -t tmpfs t "$R/games"
mkdir -p "$R/games/godzilla_pro"
cp /mnt/c/tmp/PAD-1643/game.bin "$R/games/godzilla_pro/game"; chmod 755 "$R/games/godzilla_pro/game"
ln -s godzilla_pro/game "$R/games/game"
cat > "$R/games/standin" <<'EOF'
#!/bin/sh
{ echo "STANDIN started as: $0 $*"; echo "STANDIN LD_PRELOAD=$LD_PRELOAD"; } >> /tmp/standin.log
while true; do sleep 1; done
EOF
chmod 755 "$R/games/standin"
# stand-ins bound over the card's own tools: the card is not written to make them.  reboot (sysvinit's, which
# /sbin/reboot leads to) only says it was asked; proof.py then does what a restart does.
printf '#!/bin/sh\necho asked >> /tmp/reboot-asked\n' > "$W/reboot"; chmod 755 "$W/reboot"
mount --bind "$W/reboot" "$R/sbin/reboot.sysvinit"
printf '#!/bin/sh\necho "$*" >> /tmp/dprint.log\n' > "$W/dprint"; chmod 755 "$W/dprint"
printf '#!/bin/sh\nwhile true; do sleep 1; done\n' > "$W/boot_display"; chmod 755 "$W/boot_display"
for p in /usr/local/bin/dprint /usr/local/spike/dprint; do [ -f "$R$p" ] && [ ! -L "$R$p" ] && mount --bind "$W/dprint" "$R$p"; done
for p in /usr/local/bin/boot_display /usr/local/spike/boot_display; do [ -f "$R$p" ] && [ ! -L "$R$p" ] && mount --bind "$W/boot_display" "$R$p"; done
echo "  root: $(grep " $R " /proc/mounts | awk '{print $4}' | cut -d, -f1) (as mounted for the machine)"
chroot "$R" /bin/sh -c '/bin/sh -x /etc/init.d/game_monitor /games/standin </dev/null >/tmp/gm.log 2>&1 &'
HOOK=$R/etc/rc5.d/S30sshd
echo "  boot hook: /etc/rc5.d/S30sshd -> $(readlink "$HOOK")"
chroot "$R" /etc/rc5.d/S30sshd start 2>&1 | sed 's/^/  hook: /' | tail -3
sleep 5
export STANDIN_ROOT=$R PAD_PLUGIN_DIR=$W/plugins PAD_E2FSPROGS_DIR=/sbin
PYTHONPATH=$W/py:$REPO python3 "$S/proof.py" "$W"
RC=$?
for p in "$R"/proc/[0-9]*; do n=${p#$R/proc/}; [ "$n" != 1 ] && [ "$n" != "$$" ] && kill -9 "$n" 2>/dev/null; done
sleep 1
umount -l "$R/usr/local/bin/dprint" "$R/usr/local/spike/dprint" "$R/usr/local/bin/boot_display" "$R/usr/local/spike/boot_display" 2>/dev/null
umount -l "$R/sbin/reboot.sysvinit" "$R/games" "$R/dev" "$R/proc/sys/kernel/core_pattern" "$R/proc" 2>/dev/null
for d in dump var/volatile tmp run data; do umount -l "$R/$d" 2>/dev/null; done
umount -l "$R" "$W/twin" "$W/before"; sync
losetup -d "$L" "$LT" "$LB"
exit $RC
