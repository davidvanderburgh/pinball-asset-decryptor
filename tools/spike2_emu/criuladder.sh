#!/bin/bash
# Can CRIU checkpoint and restore a QEMU-USER process? (item 13, save states)
#
#   wsl -u root -e bash tools/spike2_emu/criuladder.sh [rung ...]
#
# With no argument it runs every rung. With arguments (`criuladder.sh D`, or
# `criuladder.sh B C`) it runs only those - built for iterating on one rung
# without paying ~25 s for each of the ones already known to pass. The
# negative control ALWAYS runs first whatever was asked for, because it is
# what makes any other result mean something.
#
# Needs root (criu does). Starts NO emulator run, touches nothing the rig
# owns, and never goes near the game. All rungs take about three minutes.
#
# WHY IT EXISTS. Item 13's whole design rests on one untested assumption: that
# criu can dump and restore the guest, which is qemu-arm-static with a JIT and
# a multi-gigabyte reserved guest address space. Nobody had ever pointed criu
# at a qemu-user process. If it cannot, the design dies whatever else is true,
# and it dies cheaply here rather than expensively inside a live game.
#
# THE LADDER, and the order is the point - each rung adds exactly one thing, so
# a failure names its own cause instead of leaving a shrug:
#   A. an ordinary x86-64 process          -> is criu working AT ALL here
#   B. the same program built for ARM,
#      running under qemu-arm-static       -> can criu dump QEMU-USER
#   C. the same, with three worker threads -> guest threads map to host threads
#   D. the same, inside run_game.sh's OWN namespace shape - unshare -r -m -p -f,
#      setsid, proc + tmpfs mounts, a self-bind, then chroot
#                                          -> can criu dump the CONTAINER
#   E. the same, with the binary EXECUTED FROM a fuse2fs mount made OUTSIDE
#      the namespace and bind mounted in   -> the card, which is how the real
#                                             game ELF is mapped
#   F. the subject HOLDS AN OPEN FD to a pty slave whose MASTER a host
#      process keeps, bound onto /dev/ttymxc1, and the restore attaches it
#      to a NEW pty from a RESTARTED holder -> the node bus
#   G. the subject holds a file-backed MAP_SHARED mapping that a host
#      process KEEPS WRITING across the checkpoint
#                                          -> the padled/padsw/padgl rings
#
# HOW EACH RUNG IS JUDGED, and this is the part that matters. A restored
# process and a freshly restarted one look IDENTICAL from outside - both are
# alive, both are writing. This repo has been fooled by exactly that shape
# before ("alive after 2 s proves nothing", item 12). So the test program
# counts, and a rung passes only if the counter CONTINUES: a restart begins at
# 1 again and fails on its own evidence. Alive is not the test; continuity is.

set -u
WORK=/var/tmp/criuladder
CRIU=${CRIU:-/var/tmp/criubuild/criu/criu/criu}
# fuse2fs is NOT packaged here either - it is the hand-extracted binary
# cardmount.sh uses, under david's home, runnable by root with the same
# LD_LIBRARY_PATH trick cardmount.sh itself uses.
FUSE2FS=${FUSE2FS:-/home/david/local/usr/bin/fuse2fs}
FUSELIB=/home/david/local/lib/x86_64-linux-gnu

[ "$(id -u)" = 0 ] || { echo "criuladder: needs root (criu does). Use: wsl -u root -e bash $0"; exit 2; }
[ -x "$CRIU" ] || { echo "criuladder: no criu at $CRIU - build it first, or set CRIU="; exit 2; }

# Which rungs to run. No argument = all of them. The control is not optional.
RUNGS=${*:-A B C D E F G}

# A previous run may have left the card mounted; rm -rf THROUGH a live fuse
# mount would try to delete the (read-only) card contents and then fail to
# remove the directory, so unmount first, always.
mountpoint -q "$WORK/cardmnt" 2>/dev/null && umount -l "$WORK/cardmnt"
rm -rf "$WORK"; mkdir -p "$WORK/dumpA" "$WORK/dumpB" "$WORK/dumpC" \
                        "$WORK/dumpD" "$WORK/dumpE" "$WORK/dumpF" "$WORK/dumpG"
cd "$WORK" || exit 2

# ---------------------------------------------------------------- the subject
# Single process, no forks, no held fds: it re-opens the count file each pass
# and closes it. That is deliberate. These rungs answer "can the address space
# come back", and holding fds would fold a second question into the same
# answer. What that leaves untested is listed at the end rather than assumed.
cat > count.c <<'EOF'
#include <stdio.h>
#include <unistd.h>
int main(int argc, char **argv)
{
    long i = 0;
    for (;;) {
        FILE *f = fopen(argv[1], "w");
        if (f) { fprintf(f, "%ld\n", ++i); fclose(f); }
        usleep(200000);
    }
    return 0;
}
EOF

# THE THREADED SUBJECT, for rung C. The real guest runs several threads and
# qemu-user maps each guest thread onto a host thread, so a single-process rung
# does not cover it.
#
# It writes the MINIMUM of the three worker counters, not the sum, and that is
# the whole trick: the file only advances if EVERY thread is still running.
# A sum would keep climbing with two threads out of three alive and the rung
# would pass a restore that quietly lost one.
cat > countthr.c <<'EOF'
#include <stdio.h>
#include <unistd.h>
#include <pthread.h>
static volatile long c[3];
static void *worker(void *a) { long i = (long)a; for (;;) { c[i]++; usleep(200000); } return 0; }
int main(int argc, char **argv)
{
    pthread_t t[3];
    long i;
    for (i = 0; i < 3; i++) pthread_create(&t[i], 0, worker, (void *)i);
    for (;;) {
        long m = c[0];
        if (c[1] < m) m = c[1];
        if (c[2] < m) m = c[2];
        FILE *f = fopen(argv[1], "w");
        if (f) { fprintf(f, "%ld\n", m); fclose(f); }
        usleep(100000);
    }
    return 0;
}
EOF

# THE TTY SUBJECT, for rung F. Same counter, but it also opens /dev/ttymxc1
# and HOLDS the fd, writing a byte down it each loop the way the game talks
# to its node bus. O_NOCTTY is deliberate and load-bearing: the subject is a
# session leader with no controlling tty, so a bare open() of a pty slave
# would ACQUIRE it as ctty, and a controlling tty drags session semantics
# into the dump (the --shell-job territory this ladder exists to stay out
# of). NOTE the real game may well open ttymxc1 WITHOUT O_NOCTTY - whether
# its dump then needs more than --external tty[] is an open question the
# ladder does not answer.
cat > counttty.c <<'EOF'
#include <stdio.h>
#include <unistd.h>
#include <fcntl.h>
int main(int argc, char **argv)
{
    long i = 0;
    int tfd = open("/dev/ttymxc1", O_RDWR | O_NOCTTY);
    if (tfd < 0) return 48;
    for (;;) {
        FILE *f = fopen(argv[1], "w");
        if (f) { fprintf(f, "%ld\n", ++i); fclose(f); }
        if (write(tfd, ".", 1) < 0) { /* master gone; keep counting */ }
        usleep(200000);
    }
    return 0;
}
EOF

# THE RING SUBJECT AND ITS HOST WRITER, for rung G. The writer (x86, host
# side, NOT dumped) increments a counter in a file-backed MAP_SHARED page
# five times a second and NEVER STOPS - through the dump, the kill and the
# restore, like padglhost writing the switch ring while the guest is frozen.
# The subject maps the same file and copies whatever it currently reads into
# ring.out beside its own counter. After the restore, ring.out advancing past
# what the page held BEFORE the restore proves the remapped page is the LIVE
# one the host is still writing - not a stale copy restored from images.
cat > countring.c <<'EOF'
#include <stdio.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/mman.h>
int main(int argc, char **argv)
{
    long i = 0;
    int rfd = open("/data/ring", O_RDONLY);
    if (rfd < 0) return 49;
    volatile unsigned *ring = mmap(0, 4096, PROT_READ, MAP_SHARED, rfd, 0);
    if (ring == MAP_FAILED) return 50;
    for (;;) {
        FILE *f = fopen(argv[1], "w");
        if (f) { fprintf(f, "%ld\n", ++i); fclose(f); }
        f = fopen("/data/ring.out", "w");
        if (f) { fprintf(f, "%u\n", *ring); fclose(f); }
        usleep(200000);
    }
    return 0;
}
EOF

cat > ringwrite.c <<'EOF'
#include <unistd.h>
#include <fcntl.h>
#include <sys/mman.h>
int main(int argc, char **argv)
{
    int fd = open(argv[1], O_RDWR);
    if (fd < 0) return 1;
    volatile unsigned *ring = mmap(0, 4096, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (ring == MAP_FAILED) return 1;
    for (;;) { (*ring)++; usleep(200000); }
    return 0;
}
EOF

# THE PTY HOLDER, for rung F - the ladder's stand-in for nodebus.py, which
# does exactly this: create a pty, publish the slave path, hold the master
# and service it. Prints "slavepath rdev_hex dev_hex" (criu's tty[] key is
# %x:%x of st_rdev:st_dev) to the info file, then drains the master forever.
cat > ptyhold.py <<'EOF'
import os, sys, select
m, s = os.openpty()
path = os.ttyname(s)
st = os.stat(path)
with open(sys.argv[1] + ".tmp", "w") as f:
    f.write("%s %x %x\n" % (path, st.st_rdev, st.st_dev))
os.rename(sys.argv[1] + ".tmp", sys.argv[1])
os.close(s)   # nodebus holds only the master; the guest owns the slave
while True:
    r, _, _ = select.select([m], [], [], 1.0)
    if m in r:
        try:
            os.read(m, 4096)
        except OSError:
            pass  # no slave open right now; keep serving
EOF

echo "=== building the subject"
gcc -O0 -o countx86 count.c || { echo "  x86 build FAILED"; exit 1; }
echo "  countx86 ok"
gcc -O0 -o ringwrite ringwrite.c || { echo "  ringwrite build FAILED"; exit 1; }
echo "  ringwrite ok (host-side ring writer)"
ARMOK=0
if command -v arm-linux-gnueabihf-gcc >/dev/null 2>&1; then
    # STATIC on purpose: a dynamic ARM binary would drag the rig's rootfs and
    # its loader into a test that is not about them.
    if arm-linux-gnueabihf-gcc -O0 -static -o countarm count.c 2>/dev/null; then
        ARMOK=1; echo "  countarm ok (static ARM)"
    else
        echo "  countarm build FAILED (no static libc for the cross target?)"
    fi
    if [ "$ARMOK" = 1 ] && arm-linux-gnueabihf-gcc -O0 -static -pthread \
            -o countarmthr countthr.c 2>/dev/null; then
        THROK=1; echo "  countarmthr ok (static ARM, 3 worker threads)"
    else
        THROK=0; echo "  countarmthr build FAILED - rung C will be skipped"
    fi
    if [ "$ARMOK" = 1 ] && arm-linux-gnueabihf-gcc -O0 -static \
            -o counttty counttty.c 2>/dev/null \
       && arm-linux-gnueabihf-gcc -O0 -static -o countring countring.c 2>/dev/null; then
        EXTOK=1; echo "  counttty + countring ok (static ARM)"
    else
        EXTOK=0; echo "  counttty/countring build FAILED - rungs F and G will be skipped"
    fi
else
    THROK=0; EXTOK=0
    echo "  no arm-linux-gnueabihf-gcc - rungs B through G will be skipped"
fi

# ------------------------------------------------- the namespace apparatus
# A miniature of run_game.sh's world for rungs D and E: a rootfs to chroot
# into, and for E a "card" - an ext4 image mounted with the SAME fuse2fs
# binary cardmount.sh uses, from OUTSIDE the namespace, with the subject
# binary executed from it the way the real game ELF is.
build_ns_world()
{
    mkdir -p "$WORK/rootfs/data" "$WORK/rootfs/proc" "$WORK/rootfs/tmp" \
             "$WORK/rootfs/card" "$WORK/rootfs/dev" "$WORK/cardmnt"
    : > "$WORK/rootfs/dev/null"   # placeholder a host device gets bound onto
    # Both binaries the container needs post-pivot live IN the rootfs:
    # - qemu, because the subject is exec'd through THIS copy explicitly. Via
    #   binfmt it would be the host's arm-binfmt-P, whose text mapping sits
    #   OUTSIDE the pivoted root and criu could not resolve the file. The real
    #   rig runs the game via binfmt today (flags POF) and will need the same
    #   treatment - an explicit qemu from inside the rootfs - to be dumpable.
    # - a STATIC busybox for the post-pivot umount of the old root. Host tools
    #   are dynamic and their loader paths die with the pivot. Note
    #   busybox-initramfs ships a DYNAMIC busybox on noble; the static one is
    #   the busybox-static package.
    cp /usr/bin/qemu-arm-static "$WORK/rootfs/qemu-arm-static"
    cp /bin/busybox "$WORK/rootfs/busybox"
    cp "$WORK/countarmthr" "$WORK/rootfs/countarmthr"
    if [ "${EXTOK:-0}" = 1 ]; then
        cp "$WORK/counttty" "$WORK/rootfs/counttty"
        cp "$WORK/countring" "$WORK/rootfs/countring"
    fi
    : > "$WORK/rootfs/dev/ttymxc1"       # placeholder the pty slave binds onto
    # the ring: one shared page a host writer and the guest both map
    truncate -s 4096 "$WORK/rootfs/data/ring"

    # The inner script - what run_game.sh's INNER heredoc is to the real rig.
    # It runs as pid 1 of the new pid namespace (via unshare -p -f), as root
    # of the new user namespace (via -r), does the mounts, and execs through
    # chroot into qemu. Kept to the same shapes as the real one: a proc
    # mount, a tmpfs, a directory bound onto itself, and (rung E) a fuse
    # mount made outside the namespace and bind mounted in.
    # ★★ PIVOT_ROOT, NOT CHROOT, AND IT IS CRIU THAT FORCES IT. Two errors,
    # met in order, decided this script's shape - and run_game.sh will need
    # the same change before the real guest can ever be checkpointed:
    #
    #  1. chroot into a plain directory: criu cannot stitch the task's mount
    #     tree at all -
    #       mnt: No parent found for mountpoint 600 (@./data)
    #  2. chroot into a self-bound directory (task root IS a mount): criu
    #     still refuses -
    #       mnt: The root task has another root than mntns:
    #       /var/tmp/criuladder/rootfs
    #     i.e. the task's root must BE the mount namespace's root. Only
    #     pivot_root does that; no amount of chroot can.
    #
    # The pivot buys a second thing for free: after it, the ENTIRE inherited
    # host tree (39 mounts on this WSL - four 9p, four overlay, an iso9660,
    # /init...) hangs off /oldroot and one lazy umount detaches all of it.
    # What is left is a five-mount namespace criu can actually restore,
    # instead of one carrying every WSL mount as a dump liability.
    # Ordering inside: every mount is made with HOST tools BEFORE the pivot
    # (child mounts ride along with the root swap), because after it the host's
    # dynamic binaries cannot run - their loader paths died with the old root.
    # Post-pivot there are exactly three commands and each is self-contained:
    # bash's own cd builtin, the static busybox, and the rootfs's qemu.
    cat > "$WORK/nsinner.sh" <<'EOF'
R="$1"; BIN="$2"; CFILE="$3"; WANTCARD="$4"; TTYSLAVE="$5"
mount --bind "$R" "$R"                 || exit 39   # pivot_root wants a mount
mount -t proc proc "$R/proc"           || exit 40
mount -t tmpfs tmpfs "$R/tmp"          || exit 41
mount --bind "$R/data" "$R/data"       || exit 42
# run_game.sh's own device idiom: a host device node bound onto a placeholder
# file. Needed here because the subject's stdio has to point INSIDE the
# container - its start-time fds are host files whose mounts leave the
# namespace with the pivot, and criu refuses any fd it cannot resolve:
#   Error (criu/files-reg.c:1790): Can't lookup mount=101 for fd=0 path=/dev/null
mount --bind /dev/null "$R/dev/null"   || exit 47
if [ "$TTYSLAVE" != none ]; then
    # the pty slave, master held by a host process - run_game.sh's ttymxc1
    mount --bind "$TTYSLAVE" "$R/dev/ttymxc1" || exit 48
fi
if [ "$WANTCARD" = card ]; then
    # made OUTSIDE the namespace (like cardmount.sh's) and bind mounted in
    mount --bind /var/tmp/criuladder/cardmnt "$R/card" || exit 43
fi
cd "$R"                                || exit 44
mkdir -p oldroot
pivot_root . oldroot                   || exit 45
cd /
/busybox umount -l /oldroot            || exit 46
exec /qemu-arm-static "$BIN" "$CFILE" </dev/null >/dev/null 2>&1
EOF

    # The RESTORE side needs its own namespace hygiene. criu's compat mount
    # engine rebuilds the restored mntns by umounting, one by one, every mount
    # in a copy of the namespace criu itself runs in - and several WSL mounts
    # refuse a plain umount with EINVAL: /init (fstype rootfs) first, then
    # /dev/pts, and the list was growing one run at a time:
    #   Error (criu/mount.c:2809): mnt: Can't umount at ./init: Invalid argument
    #   Error (criu/mount.c:2809): mnt: Can't umount at ./dev/pts: Invalid argument
    # It is not a per-mount problem: EVERY WSL mount refuses - /init, then
    # /dev/pts, then /dev, then /proc itself, each EINVAL - because they are
    # init-namespace mounts the kernel has locked against exactly this. A
    # mount WE make in our own private namespace carries none of that. So:
    # detach EVERYTHING, including /proc, then mount a FRESH proc for criu
    # to find - the engine can umount that one, because it is ours.
    # /proc goes LAST, in its own pass, and the reason is a trap that cost a
    # debugging round: umount(1) reads /proc/self/mountinfo to resolve every
    # target, and sort -r orders /proc before /mnt and /init - so the first
    # version detached /proc mid-loop and every umount after it silently
    # failed into the 2>/dev/null. The cleaning claimed to have run and had
    # not, which is exactly the confident-zero shape alive.sh once had.
    # The last piece is criu's `--root`: prepare_mnt_ns() SKIPS its whole
    # cleaning phase when --root is given (mount.c:3704 `if (!opts.root)`),
    # expecting the CALLER to have pre-mounted the container's root at that
    # path - the LXC flow. Without it the cleanup tries to umount the copied
    # namespace from INSIDE the restored user namespace, where every copied
    # mount is MNT_LOCKED and even a fresh proc of our own refuses with
    # EINVAL. So this script also re-binds the rootfs, and the caller passes
    # --root pointing at it.
    # KEPT mounts, each because a restore external resolves through it - with
    # --root skipping the cleaning phase, keeping a mount costs nothing:
    #  - the card mount: --external mnt[card]:...cardmnt binds from it;
    #    stripped, the external would point at an empty directory.
    #  - /dev/pts (and /dev, whose lazy detach would take the child with it):
    #    rung F's replacement pty slave lives there, and its restore died
    #    with "Can't bind-mount at ...(yard)/dev/ttymxc1: No such file or
    #    directory" while it was stripped - the external's SOURCE is resolved
    #    in criu's own namespace, this one.
    cat > "$WORK/nsclean.sh" <<'EOF'
mount --make-rprivate /
awk '$5 != "/" && $5 != "/proc" && $5 != "/dev" && $5 != "/dev/pts" \
     && $5 != "/var/tmp/criuladder/cardmnt" { print $5 }' /proc/self/mountinfo \
    | sort -r | while read -r mp; do
    umount -l "$mp" 2>/dev/null
done
umount -l /proc 2>/dev/null
mount -t proc proc /proc
mount --bind /var/tmp/criuladder/rootfs /var/tmp/criuladder/rootfs
exec "$@"
EOF

    CARDOK=0
    if [ -x "$FUSE2FS" ]; then
        # A 16 MB ext4 "card" carrying the subject binary, populated at mke2fs
        # time (-d) so nothing ever mounts it read-write.
        mkdir -p "$WORK/cardpop"
        cp "$WORK/countarmthr" "$WORK/cardpop/countarmthr"
        truncate -s 16M "$WORK/card.raw"
        if mke2fs -q -F -t ext4 -d "$WORK/cardpop" "$WORK/card.raw" 2>/dev/null; then
            if LD_LIBRARY_PATH="$FUSELIB" "$FUSE2FS" -o ro "$WORK/card.raw" \
                    "$WORK/cardmnt" >/dev/null 2>&1 \
               && [ -x "$WORK/cardmnt/countarmthr" ]; then
                CARDOK=1
                echo "  card ok (fuse2fs, ro, subject binary on it)"
            else
                echo "  card mount FAILED - rung E will be skipped"
            fi
        else
            echo "  mke2fs FAILED - rung E will be skipped"
        fi
    else
        echo "  no fuse2fs at $FUSE2FS - rung E will be skipped"
    fi
}

# --------------------------------------------------------------- the judge
# Everything from "the subject is up" to the verdict, shared by the plain
# rungs and the namespaced ones so the discriminator - the part that could
# quietly rot into passing restarts - exists exactly ONCE.
#
# DUMP_XTRA / RESTORE_XTRA are arrays the caller may fill with extra criu
# flags (the --external incantations rungs D and E exist to discover). Both
# are reset after use so one rung's flags cannot leak into the next.
#
# Three more hooks, all optional, all for the helper-restart window between
# the kill and the restore - the exact window the real design lives in
# (checkpoint the guest, RESTART the host helpers, restore):
#   PRE_RESTORE_CMD   - eval'd after the freeze check, before the restore.
#                       Rung F kills the pty holder and starts a fresh one
#                       here; rung G snapshots the ring value the restored
#                       mapping must then overtake.
#   RESTORE_TTYFD_FILE- a file whose first field is a tty path; the judge
#                       opens it on fd 9 for criu's --inherit-fd. Read AFTER
#                       PRE_RESTORE_CMD, because that is what creates it.
#   RING_OUT          - a file the restored subject keeps writing the mapped
#                       ring's current value into; the judge requires it to
#                       EXCEED $RING_MIN (set by PRE_RESTORE_CMD) - proof the
#                       remapped page is the live one the host writer is
#                       still advancing, not a stale copy out of the images.
DUMP_XTRA=(); RESTORE_XTRA=()
PRE_RESTORE_CMD=""; RESTORE_TTYFD_FILE=""; RING_OUT=""; RING_MIN=0
judge()
{
    local DDIR=$1 CFILE=$2 PID=$3 CLEANPAT=$4
    # ★ RUN IT LONG BEFORE DUMPING, AND THAT IS THE TEST'S WHOLE VALIDITY.
    # The pass condition below is "the counter is higher after the restore than
    # it was when frozen". At 5 counts/s a FRESH process reaches ~20 in the
    # 4 s observation window, so freezing at 10 would let a restart clear the
    # bar and be scored a restore - which is the exact failure this rung
    # exists to detect. Running ~12 s first puts the frozen value near 60,
    # about 3x what any restart could reach before it is read. The margin is
    # printed with the result so it can be checked rather than trusted.
    sleep 12

    if ! kill -0 "$PID" 2>/dev/null; then
        echo "  FAIL  subject died before the dump (it never ran)"
        return 1
    fi
    local V1; V1=$(cat "$CFILE" 2>/dev/null)
    echo "  subject pid $PID, counter at $V1"
    [ -n "$V1" ] || { echo "  FAIL  subject wrote no counter"; kill -9 "$PID" 2>/dev/null; return 1; }

    echo "  dumping..."
    "$CRIU" dump -t "$PID" -D "$DDIR" -v4 -o dump.log --leave-stopped \
        ${DUMP_XTRA[@]+"${DUMP_XTRA[@]}"} 2>&1 | tail -3
    local DRC=${PIPESTATUS[0]}
    # JUDGE THE DUMP ON ITS EXIT CODE AND ITS OWN LOG, NOT ON THE IMAGES.
    # criu writes core-*.img, mm-*.img and pages-1.img BEFORE it gets to the
    # step that fails, so a dump that ends in "Dumping FAILED" still leaves a
    # convincing directory behind. The first version of this script tested for
    # those files and called a failed dump a success - the same partial-output
    # trap this repo has hit with "alive after 2 s".
    if [ "$DRC" != 0 ] || grep -aq 'Dumping FAILED' "$DDIR/dump.log" 2>/dev/null; then
        echo "  FAIL  dump failed (exit $DRC)"
        echo "  --- dump errors:"
        grep -aE 'Error' "$DDIR/dump.log" 2>/dev/null | tail -8 | sed 's/^/      /'
        kill -9 "$PID" 2>/dev/null
        return 1
    fi
    echo "  dump ok ($(du -sh "$DDIR" 2>/dev/null | cut -f1), $(ls "$DDIR"/*.img 2>/dev/null | wc -l) images)"

    # --leave-stopped leaves it SIGSTOPped; kill it so the restore cannot be
    # confused with the original still running. That confusion is not
    # hypothetical: without this the counter keeps advancing and every rung
    # "passes".
    kill -9 "$PID" 2>/dev/null
    sleep 1
    local V2; V2=$(cat "$CFILE" 2>/dev/null)
    sleep 1
    local V3; V3=$(cat "$CFILE" 2>/dev/null)
    if [ "$V2" != "$V3" ]; then
        echo "  FAIL  counter still moving after the kill ($V2 -> $V3) - the"
        echo "        original is alive, so any 'restore' below proves nothing"
        return 1
    fi
    echo "  original dead, counter frozen at $V3"

    if [ -n "$PRE_RESTORE_CMD" ]; then
        eval "$PRE_RESTORE_CMD" || { echo "  FAIL  pre-restore hook failed"; return 1; }
    fi
    if [ -n "$RESTORE_TTYFD_FILE" ]; then
        local TTYPATH
        TTYPATH=$(cut -d' ' -f1 "$RESTORE_TTYFD_FILE" 2>/dev/null)
        [ -e "$TTYPATH" ] || { echo "  FAIL  no replacement tty at '$TTYPATH'"; return 1; }
        # fd 9 rides plain fd inheritance through unshare/bash/exec into criu,
        # which is told with --inherit-fd that this fd IS the dumped tty.
        exec 9<>"$TTYPATH" || { echo "  FAIL  could not open $TTYPATH on fd 9"; return 1; }
        echo "  replacement tty $TTYPATH on fd 9"
    fi

    echo "  restoring..."
    # --pidfile: the restored root's host pid, for a deterministic kill. The
    # pattern kill alone was measured NOT to work on the container rungs -
    # see the cleanup comment below.
    local RESTORE_CMD=("$CRIU" restore -D "$DDIR" -v4 -o restore.log -d
                       --pidfile "$DDIR/restored.pid"
                       ${RESTORE_XTRA[@]+"${RESTORE_XTRA[@]}"})
    if [ "${RESTORE_NSCLEAN:-0}" = 1 ]; then
        # inside a namespace stripped of the mounts criu cannot umount;
        # see nsclean.sh's comment in build_ns_world
        unshare -m bash "$WORK/nsclean.sh" "${RESTORE_CMD[@]}" 2>&1 | tail -3
    else
        "${RESTORE_CMD[@]}" 2>&1 | tail -3
    fi
    [ -n "$RESTORE_TTYFD_FILE" ] && exec 9>&-   # criu has its copy; drop ours
    sleep 3
    local V4; V4=$(cat "$CFILE" 2>/dev/null)
    local V5; sleep 1; V5=$(cat "$CFILE" 2>/dev/null)

    if [ -z "$V4" ] || [ "$V4" = "$V3" ]; then
        echo "  FAIL  nothing is counting after the restore (still $V3)"
        echo "  --- last restore errors:"
        grep -aE 'Error' "$DDIR/restore.log" 2>/dev/null | tail -10 | sed 's/^/      /'
        [ -s "$DDIR/restored.pid" ] && kill -9 "$(cat "$DDIR/restored.pid")" 2>/dev/null
        return 1
    fi
    if [ "$V5" = "$V4" ]; then
        echo "  FAIL  restored process is not advancing ($V4 twice) - alive but stuck"
        [ -s "$DDIR/restored.pid" ] && kill -9 "$(cat "$DDIR/restored.pid")" 2>/dev/null
        return 1
    fi
    # THE DISCRIMINATOR. A fresh start counts from 1; a restore resumes above
    # where the dump caught it. Anything at or below the frozen value is a
    # restart wearing a restore's clothes. See the sleep above for why the
    # frozen value is made large first - without that margin this comparison
    # is decoration.
    #
    # CEIL is what a process that started from scratch at the restore could
    # have reached by now: ~5 counts/s over the ~4 s of sleeps since. Printed
    # either way, so the margin is visible rather than claimed.
    local CEIL=25
    if [ "$V4" -le "$V3" ] 2>/dev/null; then
        echo "  FAIL  counter RESTARTED ($V3 -> $V4) - that is a new process,"
        echo "        not a restored one"
        pkill -9 -f "$CFILE" 2>/dev/null
        return 1
    fi
    if [ "$V3" -le "$CEIL" ] 2>/dev/null; then
        echo "  FAIL  inconclusive: frozen at $V3, but a FRESH start could reach"
        echo "        ~$CEIL in the same window, so '$V4 > $V3' proves nothing."
        echo "        The subject did not run long enough before the dump."
        pkill -9 -f "$CFILE" 2>/dev/null
        return 1
    fi

    # The ring freshness gate, when a rung asked for one. Continuity above
    # only proves the SUBJECT resumed; this proves its MAPPING is live: the
    # value it copies out of the shared page must have overtaken what the
    # page held before the restore, which only the host writer - running on
    # the other side of the checkpoint the whole time - can have caused.
    if [ -n "$RING_OUT" ]; then
        local RINGNOW
        RINGNOW=$(cat "$RING_OUT" 2>/dev/null)
        if [ -z "$RINGNOW" ] || [ "$RINGNOW" -le "$RING_MIN" ] 2>/dev/null; then
            echo "  FAIL  counter resumed but the mapped ring did NOT"
            echo "        (ring.out ${RINGNOW:-empty} vs $RING_MIN before the restore) -"
            echo "        the restored mapping is a stale copy, not the live page"
            [ -s "$DDIR/restored.pid" ] && kill -9 "$(cat "$DDIR/restored.pid")" 2>/dev/null
            return 1
        fi
        echo "  ring   live: $RING_MIN before the restore -> $RINGNOW read through"
        echo "         the restored mapping (the host writer never stopped)"
    fi

    echo "  PASS  counter continued: $V3 (frozen) -> $V4 -> $V5"
    echo "        (a fresh restart could only have reached ~$CEIL by now, so"
    echo "         $V4 is a resume and not a restart, by a margin of $((V4 - CEIL)))"
    # ★ SIGKILL, NOT THE DEFAULT SIGTERM, AND IT APPLIES TO THE REAL RIG TOO.
    # A container-restored subject is PID 1 OF ITS PID NAMESPACE, and a pidns
    # init silently IGNORES any signal it has no handler for - including
    # SIGTERM. Measured here: after rungs D and E, `pkill -f countarmthr`
    # reported success and killed nothing, three restored subjects survived
    # across ladder runs, and rung E then read rung D's leftover counter (168
    # where its own froze at 70) and failed its "original still alive" check.
    # SIGKILL from an ancestor namespace is what actually works. The restored
    # GAME will be the same kind of init, so any teardown of a restored guest
    # must -9 it - a plain pkill will report success and do nothing.
    if [ -s "$DDIR/restored.pid" ]; then
        kill -9 "$(cat "$DDIR/restored.pid")" 2>/dev/null
    fi
    pkill -9 -f "$CLEANPAT" 2>/dev/null
    sleep 0.5
    return 0
}

# ---------------------------------------------------------------- one rung
# name, dump dir, count file, and the command to start
rung()
{
    local NAME=$1 DDIR=$2 CFILE=$3; shift 3
    echo
    echo "=== rung $NAME"
    rm -f "$CFILE"

    # ★ THE INHERITED-PTMX TRAP, AND IT IS NOT A PROPERTY OF THIS TEST.
    # criu refuses a dump with "Found dangling tty with sid N pgid M (ptmx) on
    # peer fd 7". setsid does not help and neither does </dev/null: what it
    # objects to is an inherited FD, and MEASURED HERE, every process started
    # through wsl.exe carries TWO of them -
    #     7 -> /dev/ptmx     10 -> /dev/ptmx
    # inherited from WSL's own `login`/`bash` on pts/1 (sid 299, pgid 368).
    # The invoking shell has them, so everything it starts has them, all the
    # way down through unshare and chroot. THIS APPLIES TO THE REAL GUEST: it
    # is started by watch.sh through the same chain, so anything that ever
    # wants to checkpoint it must close these first.
    # Hence the explicit close loop rather than a redirect.
    setsid bash -c 'for fd in $(seq 3 63); do eval "exec $fd>&-" 2>/dev/null; done; exec "$@"' \
        _ "$@" "$CFILE" </dev/null >/dev/null 2>&1 &
    # $! is the subject's own pid: this script is non-interactive, so bash job
    # control is off, background jobs stay in its process group, setsid is
    # therefore NOT a group leader and does not fork - it execs straight
    # through. Verified by the pid criu reports matching this one.
    local PID=$!
    judge "$DDIR" "$CFILE" "$PID" "$(basename "$1")"
}

# ------------------------------------------------ one NAMESPACED rung (D, E)
# Same judge, different start: the subject goes through run_game.sh's own
# shape - unshare -r -m -p -f, a fresh session, proc + tmpfs mounts, a
# self-bind, then chroot - and the dump target is the PID-NAMESPACE INIT
# (qemu, at the end of an exec chain that never forks), found as the child of
# unshare. The caller sets DUMP_XTRA/RESTORE_XTRA if the attempt needs
# --external flags, because which incantation the container needs is exactly
# what these rungs exist to discover.
rungns()
{
    local NAME=$1 DDIR=$2 BIN=$3 WANTCARD=$4 TTYSLAVE=${5:-none}
    local CFILE=$WORK/rootfs/data/count
    echo
    echo "=== rung $NAME"
    rm -f "$CFILE"

    # The same fd-close loop as rung() (the wsl.exe ptmx trap), then:
    # unshare -f FORKS; the child is not a group leader, so its exec of
    # `setsid` succeeds WITHOUT forking and chains into bash -> mounts ->
    # chroot -> qemu, one pid end to end. That pid is the ns init and the
    # dump target, and it is the only child unshare has.
    setsid bash -c '
        for fd in $(seq 3 63); do eval "exec $fd>&-" 2>/dev/null; done
        exec unshare -r -m -p -f setsid bash "$@"
    ' _ "$WORK/nsinner.sh" "$WORK/rootfs" "$BIN" /data/count "$WANTCARD" "$TTYSLAVE" \
        </dev/null >"$DDIR/subject.out" 2>&1 &
    local UPID=$!
    sleep 2
    local NSPID
    NSPID=$(ps -o pid= --ppid "$UPID" 2>/dev/null | tr -d ' ' | head -1)
    if [ -z "$NSPID" ]; then
        echo "  FAIL  no namespace init under unshare (pid $UPID)"
        echo "  --- subject.out:"
        sed 's/^/      /' "$DDIR/subject.out" 2>/dev/null | tail -5
        kill -9 "$UPID" 2>/dev/null
        return 1
    fi
    echo "  unshare pid $UPID, ns init (dump target) pid $NSPID"
    judge "$DDIR" "$CFILE" "$NSPID" countarmthr
    local RC=$?
    kill -9 "$UPID" 2>/dev/null
    return $RC
}

# ---------------------------------------------------------- negative control
# ★ THE LABELLED FAILURE, and it runs FIRST on purpose.
# Rungs A and B pass only if the harness can tell a restore from a restart. So
# prove it can, on a case whose answer is known: kill the subject and START A
# NEW ONE instead of restoring. The counter goes back to 1, and the harness
# MUST call that a failure. If this control "passes", every result below it is
# worthless and the script says so and stops - a metric that cannot fail its
# own negative case has scored nothing, which is how three audio metrics in
# this repo were caught ranking a good capture below a bad one.
control()
{
    echo
    echo "=== control - a deliberate RESTART, which MUST be scored FAIL"
    local CFILE=$WORK/c.count
    rm -f "$CFILE"
    setsid bash -c 'for fd in $(seq 3 63); do eval "exec $fd>&-" 2>/dev/null; done; exec "$@"' \
        _ "$WORK/countx86" "$CFILE" </dev/null >/dev/null 2>&1 &
    local PID=$!
    sleep 12
    local V3; V3=$(cat "$CFILE" 2>/dev/null)
    kill -9 "$PID" 2>/dev/null; sleep 1
    echo "  original frozen at $V3, now starting a FRESH process"
    rm -f "$CFILE"
    setsid bash -c 'for fd in $(seq 3 63); do eval "exec $fd>&-" 2>/dev/null; done; exec "$@"' \
        _ "$WORK/countx86" "$CFILE" </dev/null >/dev/null 2>&1 &
    local NPID=$!
    sleep 4
    local V4; V4=$(cat "$CFILE" 2>/dev/null)
    kill -9 "$NPID" 2>/dev/null
    echo "  fresh process reached $V4 against a frozen $V3"
    if [ "${V4:-0}" -le "$V3" ] 2>/dev/null; then
        echo "  ok    the harness would score this FAIL (restart detected)"
        return 0
    fi
    echo "  BROKEN  the harness would score a RESTART as a PASS."
    echo "          Every rung below is meaningless. Raise the pre-dump sleep."
    return 1
}

want() { case " $RUNGS " in *" $1 "*) return 0;; *) return 1;; esac; }

# Verdicts: ok / NO / skip, per rung, so the summary can tell "not run" from
# "failed" - a skipped rung printed as a failure sends someone at a non-bug.
RA=skip; RB=skip; RC=skip; RD=skip; RE=skip

if ! control; then
    echo
    echo "=== aborting: the harness failed its own negative control"
    exit 1
fi

if want A; then
    RA=NO
    rung "A - ordinary x86-64 process" "$WORK/dumpA" "$WORK/a.count" "$WORK/countx86" && RA=ok
fi

if want B; then
    if [ "$ARMOK" = 1 ]; then
        RB=NO
        rung "B - ARM binary under qemu-arm-static" "$WORK/dumpB" "$WORK/b.count" \
             /usr/bin/qemu-arm-static "$WORK/countarm" && RB=ok
    else
        echo; echo "=== rung B SKIPPED (no ARM binary)"
    fi
fi

if want C; then
    if [ "${THROK:-0}" = 1 ]; then
        rung "C - THREADED ARM binary under qemu-arm-static" "$WORK/dumpC" "$WORK/c2.count" \
             /usr/bin/qemu-arm-static "$WORK/countarmthr" && RC=ok || RC=NO
    else
        echo; echo "=== rung C SKIPPED (no threaded ARM binary)"
    fi
fi

if want D || want E || want F || want G; then
    if [ "${THROK:-0}" = 1 ]; then
        echo
        echo "=== building the namespace world (rootfs + card)"
        build_ns_world
    else
        echo; echo "=== rungs D through G SKIPPED (no threaded ARM binary)"
    fi
fi

# The recipe rungs D-G share, discovered by D and E - see the comments where
# each part was forced: compat engine (v2 BUG_ONs), --root (skips the cleanup
# that dies on MNT_LOCKED), nsclean (strips criu's own ns), devnull external.
BASE_DUMP=(--external 'mnt[/dev/null]:devnull')
BASE_RESTORE=(--external 'mnt[devnull]:/dev/null' --mntns-compat-mode
              --root /var/tmp/criuladder/rootfs)

if want D && [ "${THROK:-0}" = 1 ]; then
    DUMP_XTRA=("${BASE_DUMP[@]}")
    RESTORE_XTRA=("${BASE_RESTORE[@]}")
    RESTORE_NSCLEAN=1
    rungns "D - namespaces + pivot_root (run_game.sh's shape)" "$WORK/dumpD" \
           /countarmthr none && RD=ok || RD=NO
    DUMP_XTRA=(); RESTORE_XTRA=(); RESTORE_NSCLEAN=0
fi

if want E && [ "${THROK:-0}" = 1 ]; then
    if [ "${CARDOK:-0}" = 1 ]; then
        # The base recipe plus the card: a fuse2fs mount made OUTSIDE the
        # namespace, bind mounted in, with the subject binary EXECUTED from
        # it - the real game ELF's exact shape. External at dump; at restore
        # the card must already be mounted again (the design restarts host
        # helpers, cardmount.sh among them) and criu binds it back in.
        DUMP_XTRA=("${BASE_DUMP[@]}" --external 'mnt[/card]:card')
        RESTORE_XTRA=("${BASE_RESTORE[@]}"
                      --external 'mnt[card]:/var/tmp/criuladder/cardmnt')
        RESTORE_NSCLEAN=1
        rungns "E - executed FROM the fuse2fs card, bind mounted in" "$WORK/dumpE" \
               /card/countarmthr card && RE=ok || RE=NO
        DUMP_XTRA=(); RESTORE_XTRA=(); RESTORE_NSCLEAN=0
    else
        echo; echo "=== rung E SKIPPED (no card)"
    fi
fi

RF=skip; RG=skip

if want F && [ "${EXTOK:-0}" = 1 ]; then
    # THE PTY, and the full helper-restart flow: holder 1 (the ladder's
    # nodebus.py stand-in) owns the master at dump; between kill and restore
    # it is killed and holder 2 started, exactly as a real restore would
    # restart the node bus; criu is handed holder 2's NEW slave on fd 9,
    # standing in for the OLD tty[] key recorded in the images.
    rm -f "$WORK/pty1.info" "$WORK/pty2.info"
    setsid python3 "$WORK/ptyhold.py" "$WORK/pty1.info" </dev/null >/dev/null 2>&1 &
    HOLD1=$!
    for _ in $(seq 50); do [ -s "$WORK/pty1.info" ] && break; sleep 0.1; done
    if [ -s "$WORK/pty1.info" ]; then
        read -r SLAVE1 RDEV1 DEV1 < "$WORK/pty1.info"
        echo
        echo "--- rung F pty: $SLAVE1 (tty[$RDEV1:$DEV1]), master held by pid $HOLD1"
        # TWO externals, one per layer, and both were measured as needed:
        # the MOUNT of the slave onto /dev/ttymxc1 (without it the dump dies
        # with "./dev/ttymxc1 doesn't have a proper root mount" - same class
        # as /dev/null), and the tty FD the subject holds (tty[rdev:dev],
        # answered at restore by --inherit-fd on fd 9).
        DUMP_XTRA=("${BASE_DUMP[@]}" --external 'mnt[/dev/ttymxc1]:ttybind'
                   --external "tty[$RDEV1:$DEV1]")
        RESTORE_XTRA=("${BASE_RESTORE[@]}" --inherit-fd "fd[9]:tty[$RDEV1:$DEV1]")
        RESTORE_NSCLEAN=1
        # The mnt external's restore half is appended INSIDE the hook: it has
        # to name pty 2's slave, which does not exist until the hook makes
        # it. The judge builds the restore command after this runs, so a
        # late append lands in it.
        PRE_RESTORE_CMD='kill -9 '$HOLD1' 2>/dev/null;
            setsid python3 "$WORK/ptyhold.py" "$WORK/pty2.info" </dev/null >/dev/null 2>&1 &
            HOLD2=$!;
            for _ in $(seq 50); do [ -s "$WORK/pty2.info" ] && break; sleep 0.1; done;
            RESTORE_XTRA+=(--external "mnt[ttybind]:$(cut -d" " -f1 "$WORK/pty2.info")");
            echo "  pty holder restarted (pid $HOLD2, was '$HOLD1')"'
        RESTORE_TTYFD_FILE=$WORK/pty2.info
        rungns "F - holds a pty slave, master OUTSIDE; restored onto a NEW pty" \
               "$WORK/dumpF" /counttty none "$SLAVE1" && RF=ok || RF=NO
        DUMP_XTRA=(); RESTORE_XTRA=(); RESTORE_NSCLEAN=0
        PRE_RESTORE_CMD=""; RESTORE_TTYFD_FILE=""
        pkill -9 -f ptyhold.py 2>/dev/null
    else
        RF=NO
        echo; echo "=== rung F FAILED to start its pty holder"
        kill -9 "$HOLD1" 2>/dev/null
    fi
fi

if want G && [ "${EXTOK:-0}" = 1 ]; then
    # THE RING: a host writer advances a file-backed MAP_SHARED page five
    # times a second and NEVER stops - the padglhost-writing-the-switch-ring
    # shape. The subject maps the same file; after the restore its view must
    # overtake the value the page held before the restore, or the mapping is
    # a stale copy. RING_MIN is snapshotted in the kill-to-restore window.
    setsid "$WORK/ringwrite" "$WORK/rootfs/data/ring" </dev/null >/dev/null 2>&1 &
    RINGPID=$!
    rm -f "$WORK/rootfs/data/ring.out"
    DUMP_XTRA=("${BASE_DUMP[@]}")
    RESTORE_XTRA=("${BASE_RESTORE[@]}")
    RESTORE_NSCLEAN=1
    PRE_RESTORE_CMD='RING_MIN=$(od -An -tu4 -N4 "$WORK/rootfs/data/ring" | tr -d " ");
        echo "  ring at $RING_MIN before the restore (writer still running)"'
    RING_OUT=$WORK/rootfs/data/ring.out
    rungns "G - file-backed MAP_SHARED ring, host writer LIVE across the checkpoint" \
           "$WORK/dumpG" /countring none && RG=ok || RG=NO
    DUMP_XTRA=(); RESTORE_XTRA=(); RESTORE_NSCLEAN=0
    PRE_RESTORE_CMD=""; RING_OUT=""; RING_MIN=0
    kill -9 "$RINGPID" 2>/dev/null
fi

echo
echo "=== verdict   (requested: $RUNGS)"
echo "  A  $RA   ordinary process - is criu working at all here"
echo "  B  $RB   qemu-user - the assumption item 13's design rests on"
echo "  C  $RC   qemu-user with threads, which the real guest has"
echo "  D  $RD   unshare -r -m -p -f + setsid + mounts + chroot - the container"
echo "  E  $RE   executed from a fuse2fs mount made outside the namespace - the card"
echo "  F  $RF   holds a pty slave (master outside), restored onto a NEW pty - the node bus"
echo "  G  $RG   MAP_SHARED ring, host writer live across the checkpoint - the rings"
echo
echo "  NOT tested by this ladder, and each is a later rung, not an assumption:"
echo "    - the LD_PRELOADed shim, and the game's own threads rather than 3 spinners"
echo "    - the subject running as david (these rungs run it as root; the rig's"
echo "      userns maps 1000->0, not 0->0)"
echo "    - a subject that opens its tty WITHOUT O_NOCTTY, the way the real game"
echo "      may - a controlling tty drags session semantics into the dump"

# Leave nothing mounted: the card fuse mount outlives the script otherwise,
# and the next run's rm -rf would fight it.
mountpoint -q "$WORK/cardmnt" 2>/dev/null && umount -l "$WORK/cardmnt"
exit 0
