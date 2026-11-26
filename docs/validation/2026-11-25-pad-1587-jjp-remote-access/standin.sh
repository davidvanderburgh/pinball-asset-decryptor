#!/bin/bash
# PAD-1587 proof: a JJP machine stand-in from a built install ISO, in its own mount, UTS and network namespaces.
#   standin.sh <iso>        run as root in WSL; leaves it running until /var/tmp/pad1587/stop appears
# The machine:   192.168.77.50 in netns padm  (PAD's server from the install's own systemd unit, and the install's
#                own rungame.sh loop; the game program is a stand-in: the real one needs the Sentinel key)
# The client:    192.168.77.1  in netns padc  (client.py: the app's own scan / Send / care code)
set -u
ISO=$1
T=/var/tmp/pad1587
EMU=/mnt/c/Users/david/Documents/development/pad-triage/work/tickets/PAD-1587/tools/jjp_emu
mkdir -p $T
rm -f $T/stop $T/ready
export JJP_BASE=$T/base JJP_CURRENT=$T/current
echo "== restoring the built install's partitions (tools/jjp_emu/mount.sh)"
bash $EMU/mount.sh "$ISO" > $T/mount.log 2>&1 || { tail -20 $T/mount.log; exit 1; }
tail -3 $T/mount.log
B=$JJP_BASE
for m in root perm; do mountpoint -q $B/$m || { echo "no $B/$m"; exit 1; }; done

ip netns del padm 2>/dev/null; ip netns del padc 2>/dev/null
ip netns add padm && ip netns add padc
ip link add pad1587m type veth peer name pad1587c
ip link set pad1587m netns padm && ip link set pad1587c netns padc
ip -n padm addr add 192.168.77.50/24 dev pad1587m && ip -n padm link set pad1587m up && ip -n padm link set lo up
ip -n padc addr add 192.168.77.1/24 dev pad1587c && ip -n padc link set pad1587c up && ip -n padc link set lo up
ip -n padc route add default via 192.168.77.50

cat > $T/inner.sh <<'INNER'
set -u
T=/var/tmp/pad1587; B=$T/base; S=$T/machine
mkdir -p $S $T/up $T/wk
rm -rf $T/up/* $T/wk/*
mount -t overlay overlay -o lowerdir=$B/root,upperdir=$T/up,workdir=$T/wk,metacopy=on,redirect_dir=on $S \
  || mount -t overlay overlay -o lowerdir=$B/root,upperdir=$T/up,workdir=$T/wk $S || exit 1
# the machine's perm partition: a writable copy of the install's own sda4
cp --sparse=always $B/sda4.raw $T/perm.raw
mount -o loop $T/perm.raw $S/jjpe/perm || exit 1
mount -t tmpfs tmp $S/jjpe/temp
mount -t proc proc $S/proc
mount -t sysfs sys $S/sys 2>/dev/null || true
mount -t tmpfs run $S/run; mkdir -p $S/run/lock
mount -t tmpfs tmp $S/tmp
mount -t tmpfs dev $S/dev
for n in "null c 1 3" "zero c 1 5" "random c 1 8" "urandom c 1 9" "tty c 5 0"; do set -- $n; mknod -m 666 $S/dev/$1 $2 $3 $4; done
mkdir -p $S/dev/pts; mount -t devpts -o newinstance,ptmxmode=0666 devpts $S/dev/pts; ln -sf pts/ptmx $S/dev/ptmx
hostname Wonka-standin
# what the game saves on perm, made up for the proof (the real game, which needs its key, makes the same kind)
mkdir -p $S/jjpe/perm/vf/settings $S/jjpe/perm/vf/audits
printf 'BALLS 3\nREPLAY 300000000\n' > $S/jjpe/perm/vf/settings/adjustments.cfg
printf 'GAMES_PLAYED 1587\n' > $S/jjpe/perm/vf/audits/audits.dat
printf 'DAV 9876543210\nPAD 1587000000\n' > $S/jjpe/perm/vf/hiscores.dat

# the systemd unit the hook enables, and its own start command, as systemd would run it at boot
H=$S/etc/systemd/system/multi-user.target.wants/pad-sshd.service
echo "hook: $(readlink $H)"
start=$(sed -n 's/^ExecStart=//p' $S/etc/systemd/system/pad-sshd.service)
echo "unit ExecStart: $start"
chroot $S /bin/sh -c "$start" > $T/sshd-start.log 2>&1
echo "server start rc=$? $(cat $T/sshd-start.log | tail -2)"

# the stand-in game, put over the game program in the loop's own view only (the machine's files stay the install's)
cat > $T/standin-game <<'GAME'
#!/bin/sh
echo "$(date +%T) stand-in game started, pid $$, message picture $(sha1sum /jjpe/gen1/miscfiles/graphics/JJP_logo_message.png | cut -c1-12)" >> /jjpe/temp/standin-game.log
while true; do sleep 1; done
GAME
chmod 755 $T/standin-game
unshare -m --propagation private bash -c "mount --bind $T/standin-game $S/jjpe/gen1/Wonka/game && exec setpriv --bounding-set -sys_boot chroot $S /jjpe/gen1/scripts/rungame.sh" </dev/null >/dev/null 2>&1 &
sleep 8
echo "loop: $(cat $S/jjpe/temp/standin-game.log 2>/dev/null)"
grep -c . $S/jjpe/temp/game.log 2>/dev/null | sed 's/^/game.log lines: /'
touch $T/ready
while [ ! -f $T/stop ]; do sleep 2; done
echo "== stopping"
for p in $(ls /proc | grep -E '^[0-9]+$'); do
  r=$(readlink /proc/$p/root 2>/dev/null); [ "$r" = "$S" ] && kill -9 $p 2>/dev/null
done
sleep 1
for m in $S/dev/pts $S/dev $S/tmp $S/run $S/sys $S/proc $S/jjpe/temp $S/jjpe/perm $S; do umount -l $m 2>/dev/null; done
echo stopped
INNER
ip netns exec padm unshare -m -u --propagation private bash $T/inner.sh
ip netns del padm; ip netns del padc
for m in $B/root $B/perm $B/boot $B/iso; do mountpoint -q $m && umount -l $m; done
echo "== stand-in gone"
