#!/bin/bash
# PAD-1588 stand-in machine: run inside `unshare -n -m -p -f` (private network, mounts and processes; nothing reaches
# off the PC).  The card's own system partition as /, under qemu-arm; /data/nv the Spike 2 emulator's own Godzilla LE
# settings, audits and scores; its own game_monitor running a stand-in game from /games/godzilla_le; its own boot hook
# starting its own dropbear.  Then the app's own backup code (proof.py) is run against 127.0.0.1.
set -u
OFF=$1; SIZE=$2; W=/var/tmp/pad1588; REPO=$3
R=$W/root
mkdir -p "$R"
mount --make-rprivate /
ip link set lo up
L=$(losetup -o "$OFF" --sizelimit "$SIZE" -f --show "$W/machine.raw")
mount "$L" "$R"
for d in data run tmp var/volatile dump; do if [ -d "$R/$d" ] && [ ! -L "$R/$d" ]; then mount -t tmpfs t "$R/$d"; fi; done
mkdir -p "$R/var/volatile/tmp" "$R/var/volatile/run"
mount -t proc p "$R/proc"
mount -t tmpfs t "$R/dev"
for n in "null c 1 3" "zero c 1 5" "random c 1 8" "urandom c 1 9" "tty c 5 0" "console c 5 1"; do set -- $n; mknod -m 666 "$R/dev/$1" $2 $3 $4; done
# the machine's settings, audits and scores: what the Spike 2 emulator's Godzilla LE runs wrote
mkdir -p "$R/data/nv"
cp -a /home/david/spike2root/data/nv/godzilla_le "$R/data/nv/"
echo "  /data/nv: $(find "$R/data/nv" -type f | wc -l) files, $(du -sk "$R/data/nv" | cut -f1) KB"
# the game: a stand-in program where Godzilla's would be, run by the card's own game_monitor
mount -t tmpfs t "$R/games"
mkdir -p "$R/games/godzilla_le"
printf '#!/bin/sh\nwhile true; do sleep 1; done\n' > "$R/games/godzilla_le/game"; chmod 755 "$R/games/godzilla_le/game"
ln -s godzilla_le/game "$R/games/game"
for p in /usr/local/bin/dprint /usr/local/spike/dprint; do [ -e "$R$p" ] && printf '#!/bin/sh\necho "$*" >> /tmp/dprint.log\n' > "$R$p"; done
for p in /usr/local/bin/boot_display /usr/local/spike/boot_display; do [ -e "$R$p" ] && printf '#!/bin/sh\nwhile true; do sleep 1; done\n' > "$R$p"; done
chroot "$R" /bin/sh -c '/etc/init.d/game_monitor /games/game </dev/null >/tmp/gm.log 2>&1 &'
HOOK=$R/etc/rc5.d/S30sshd
echo "  boot hook: /etc/rc5.d/S30sshd -> $(readlink "$HOOK")"
chroot "$R" /etc/rc5.d/S30sshd start 2>&1 | sed 's/^/  hook: /' | tail -3
sleep 5
export STANDIN_ROOT=$R
PYTHONPATH=$W/py:$REPO python3 /mnt/c/tmp/PAD-1588/standin/proof.py "$W"
echo "  dprint (the machine's screen) during the run: $(tr '\n' '|' < "$R/tmp/dprint.log" 2>/dev/null | cut -c1-300)"
for p in "$R"/proc/[0-9]*; do n=${p#$R/proc/}; [ "$n" != 1 ] && kill -9 "$n" 2>/dev/null; done
sleep 1
umount -l "$R/games" "$R/dev" "$R/proc" 2>/dev/null
for d in dump var/volatile tmp run data; do umount -l "$R/$d" 2>/dev/null; done
umount -l "$R"; losetup -d "$L"
