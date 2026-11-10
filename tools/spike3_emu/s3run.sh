#!/bin/bash
# s3run.sh - boot a Stern Spike 3 card's own game program under qemu-aarch64,
# chroot'd into the card's own rootfs, straight out of the Spike 3 card store
# (s3store.py). PAD-1090, stage 1: the bring-up harness.
#
#   wsl -u root -e bash s3run.sh CARD.raw [--slot N] [--secs S] [--strace]
#
# THE STORE IS NEVER WRITTEN. The card's tree is the overlay's LOWER layer and
# each rig slot has its own upper layer (/var/tmp/pad-s3/slot<N>), so the game's
# settings, NVRAM and logs land in the slot. --fresh empties the slot first: the
# next boot is then the card's own first boot again.
#
#   /                overlay  lower = <tree>/rootfs        (Buildroot, aarch64)
#   /games           overlay  lower = <tree>/games         (the title; ro on a
#                                                           machine, the game
#                                                           writes nothing here)
#   /data            overlay  lower = <tree>/data          (settings: writable)
#   /connectivity    overlay  lower = <tree>/connectivity  (cache, dump, update)
#   /proc /dev/pts   real, in a private mount + pid namespace
#   /tmp /run /dev/shm /sys   tmpfs
#
# On the machine an initramfs unlocks the LUKS volumes and mounts them there;
# /etc/init.d/S95game then runs /games/game in game_monitor's restart loop. Here
# the game is exec'd directly (binfmt's qemu-aarch64 with the F flag, so nothing
# from the host is copied into the chroot), its exit code reported the way
# game_monitor reads it.
set -u
S=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CARD=""; SLOT=1; SECS=60; STRACE=0; FRESH=0; PROG=/games/game; ARGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --slot) SLOT=$2; shift ;;
        --secs) SECS=$2; shift ;;
        --strace) STRACE=1 ;;
        --fresh) FRESH=1 ;;
        --prog) PROG=$2; shift ;;
        --) shift; ARGS=("$@"); break ;;
        *) CARD=$1 ;;
    esac
    shift
done
[ -n "$CARD" ] || { echo "usage: s3run.sh CARD.raw [--slot N] [--secs S] [--strace] [--fresh]" >&2; exit 2; }
[ "$(id -u)" = 0 ] || { echo "[s3run] needs root (overlay mounts): wsl -u root -e bash s3run.sh ..." >&2; exit 2; }

TREE=$(python3 "$S/s3store.py" path "$CARD") || {
    echo "[s3run] the card is not in the Spike 3 store yet: s3store.py build $CARD" >&2; exit 1; }
SD=/var/tmp/pad-s3/slot$SLOT
LOG=$SD/run.log
[ "$FRESH" = 1 ] && rm -rf "$SD"
mkdir -p "$SD"
echo "[s3run] card tree $TREE, slot $SLOT ($SD)"

unshare -m -p -f --mount-proc=/proc bash -s "$TREE" "$SD" "$SECS" "$STRACE" "$PROG" "${ARGS[@]}" <<'INNER'
set -u
TREE=$1; SD=$2; SECS=$3; STRACE=$4; PROG=$5; shift 5
R=$SD/root
mount --make-rprivate /
ov() {  # lower mountpoint name
    mkdir -p "$SD/$3.up" "$SD/$3.wk" "$2"
    mount -t overlay overlay -o "lowerdir=$1,upperdir=$SD/$3.up,workdir=$SD/$3.wk" "$2"
}
mkdir -p "$R"
ov "$TREE/rootfs" "$R" root || { echo "[s3run] overlay on the rootfs failed" >&2; exit 1; }
for d in games data connectivity; do
    [ -d "$TREE/$d" ] || continue
    mkdir -p "$R/$d" 2>/dev/null
    ov "$TREE/$d" "$R/$d" "$d" || { echo "[s3run] overlay on /$d failed" >&2; exit 1; }
done
mount -t proc proc "$R/proc"
mount -t tmpfs tmpfs "$R/sys"
for d in tmp run dev/shm; do mkdir -p "$R/$d"; mount -t tmpfs tmpfs "$R/$d"; done
mkdir -p "$R/dev/pts"
mount -t devpts devpts "$R/dev/pts" -o newinstance,ptmxmode=0666
for f in null zero urandom random tty; do
    [ -e "$R/dev/$f" ] || touch "$R/dev/$f"
    mount --bind /dev/$f "$R/dev/$f"
done
ln -sf /proc/self/fd "$R/dev/fd" 2>/dev/null
# /dump -> /connectivity/dump on the machine (S95game makes it)
mkdir -p "$R/connectivity/dump/log"
echo "[s3run] exec $PROG $* (qemu-aarch64 via binfmt, ${SECS}s cap)"
[ "$STRACE" = 1 ] && export QEMU_STRACE=1
export HOME=/root PATH=/usr/sbin:/usr/bin:/sbin:/bin
T0=$(date +%s.%N)
# STDOUT ON A PTY. To a plain file the game's stdout is block-buffered, and
# neither a SIGKILL at the cap nor its own TERM handler (which exits without a
# flush) ever wrote it: a 30 s boot left game.out EMPTY (PAD-1090, second
# sweep). `script` gives it a terminal, so it is line-buffered as on the
# machine's console. stderr stays its own file. TERM at the cap, KILL 5 s on.
printf '%q ' "$PROG" "$@" > "$SD/.argv"
script -q -f -e -c "timeout -s TERM -k 5 $SECS chroot $R $(cat "$SD/.argv") 2> $SD/game.err < /dev/null" "$SD/game.out" > /dev/null < /dev/null   # script reads stdin - which is THIS script (bash -s)
RC=$?
# script's own exit is the child's (-e); a dumped core reads 128+signal
grep -q 'COMMAND_EXIT_CODE="134"' "$SD/game.out" && RC=134
echo "[s3run] exit $RC after $(echo "$(date +%s.%N) - $T0" | bc | cut -c1-6) s"
case $RC in
    0) echo "[s3run]   0 = RESTART REQUESTED" ;; 1) echo "[s3run]   1 = REBOOT REQUESTED" ;;
    2) echo "[s3run]   2 = EXIT REQUESTED" ;; 3) echo "[s3run]   3 = POWER LOSS" ;;
    4) echo "[s3run]   4 = FATAL ERROR" ;; 5) echo "[s3run]   5 = DISPATCH TIMEOUT" ;;
    124|143) echo "[s3run]   $RC = still running at the ${SECS}s cap (stopped with TERM)" ;;
    137) echo "[s3run]   137 = still running at the cap and ignored TERM (killed)" ;;
    *) [ "$RC" -ge 128 ] && echo "[s3run]   uncaught signal $((RC-128))"
       grep -h -m3 -E "Assertion|uncaught target signal" "$SD/game.err" | sed 's/^/[s3run]   /' ;;
esac
INNER
RC=$?
echo "[s3run] stdout: $(wc -l < "$SD/game.out") lines, stderr: $(wc -l < "$SD/game.err") lines ($SD)"
exit $RC
